import argparse
import asyncio
import cv2
import json
import logging
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional, Dict, Any, List

import serial
import serial.tools.list_ports
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

# RoboSurge Imports
from robosurge.sensor_fusion import (
    LocalAffineMapper,
    CALIBRATION_PHYSICAL_PTS,
    CALIBRATION_PIXEL_PTS,
    SERIAL_PORT,
    SERIAL_BAUD,
    SERIAL_TIMEOUT,
)
from robosurge.vision_pipeline import PoseTracker
from robosurge.landmark_detector import LandmarkDetector
from robosurge.scene_state import SceneState, TABLE_Z_CM, SAFE_Z_CM
from robosurge.surgical_agent import SurgicalAgent, ProcedurePlan
from robosurge.procedure_validator import ProcedureValidator
from robosurge.motion_executor import MotionExecutor
from robosurge.kinematics_engine import ForwardKinematics
from robosurge.cli import (
    SharedState,
    VisionThread,
    load_tool_offset,
    _load_robot_calibration,
    _save_robot_calibration,
    ROBOT_CALIBRATION_FILE,
    TOOL_OFFSET_FILE,
    _repair_incision_plan,
    _repair_biopsy_plan,
    _repair_cauterization_plan,
    _repair_debridement_plan,
    _repair_suturing_plan,
)

load_dotenv()
logger = logging.getLogger("RoboSurgeWeb")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

app = FastAPI(title="RoboSurge Web API")

# Enable CORS for the React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global State
class WebState:
    def __init__(self):
        self.shared_state = SharedState()
        self.mapper: Optional[LocalAffineMapper] = None
        self.tracker: Optional[PoseTracker] = None
        self.lm_detector: Optional[LandmarkDetector] = None
        self.agent: Optional[SurgicalAgent] = None
        self.validator: Optional[ProcedureValidator] = None
        self.executor: Optional[MotionExecutor] = None
        self.vision_thread: Optional[VisionThread] = None
        self.serial_conn: Optional[serial.Serial] = None
        self.dry_run: bool = False
        self.tool_offset: float = 0.0
        
        self.last_plan: Optional[ProcedurePlan] = None
        self.last_validation_result = None
        self.last_command: str = ""
        self.doctor_brief: Optional[str] = None
        self.is_doctor_edited: bool = False
        self.is_executing: bool = False
        self.last_execution_results: Optional[Dict[str, Any]] = None
        
        # System status flags
        self.camera_status = "OFFLINE"
        self.serial_status = "OFFLINE"
        self.groq_status = "OFFLINE"
        
        # Simple memory log
        self.logs: deque = deque(maxlen=100)

    def log(self, tag: str, message: str):
        timestamp = time.strftime("%H:%M:%S")
        self.logs.append({"time": timestamp, "tag": tag, "message": message})
        logger.info(f"[{tag}] {message}")

web_state = WebState()

def find_esp32_port() -> str:
    env_port = os.environ.get("SERIAL_PORT")
    if env_port:
        return env_port
    try:
        ports = list(serial.tools.list_ports.comports())
        for p in ports:
            desc = (p.description or "").lower()
            hwid = (p.hwid or "").lower()
            if "cp210" in desc or "ch340" in desc or "ftdi" in desc or "usb-uart" in desc or "uart" in desc:
                return p.device
            if "10c4:ea60" in hwid or "1a86:7523" in hwid or "0403:6001" in hwid:
                return p.device
    except Exception:
        pass
    return SERIAL_PORT

def open_serial(port: str) -> Optional[serial.Serial]:
    try:
        ser = serial.Serial(
            port=port,
            baudrate=SERIAL_BAUD,
            timeout=SERIAL_TIMEOUT,
            write_timeout=0.1
        )
        web_state.serial_status = "CONNECTED"
        web_state.log("SYS", f"Serial connection established on {port} @ {SERIAL_BAUD} baud")
        return ser
    except serial.SerialException as exc:
        web_state.serial_status = "DRY_RUN"
        web_state.log("WARN", f"Serial port {port} unavailable ({exc}) — operating in DRY_RUN.")
        return None

