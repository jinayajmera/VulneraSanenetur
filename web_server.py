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
from robosurge.scene_state import SceneState
from robosurge.surgical_agent import SurgicalAgent, ProcedurePlan
from robosurge.procedure_validator import ProcedureValidator
from robosurge.motion_executor import MotionExecutor
from robosurge.kinematics_engine import ForwardKinematics
from robosurge.cli import (
    SharedState,
    VisionThread,
    load_tool_offset,
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

def open_serial(port: str) -> Optional[serial.Serial]:
    try:
        ser = serial.Serial(port, SERIAL_BAUD, timeout=SERIAL_TIMEOUT)
        web_state.serial_status = "CONNECTED"
        web_state.log("SYS", f"Serial opened on {port}")
        return ser
    except serial.SerialException as exc:
        web_state.serial_status = "ERROR"
        web_state.log("ALERT", f"Failed to open serial port {port}: {exc}")
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
    
    # Defaults (could be parameterized)
    port = "COM6"
    cam_index = 1
    weights = "models/robosurge_pose_best.pt"
    if not os.path.exists(weights):
        weights = "yolov8n-pose.pt" # fallback
        
    dry_run = os.environ.get("DRY_RUN", "1") == "1"
    
    web_state.dry_run = dry_run
    web_state.tool_offset = load_tool_offset()
    
    web_state.mapper = LocalAffineMapper(CALIBRATION_PHYSICAL_PTS, CALIBRATION_PIXEL_PTS)
    
    # Initialize Camera
    try:
        web_state.tracker = PoseTracker(weights_path=weights, camera_index=cam_index)
        # Attempt to open camera to check status
        cap = cv2.VideoCapture(cam_index)
        if cap.isOpened():
            web_state.camera_status = "LIVE"
            cap.release()
        else:
            web_state.camera_status = "ERROR"
            web_state.log("WARN", "Camera could not be opened.")
    except Exception as e:
        web_state.camera_status = "ERROR"
        web_state.log("ERROR", f"Camera init failed: {e}")
        
    web_state.lm_detector = LandmarkDetector(mapper=web_state.mapper)
    
    try:
        web_state.agent = SurgicalAgent()
        web_state.groq_status = "ACTIVE"
    except EnvironmentError:
        web_state.groq_status = "MISSING_KEY"
        web_state.log("ALERT", "GROQ_API_KEY missing.")
        
    web_state.validator = ProcedureValidator()
    
    if not dry_run:
        web_state.serial_conn = open_serial(port)
    else:
        web_state.serial_status = "DRY_RUN"
        web_state.log("SYS", "Operating in dry-run mode.")
        
    def serial_write(cmd: str):
        if web_state.serial_conn:
            try:
                web_state.serial_conn.write(cmd.encode("ascii"))
            except Exception as e:
                web_state.log("ERROR", f"Serial write error: {e}")
        else:
            pass # dry run
            
    web_state.executor = MotionExecutor(serial_write_fn=serial_write)
    
    if web_state.tracker:
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
    if web_state.serial_conn:
        web_state.serial_conn.close()

# --- API MODELS ---
class CommandRequest(BaseModel):
    command: str

# --- ROUTES ---
@app.get("/api/status")
def get_status():
    state = web_state.shared_state.read()
    
    # Build safe representations
    arms_data = []
    landmarks_data = []
    
    if state:
        arms_data = [{"id": a.arm_id, "x": a.x, "y": a.y, "z": a.z, "source": a.source} for a in state.arms]
        landmarks_data = [{"name": lm.name, "x": lm.x, "y": lm.y, "z": lm.z, "conf": lm.confidence} for lm in state.landmarks]

    # Convert current plan to dict if it exists
    plan_data = None
    if web_state.last_plan:
        plan = web_state.last_plan
        plan_data = {
            "procedure": plan.procedure,
            "rationale": plan.rationale,
            "duration": plan.estimated_duration_s,
            "safety_notes": plan.safety_notes,
            "arm1": {
                "id": plan.arm1.arm_id, "role": plan.arm1.role, "feed": plan.arm1.feed_rate_mm_s,
                "waypoints": [{"x": wp.x, "y": wp.y, "z": wp.z, "label": wp.label} for wp in plan.arm1.waypoints]
            },
            "arm2": {
                "id": plan.arm2.arm_id, "role": plan.arm2.role, "feed": plan.arm2.feed_rate_mm_s,
                "waypoints": [{"x": wp.x, "y": wp.y, "z": wp.z, "label": wp.label} for wp in plan.arm2.waypoints]
            }
        }
        
    validation_data = None
    if web_state.last_validation_result:
        val = web_state.last_validation_result
        validation_data = {
            "ok": val.ok,
            "errors": val.errors,
            "warnings": val.warnings
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
        },
        "planning": {
            "command": web_state.last_command,
            "plan": plan_data,
            "validation": validation_data
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
    cmd = req.command
    web_state.log("CMD", f"> {cmd}")
    web_state.last_command = cmd
    web_state.last_plan = None
    web_state.last_validation_result = None
    
    state = web_state.shared_state.read()
    if not state:
        web_state.log("WARN", "Cannot plan: No SceneState available yet.")
        raise HTTPException(status_code=400, detail="SceneState not available")
        
    if not web_state.agent:
        web_state.log("ERROR", "SurgicalAgent not initialized.")
        raise HTTPException(status_code=500, detail="Agent not available")
        
    try:
        web_state.log("SYS", "Generating procedure plan via Groq...")
        plan = web_state.agent.plan(cmd, state)
        
        web_state.log("SYS", "Applying deterministic geometry repair...")
        plan = apply_repairs(cmd, state, plan)
        
        web_state.log("SYS", "Running pure-math safety validation...")
        vresult = web_state.validator.validate(plan)
        
        web_state.last_plan = plan
        web_state.last_validation_result = vresult
        
        if vresult.ok:
            web_state.log("SYS", "Plan validated successfully. Ready for execution.")
        else:
            web_state.log("ALERT", f"Plan rejected: {vresult.summary()}")
            
        return {"status": "ok"}
    except Exception as e:
        web_state.log("ERROR", f"Planning failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/execute")
def execute_plan():
    if not web_state.last_plan:
        web_state.log("WARN", "Execute called but no plan exists.")
        raise HTTPException(status_code=400, detail="No plan to execute")
        
    if not web_state.last_validation_result or not web_state.last_validation_result.ok:
        web_state.log("ALERT", "Attempted to execute an invalid plan!")
        raise HTTPException(status_code=400, detail="Plan is not valid")
        
    web_state.log("SYS", f"Executing procedure: {web_state.last_plan.procedure}")
    
    # We run execution in a background thread so we don't block the API
    def run_exec():
        results = web_state.executor.execute(web_state.last_plan)
        for arm_id, res in results.items():
            status = "ABORTED" if res.aborted else "OK"
            web_state.log("SYS", f"Arm {arm_id} Execution: {status} in {res.duration_s:.1f}s")
            
    threading.Thread(target=run_exec, daemon=True).start()
    return {"status": "executing"}

@app.post("/api/abort")
def abort_execution():
    web_state.log("ALERT", "ABORT SIGNAL RECEIVED. Stopping motion.")
    if web_state.executor:
        web_state.executor.abort()
        
    web_state.log("ALERT", "Shutting down visual loop and exiting system...")
    if web_state.vision_thread:
        web_state.vision_thread.stop()
        
    def hard_exit():
        time.sleep(1.0) # give response time to return
        os._exit(1)
        
    threading.Thread(target=hard_exit, daemon=True).start()
    return {"status": "aborted"}

if __name__ == "__main__":
    uvicorn.run("web_server:app", host="0.0.0.0", port=8000, reload=True)