def apply_repairs(command: str, state: SceneState, plan: ProcedurePlan) -> ProcedurePlan:
    plan = _repair_incision_plan(command, state, plan)
    plan = _repair_biopsy_plan(command, state, plan)
    plan = _repair_cauterization_plan(command, state, plan)
    plan = _repair_debridement_plan(command, state, plan)
    plan = _repair_suturing_plan(command, state, plan)
    return plan

@app.on_event("startup")
def startup_event():
    web_state.log("SYS", "RoboSurge Web Server Initializing...")
    
    # Defaults
    port = find_esp32_port()
    cam_index = 1
    
    # Custom weights — search models/ then root
    weights_path = Path("models/robosurge_pose_best.pt")
    if not weights_path.exists():
        weights_path = Path("robosurge_pose_best.pt")
    if not weights_path.exists():
        weights_path = Path("yolov8n-pose.pt") # fallback
        
    dry_run = os.environ.get("DRY_RUN", "0") == "1"
    
    web_state.dry_run = dry_run
    web_state.tool_offset = load_tool_offset()
    
    web_state.mapper = LocalAffineMapper(CALIBRATION_PHYSICAL_PTS, CALIBRATION_PIXEL_PTS)
    web_state.lm_detector = LandmarkDetector(mapper=web_state.mapper)
    
    # Initialize Camera
    try:
        web_state.tracker = PoseTracker(weights_path=str(weights_path), camera_index=cam_index)
        cam_opened = web_state.tracker.open_camera()
        
        # If cam_index (1) failed, try fallback to camera 0
        if not cam_opened:
            web_state.log("WARN", f"Camera {cam_index} failed to open, trying fallback camera 0...")
            web_state.tracker.camera_index = 0
            cam_opened = web_state.tracker.open_camera()
            
        if cam_opened:
            web_state.camera_status = "LIVE"
            web_state.log("SYS", f"Camera online on index {web_state.tracker.camera_index}")
        else:
            web_state.camera_status = "ERROR"
            web_state.log("WARN", "Camera could not be opened.")
    except Exception as e:
        web_state.camera_status = "ERROR"
        web_state.log("ERROR", f"Camera init failed: {e}")
    
    try:
        web_state.agent = SurgicalAgent()
        web_state.groq_status = "ACTIVE"
    except EnvironmentError:
        web_state.groq_status = "MISSING_KEY"
        web_state.log("ALERT", "GROQ_API_KEY missing.")
        
    web_state.validator = ProcedureValidator()
    
    # Initialize Serial
    if not dry_run:
        web_state.serial_conn = open_serial(port)
        if web_state.serial_conn is None:
            web_state.dry_run = True
            web_state.serial_status = "DRY_RUN"
        else:
            web_state.dry_run = False
    else:
        web_state.dry_run = True
        web_state.serial_status = "DRY_RUN"
        web_state.log("SYS", "Operating in dry-run mode.")
        
    def serial_write(cmd: str) -> bool:
        if not cmd.endswith('\n'):
            cmd += '\n'
        if web_state.serial_conn and web_state.serial_conn.is_open:
            try:
                web_state.serial_conn.write(cmd.encode("ascii"))
                web_state.serial_conn.flush()
                return True
            except Exception as e:
                web_state.log("ERROR", f"Serial write error: {e}")
                return False
        else:
            return True # dry run
            
    web_state.executor = MotionExecutor(serial_write_fn=serial_write)
    
    if web_state.tracker and web_state.camera_status == "LIVE":
        web_state.vision_thread = VisionThread(
            tracker=web_state.tracker,
            mapper=web_state.mapper,
            lm_detector=web_state.lm_detector,
            shared_state=web_state.shared_state,
            tool_offset=web_state.tool_offset,
            loop_hz=10.0
        )
        web_state.vision_thread.start()
        web_state.log("SYS", "Vision thread started.")

@app.on_event("shutdown")
def shutdown_event():
    web_state.log("SYS", "Shutting down...")
    if web_state.executor:
        web_state.executor.abort()
    if web_state.vision_thread:
        web_state.vision_thread.stop()
        web_state.vision_thread.join(timeout=1.0)
    if web_state.tracker:
        web_state.tracker.release_camera()
    if web_state.serial_conn:
        web_state.serial_conn.close()

# --- API MODELS ---
class CommandRequest(BaseModel):
    command: str

class UpdateBriefRequest(BaseModel):
    brief: str

class NudgeRequest(BaseModel):
    dx: float
    dy: float

class ScaleRequest(BaseModel):
    sx: float
    sy: float

class ToolOffsetRequest(BaseModel):
    offset: float

class FKCalculationRequest(BaseModel):
    base: float
    shoulder: float
    elbow: float

class AbortRequest(BaseModel):
    hard_exit: bool = False

# --- ROUTES ---
@app.get("/api/status")
def get_status():
    state = web_state.shared_state.read()
    cal = _load_robot_calibration()
    
    # Build safe representations
    arms_data = []
    landmarks_data = []
    
    if state:
        arms_data = [{"id": a.arm_id, "x": a.x, "y": a.y, "z": a.z, "source": a.source} for a in state.arms]
        landmarks_data = [{"name": lm.name, "x": lm.x, "y": lm.y, "z": lm.z, "conf": lm.confidence} for lm in state.landmarks]

    # Convert current plan to dict if it exists
    plan_data = None
    serial_commands = []
    if web_state.last_plan:
        plan = web_state.last_plan
        plan_data = {
            "procedure": plan.procedure,
            "rationale": plan.rationale,
            "duration": plan.estimated_duration_s,
            "safety_notes": plan.safety_notes,
            "arm1": {
                "id": plan.arm1.arm_id, "role": plan.arm1.role, "feed": plan.arm1.feed_rate_mm_s,
                "waypoints": [{"x": wp.x, "y": wp.y, "z": wp.z, "label": wp.label, "dwell_s": getattr(wp, 'dwell_s', 0.0)} for wp in plan.arm1.waypoints]
            },
            "arm2": {
                "id": plan.arm2.arm_id, "role": plan.arm2.role, "feed": plan.arm2.feed_rate_mm_s,
                "waypoints": [{"x": wp.x, "y": wp.y, "z": wp.z, "label": wp.label, "dwell_s": getattr(wp, 'dwell_s', 0.0)} for wp in plan.arm2.waypoints]
            }
        }
        for arm_plan in (plan.arm1, plan.arm2):
            for wp in arm_plan.waypoints:
                serial_commands.append(f"arm{arm_plan.arm_id} {wp.x:+.2f} {wp.y:+.2f} {wp.z:.2f}   # {wp.label}")
        
    validation_data = None
    if web_state.last_validation_result:
        val = web_state.last_validation_result
        validation_data = {
            "ok": val.ok,
            "errors": val.errors,
            "warnings": val.warnings,
            "summary": val.summary()
        }

    return {
        "online": True,
        "time": time.strftime("%H:%M:%S"),
        "vitals": {
            "camera": web_state.camera_status,
            "serial": web_state.serial_status,
            "groq": web_state.groq_status
        },
        "scene": {
            "arms": arms_data,
            "landmarks": landmarks_data,
            "tool_offset": web_state.tool_offset,
            "table_z": TABLE_Z_CM,
            "safe_z": SAFE_Z_CM,
        },
        "calibration": {
            "scale_x": cal.get("scale_x", 1.0),
            "scale_y": cal.get("scale_y", 1.0),
            "offset_x_cm": cal.get("offset_x_cm", 0.0),
            "offset_y_cm": cal.get("offset_y_cm", 0.0),
            "tool_z_offset_cm": web_state.tool_offset,
        },
        "planning": {
            "command": web_state.last_command,
            "plan": plan_data,
            "validation": validation_data,
            "serial_preview": serial_commands,
            "doctor_brief": web_state.doctor_brief,
            "is_doctor_edited": web_state.is_doctor_edited,
        },
        "execution": {
            "is_executing": web_state.is_executing,
            "last_results": web_state.last_execution_results,
        },
        "logs": list(web_state.logs)
    }

def generate_frames():
    while True:
        frame = web_state.shared_state.read_frame()
        if frame is not None:
            ret, buffer = cv2.imencode('.jpg', frame)
            if ret:
                frame_bytes = buffer.tobytes()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        time.sleep(0.1)

@app.get("/api/camera/feed")
def camera_feed():
    return StreamingResponse(generate_frames(), media_type="multipart/x-mixed-replace; boundary=frame")

@app.post("/api/command")
def process_command(req: CommandRequest):
    cmd = req.command.strip()
    web_state.log("CMD", f"> {cmd}")
    web_state.last_command = cmd
    web_state.last_plan = None
    web_state.last_validation_result = None
    web_state.doctor_brief = None
    web_state.is_doctor_edited = False
    
    state = web_state.shared_state.read()
    if not state:
        web_state.log("WARN", "Cannot plan: No SceneState available yet.")
        raise HTTPException(status_code=400, detail="SceneState not available")
        
    if not web_state.agent:
        web_state.log("ERROR", "SurgicalAgent not initialized.")
        raise HTTPException(status_code=500, detail="Agent not available")
        
    try:
        web_state.log("SYS", "Generating procedure plan via Groq…")
        plan = web_state.agent.plan(cmd, state)
        
        web_state.log("SYS", "Applying deterministic geometry repair…")
        plan = apply_repairs(cmd, state, plan)
        
        web_state.log("SYS", "Running pure-math safety validation…")
        validator = ProcedureValidator(landmarks=state.landmarks)
        vresult = validator.validate(plan)
        
        web_state.last_plan = plan
        web_state.last_validation_result = vresult
        
        if vresult.ok:
            web_state.log("SYS", f"Plan for '{plan.procedure.upper()}' validated successfully.")
        else:
            web_state.log("ALERT", f"Plan rejected: {vresult.summary()}")
            
        return {"status": "ok"}
    except Exception as e:
        web_state.log("ERROR", f"Planning failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/plan/update-brief")
def update_brief(req: UpdateBriefRequest):
    brief = req.brief.strip()
    if not brief:
        raise HTTPException(status_code=400, detail="Brief cannot be empty")
        
    web_state.log("CMD", f"[SURGEON BRIEF MODIFIED] > {brief}")
    
    state = web_state.shared_state.read()
    if not state:
        web_state.log("WARN", "Cannot plan: No SceneState available yet.")
        raise HTTPException(status_code=400, detail="SceneState not available")
        
    if not web_state.agent:
        web_state.log("ERROR", "SurgicalAgent not initialized.")
        raise HTTPException(status_code=500, detail="Agent not available")
        
    try:
        web_state.log("SYS", "Re-generating procedure plan from doctor's updated brief…")
        plan = web_state.agent.plan(brief, state)
        
        web_state.log("SYS", "Applying deterministic geometry repair to modified plan…")
        plan = apply_repairs(brief, state, plan)
        
        web_state.log("SYS", "Running pure-math safety validation…")
        validator = ProcedureValidator(landmarks=state.landmarks)
        vresult = validator.validate(plan)
        
        web_state.last_plan = plan
        web_state.last_validation_result = vresult
        web_state.doctor_brief = brief
        web_state.is_doctor_edited = True
        
        if vresult.ok:
            web_state.log("SYS", f"Doctor-edited plan for '{plan.procedure.upper()}' validated successfully.")
        else:
            web_state.log("ALERT", f"Doctor-edited plan rejected by safety: {vresult.summary()}")
            
        return {"status": "ok", "is_doctor_edited": True}
    except Exception as e:
        web_state.log("ERROR", f"Brief re-planning failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/execute")
def execute_plan():
    if not web_state.last_plan:
        web_state.log("WARN", "Execute called but no plan exists.")
        raise HTTPException(status_code=400, detail="No plan to execute")
        
    if not web_state.last_validation_result or not web_state.last_validation_result.ok:
        web_state.log("ALERT", "Attempted to execute an invalid plan!")
        raise HTTPException(status_code=400, detail="Plan is not valid")
        
    if web_state.is_executing:
        web_state.log("WARN", "Execution already in progress.")
        raise HTTPException(status_code=409, detail="Execution already in progress")
        
    web_state.log("SYS", f"Executing procedure: {web_state.last_plan.procedure.upper()}")
    web_state.is_executing = True
    web_state.last_execution_results = None
    
    # Run execution in a background thread so we don't block the API
    def run_exec():
        try:
            results = web_state.executor.execute(web_state.last_plan)
            formatted_results = {}
            for arm_id, res in results.items():
                status = "ABORTED" if res.aborted else "OK"
                formatted_results[f"arm{arm_id}"] = {
                    "arm_id": arm_id,
                    "status": status,
                    "aborted": res.aborted,
                    "steps_sent": res.steps_sent,
                    "duration_s": round(res.duration_s, 2),
                    "final_position": [round(c, 2) for c in res.final_position]
                }
                web_state.log("EXEC", f"Arm {arm_id} Complete: {status} in {res.duration_s:.1f}s ({res.steps_sent} steps)")
            web_state.last_execution_results = formatted_results
        except Exception as e:
            web_state.log("ERROR", f"Execution error: {e}")
        finally:
            web_state.is_executing = False
            
    threading.Thread(target=run_exec, daemon=True).start()
    return {"status": "executing"}

@app.post("/api/abort")
def abort_execution(req: Optional[AbortRequest] = None):
    web_state.log("ALERT", "ABORT SIGNAL RECEIVED. Stopping motion.")
    if web_state.executor:
        web_state.executor.abort()
    web_state.is_executing = False
    
    hard_exit = req.hard_exit if req else False
    if hard_exit:
        web_state.log("ALERT", "Hard exit requested. Shutting down...")
        if web_state.vision_thread:
            web_state.vision_thread.stop()
        def hard_exit_fn():
            time.sleep(1.0)
            os._exit(1)
        threading.Thread(target=hard_exit_fn, daemon=True).start()
        
    return {"status": "aborted"}

# --- CALIBRATION ROUTES ---
@app.get("/api/calibration")
def get_calibration():
    cal = _load_robot_calibration()
    return {
        "robot": cal,
        "tool_z_offset_cm": web_state.tool_offset,
        "table_z_cm": TABLE_Z_CM,
        "safe_z_cm": SAFE_Z_CM
    }

@app.post("/api/calibration/nudge")
def nudge_calibration(req: NudgeRequest):
    cal = _load_robot_calibration()
    cal["offset_x_cm"] += req.dx
    cal["offset_y_cm"] += req.dy
    _save_robot_calibration(cal)
    web_state.log("SYS", f"Nudged calibration by dx={req.dx:+.2f}cm, dy={req.dy:+.2f}cm")
    return {"status": "ok", "calibration": cal}

@app.post("/api/calibration/scale")
def scale_calibration(req: ScaleRequest):
    cal = _load_robot_calibration()
    cal["scale_x"] = req.sx
    cal["scale_y"] = req.sy
    _save_robot_calibration(cal)
    web_state.log("SYS", f"Updated scale: sx={req.sx:.3f}, sy={req.sy:.3f}")
    return {"status": "ok", "calibration": cal}

@app.post("/api/calibration/reset")
def reset_calibration():
    cal = {
        "scale_x": 1.0,
        "scale_y": 1.0,
        "offset_x_cm": 0.0,
        "offset_y_cm": 0.0,
    }
    _save_robot_calibration(cal)
    web_state.log("SYS", "Reset robot calibration to defaults.")
    return {"status": "ok", "calibration": cal}

@app.post("/api/calibration/tool_offset")
def update_tool_offset(req: ToolOffsetRequest):
    web_state.tool_offset = req.offset
    try:
        TOOL_OFFSET_FILE.write_text(json.dumps({"tool_z_offset_cm": req.offset}))
        web_state.log("SYS", f"Saved tool Z offset: {req.offset:.4f} cm")
    except Exception as e:
        web_state.log("WARN", f"Could not save tool offset file: {e}")
    return {"status": "ok", "tool_z_offset_cm": req.offset}

@app.post("/api/calibration/calculate_fk")
def calculate_fk_offset(req: FKCalculationRequest):
    fk = ForwardKinematics()
    result = fk.calculate_fk(req.base, req.shoulder, req.elbow)
    offset = TABLE_Z_CM - result.tip_z
    web_state.tool_offset = offset
    try:
        TOOL_OFFSET_FILE.write_text(json.dumps({"tool_z_offset_cm": offset}))
        web_state.log("SYS", f"Computed tool offset via FK: {offset:.4f} cm (tip Z: {result.tip_z:.4f} cm)")
    except Exception as e:
        web_state.log("WARN", f"Could not save tool offset file: {e}")
    return {
        "status": "ok",
        "tip_z": round(result.tip_z, 4),
        "table_z": TABLE_Z_CM,
        "tool_z_offset_cm": round(offset, 4)
    }

if __name__ == "__main__":
    uvicorn.run("web_server:app", host="0.0.0.0", port=8000, reload=True)

