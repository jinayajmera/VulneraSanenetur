"""
robosurge_cli.py — RoboSurge Phase 4
======================================
Top-level entry point.  Wires all Phase 4 modules into a live surgical command loop.

Full pipeline per command
--------------------------
  1. Vision thread: grabs frames at 10Hz, runs PoseTracker + LandmarkDetector,
     writes the latest SceneState to a shared slot.
  2. CLI thread (main): reads typed commands, calls SurgicalAgent → ProcedureValidator
     → MotionExecutor in sequence.  Blocks during execution.

Startup sequence
-----------------
  a. Open camera (PoseTracker).
  b. Connect to ESP32 serial port.
  c. Build LocalAffineMapper from calibration constants (sensor_fusion.py).
  d. Build LandmarkDetector.
  e. Run tool Z-offset calibration (or load from file).
  f. Start vision thread.
  g. Enter command loop.

Tool Z-offset calibration
--------------------------
Run with ``--calibrate`` flag.  The CLI prompts you to:
  1. Manually drive arm1 until the tip just touches the table surface.
  2. Type the current servo angles (base, shoulder, elbow).
   3. The system computes FK, measures the delta between FK Z and TABLE_Z_CM,
      and saves it to ``config/tool_offset.json``.

Usage
-----
  python main.py [--port COM6] [--cam 1] [--weights robosurge_pose_best.pt]
                 [--calibrate] [--dry-run]
  (equivalently: python -m robosurge.cli ...)

Commands (at the prompt)
------------------------
  Any natural language:  "make a 3mm incision at landmark A"
                         "retract the tissue at landmark B"
                         "go home"
                         "abort"
  "status"   — print current SceneState without planning anything
  "quit"     — exit cleanly
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import cv2
import serial
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Local imports
# ---------------------------------------------------------------------------

from .sensor_fusion import (
    LocalAffineMapper,
    CALIBRATION_PHYSICAL_PTS,
    CALIBRATION_PIXEL_PTS,
    SERIAL_PORT,
    SERIAL_BAUD,
    SERIAL_TIMEOUT,
    assign_arms,
)
from .vision_pipeline import PoseTracker

from .landmark_detector import LandmarkDetector, LandmarkFrame
from .scene_state import SceneState, ArmState, LandmarkState, TABLE_Z_CM, SAFE_Z_CM
from .surgical_agent import ArmPlan, SurgicalAgent, ProcedurePlan, SurgicalAgentError, Waypoint
from .procedure_validator import ProcedureValidator
from .motion_executor import MotionExecutor, HOME_X, HOME_Y, HOME_Z
from .kinematics_engine import ForwardKinematics

logger = logging.getLogger("RoboSurgeCLI")

# ---------------------------------------------------------------------------
# ANSI colours
# ---------------------------------------------------------------------------

_R    = "\033[0m"
_BOLD = "\033[1m"
_GRN  = "\033[92m"
_YLW  = "\033[93m"
_RED  = "\033[91m"
_CYN  = "\033[96m"
_MAG  = "\033[95m"
_DIM  = "\033[2m"

TOOL_OFFSET_FILE = Path(__file__).resolve().parents[1] / "config" / "tool_offset.json"
ROBOT_CALIBRATION_FILE = Path(__file__).resolve().parents[1] / "config" / "robot_calibration.json"
MODELS_DIR = Path(__file__).resolve().parents[1] / "models"


# ---------------------------------------------------------------------------
# Shared state between vision thread and CLI thread
# ---------------------------------------------------------------------------

class SharedState:
    """Thread-safe slot for the latest SceneState."""

    def __init__(self) -> None:
        self._lock  = threading.Lock()
        self._state: Optional[SceneState] = None
        self._frame: Optional[object]     = None   # latest annotated frame

    def write(self, state: SceneState, frame=None) -> None:
        with self._lock:
            self._state = state
            self._frame = frame

    def read(self) -> Optional[SceneState]:
        with self._lock:
            return self._state

    def read_frame(self):
        with self._lock:
            return self._frame


# ---------------------------------------------------------------------------
# Vision thread
# ---------------------------------------------------------------------------

class VisionThread(threading.Thread):
    """
    Runs at 10 Hz.  On each tick:
      1. Grab frame.
      2. Run PoseTracker → arm tip pixels.
      3. Map arm tips to physical coords via LocalAffineMapper.
      4. Run LandmarkDetector → landmark physical coords.
      5. Assemble SceneState and write to shared_state.
    """

    def __init__(
        self,
        tracker:       PoseTracker,
        mapper:        LocalAffineMapper,
        lm_detector:   LandmarkDetector,
        shared_state:  SharedState,
        tool_offset:   float = 0.0,
        loop_hz:       float = 10.0,
    ) -> None:
        super().__init__(daemon=True, name="vision_thread")
        self._tracker     = tracker
        self._mapper      = mapper
        self._lm_detector = lm_detector
        self._shared      = shared_state
        self._tool_offset = tool_offset
        self._interval    = 1.0 / loop_hz
        self._stop_event  = threading.Event()
        self._frame_count = 0

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        logger.info("Vision thread started.")
        while not self._stop_event.is_set():
            t0 = time.monotonic()
            try:
                self._tick()
            except Exception as exc:   # noqa: BLE001
                logger.error("Vision thread error: %s", exc, exc_info=True)
            sleep_for = max(0.0, self._interval - (time.monotonic() - t0))
            time.sleep(sleep_for)
        logger.info("Vision thread stopped.")

    def _tick(self) -> None:
        frame = self._tracker.grab_frame()
        cv2.imwrite('live_calib_check.png', frame)
        if self._frame_count <= 3:
            logger.warning("LIVE FRAME SHAPE: %s", None if frame is None else frame.shape)
        self._frame_count += 1

        # ── Arm detection ────────────────────────────────────────────────
        # Arms are physically elevated above the cardboard plane.
        # Homography is only valid for points ON the table surface, so
        # projecting arm tip pixels gives nonsense coordinates.
        # FK is the ground truth for arm positions — vision is used ONLY
        # for landmark detection.  Once the ESP32 reports live angles via
        # serial, replace HOME_X/Y/Z here with fk.calculate_fk(angles).
        detections = self._tracker.process_frame(frame)  # still run for draw_pose()
        arm_states: list[ArmState] = [
            ArmState(arm_id=1, x=HOME_X, y=HOME_Y, z=HOME_Z, source="FK"),
            ArmState(arm_id=2, x=HOME_X, y=HOME_Y, z=HOME_Z, source="FK"),
        ]

        # ── Landmark detection ───────────────────────────────────────────
        lf: LandmarkFrame = self._lm_detector.process_frame(frame)
        lm_states: list[LandmarkState] = [
            LandmarkState(
                name=d.name,
                x=d.physical_x,
                y=d.physical_y,
                z=d.physical_z,
                confidence=d.confidence,
            )
            for d in lf.detections
        ]

        # ── Annotated frame for optional display ─────────────────────────
        annotated = None
        if frame is not None:
            try:
                annotated = self._tracker.draw_pose(frame, detections)
                annotated = self._lm_detector.draw_landmarks(annotated, lf)
            except Exception:  # noqa: BLE001
                annotated = frame

        # ── Publish ──────────────────────────────────────────────────────
        state = SceneState(
            arms=sorted(arm_states, key=lambda a: a.arm_id),
            landmarks=lm_states,
            tool_z_offset_cm=self._tool_offset,
        )
        self._shared.write(state, annotated)


# ---------------------------------------------------------------------------
# Tool Z-offset calibration
# ---------------------------------------------------------------------------

def run_tool_calibration(fk: ForwardKinematics) -> float:
    """
    Interactive calibration: user positions arm1 tip on the table surface,
    enters the servo angles, and the function returns the Z offset.
    """
    print(f"\n{_BOLD}Tool Z-Offset Calibration{_R}")
    print("Manually drive arm1 until the tip JUST touches the table surface.")
    print("Then enter the servo angles below.\n")

    try:
        base     = float(input("  Base angle (deg)     : "))
        shoulder = float(input("  Shoulder angle (deg) : "))
        elbow    = float(input("  Elbow angle (deg)    : "))
    except (ValueError, EOFError):
        print(f"{_YLW}Invalid input — using offset = 0.0{_R}")
        return 0.0

    result = fk.calculate_fk(base, shoulder, elbow)
    offset = TABLE_Z_CM - result.tip_z
    print(f"\n  FK tip Z   = {result.tip_z:.4f} cm")
    print(f"  Table Z    = {TABLE_Z_CM:.4f} cm")
    print(f"  {_GRN}Tool offset = {offset:.4f} cm{_R}")

    try:
        TOOL_OFFSET_FILE.write_text(json.dumps({"tool_z_offset_cm": offset}))
        print(f"  Saved to {TOOL_OFFSET_FILE}")
    except OSError as exc:
        print(f"  {_YLW}Could not save: {exc}{_R}")

    return offset


def load_tool_offset() -> float:
    """Load previously saved tool Z offset, or return 0.0."""
    try:
        data = json.loads(TOOL_OFFSET_FILE.read_text())
        off  = float(data.get("tool_z_offset_cm", 0.0))
        logger.info("Tool Z offset loaded: %.4f cm", off)
        return off
    except (OSError, json.JSONDecodeError, ValueError):
        logger.info("No saved tool offset — using 0.0 cm.")
        return 0.0


# ---------------------------------------------------------------------------
# Terminal output helpers
# ---------------------------------------------------------------------------

def _print_banner() -> None:
    print(
        f"\n{_BOLD}{'═'*72}\n"
        f"  RoboSurge Phase 4 — Landmark-Anchored Surgical Command System\n"
        f"{'═'*72}{_R}\n"
        f"  Commands: any natural language, 'status', 'abort', 'quit'\n"
        f"{'─'*72}"
    )


def _print_scene(state: SceneState) -> None:
    print(f"\n{_CYN}{_BOLD}═ SCENE STATE ═══════════════════════════════════{_R}")
    for arm in state.arms:
        src_col = _GRN if arm.source == "FUSED" else _YLW
        print(f"  Arm {arm.arm_id} [{src_col}{arm.source}{_R}]  "
              f"x={arm.x:+.2f}  y={arm.y:+.2f}  z={arm.z:.2f} cm")
    if state.landmarks:
        print(f"  {_DIM}Landmarks:{_R}")
        for lm in state.landmarks:
            conf_col = _GRN if lm.confidence > 0.7 else _YLW
            print(f"    {lm.name}  ({lm.x:+.2f}, {lm.y:+.2f}) cm  "
                  f"conf={conf_col}{lm.confidence:.2f}{_R}")
    else:
        print(f"  {_YLW}No landmarks detected{_R}")
    print(f"  tool_z_offset = {state.tool_z_offset_cm:.3f} cm")
    cal = _load_robot_calibration()
    print(
        f"  robot_calibration = scale({cal['scale_x']:.3f}, {cal['scale_y']:.3f}) "
        f"offset({cal['offset_x_cm']:+.2f}, {cal['offset_y_cm']:+.2f}) cm"
    )
    print()


def _print_plan(plan: ProcedurePlan) -> None:
    print(f"\n{_MAG}{_BOLD}═ PROCEDURE PLAN ════════════════════════════════{_R}")
    print(f"  Procedure : {_BOLD}{plan.procedure.upper()}{_R}")
    print(f"  Rationale : {plan.rationale}")
    print(f"  Duration  : ~{plan.estimated_duration_s:.1f}s")
    if plan.safety_notes:
        print(f"  {_YLW}Safety    : {plan.safety_notes}{_R}")
    for arm_plan in (plan.arm1, plan.arm2):
        print(f"\n  {_CYN}Arm {arm_plan.arm_id} ({arm_plan.role}){_R} "
              f"@ {arm_plan.feed_rate_mm_s} mm/s:")
        for wp in arm_plan.waypoints:
            print(f"    [{wp.label:<10}]  "
                  f"({wp.x:+7.2f}, {wp.y:+7.2f}, {wp.z:6.2f}) cm")
    print()


def _print_serial_preview(plan: ProcedurePlan) -> None:
    """Print the waypoint-level serial commands before confirmation."""
    print(f"\n{_CYN}{_BOLD}═ SERIAL PREVIEW ═════════════════════════════════{_R}")
    for arm_plan in (plan.arm1, plan.arm2):
        for wp in arm_plan.waypoints:
            print(f"  arm{arm_plan.arm_id} {wp.x:+.2f} {wp.y:+.2f} {wp.z:.2f}   # {wp.label}")
    print()


def _print_robot_calibration() -> None:
    cal = _load_robot_calibration()
    print(f"\n{_CYN}{_BOLD}Robot calibration{_R}")
    print(f"  scale_x     = {cal['scale_x']:.4f}")
    print(f"  scale_y     = {cal['scale_y']:.4f}")
    print(f"  offset_x_cm = {cal['offset_x_cm']:+.3f}")
    print(f"  offset_y_cm = {cal['offset_y_cm']:+.3f}")
    print(f"  file        = {ROBOT_CALIBRATION_FILE}\n")


def _handle_calibration_command(raw: str) -> bool:
    """
    Handle robot-frame calibration commands.

    Commands:
      cal                 show current robot calibration
      nudge <dx> <dy>     add cm offsets to every future target
      scale <sx> <sy>     set final XY scale multipliers
      cal reset           reset scale=1 and offsets=0
    """
    parts = raw.strip().split()
    if not parts:
        return False
    head = parts[0].lower()
    if head not in ("cal", "nudge", "scale"):
        return False

    cal = _load_robot_calibration()

    try:
        if head == "cal" and len(parts) == 1:
            _print_robot_calibration()
            return True
        if head == "cal" and len(parts) == 2 and parts[1].lower() == "reset":
            _save_robot_calibration({
                "scale_x": 1.0,
                "scale_y": 1.0,
                "offset_x_cm": 0.0,
                "offset_y_cm": 0.0,
            })
            print(f"{_GRN}Robot calibration reset.{_R}")
            return True
        if head == "nudge" and len(parts) == 3:
            dx = float(parts[1])
            dy = float(parts[2])
            cal["offset_x_cm"] += dx
            cal["offset_y_cm"] += dy
            _save_robot_calibration(cal)
            print(
                f"{_GRN}Nudged future targets by dx={dx:+.2f} cm, "
                f"dy={dy:+.2f} cm.{_R}"
            )
            _print_robot_calibration()
            return True
        if head == "scale" and len(parts) == 3:
            cal["scale_x"] = float(parts[1])
            cal["scale_y"] = float(parts[2])
            _save_robot_calibration(cal)
            print(f"{_GRN}Updated robot XY scale.{_R}")
            _print_robot_calibration()
            return True
    except ValueError:
        print(f"{_RED}Bad calibration command. Use numbers, e.g. nudge +1.0 -0.5{_R}")
        return True

    print(f"{_YLW}Calibration commands: cal | cal reset | nudge <dx_cm> <dy_cm> | scale <sx> <sy>{_R}")
    return True


def _print_result(results: dict) -> None:
    print(f"\n{_GRN}{_BOLD}═ EXECUTION COMPLETE ════════════════════════════{_R}")
    for arm_id, res in results.items():
        status = f"{_RED}ABORTED{_R}" if res.aborted else f"{_GRN}OK{_R}"
        print(f"  Arm {arm_id}: {status}  steps={res.steps_sent}  "
              f"duration={res.duration_s:.2f}s  "
              f"final=({res.final_position[0]:+.2f}, "
              f"{res.final_position[1]:+.2f}, "
              f"{res.final_position[2]:.2f}) cm")
    print()


def _extract_target_landmark(command: str) -> str:
    """Return the landmark name mentioned in the command; default to A."""
    cmd = command.lower()
    if "landmark b" in cmd or "landmark_b" in cmd or "target b" in cmd:
        return "landmark_B"
    if "landmark c" in cmd or "landmark_c" in cmd or "target c" in cmd:
        return "landmark_C"
    return "landmark_A"


def _extract_mm_value(command: str, default_mm: float = 3.0) -> float:
    """Extract the first '<number>mm' value from a natural-language command."""
    match = re.search(r"(\d+(?:\.\d+)?)\s*mm", command.lower())
    return float(match.group(1)) if match else default_mm


def _extract_stitch_count(command: str, default_n: int = 3) -> int:
    """
    Extract a stitch count from phrases like "3 stitches", "suture 5 times",
    or "put in 2 sutures".  Falls back to default_n (3) if nothing matches.
    """
    cmd = command.lower()
    match = re.search(r"(\d+)\s*(?:stitches|stitch|sutures|suture|times)", cmd)
    if match:
        n = int(match.group(1))
        return max(1, min(n, 8))   # clamp to a sane demo range
    return default_n


def _load_robot_calibration() -> dict[str, float]:
    """Load the final robot-frame scale/offset correction."""
    defaults = {
        "scale_x": 1.0,
        "scale_y": 1.0,
        "offset_x_cm": 0.0,
        "offset_y_cm": 0.0,
    }
    try:
        data = json.loads(ROBOT_CALIBRATION_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults
    for key, value in defaults.items():
        try:
            defaults[key] = float(data.get(key, value))
        except (TypeError, ValueError):
            defaults[key] = value
    return defaults


def _save_robot_calibration(cal: dict[str, float]) -> None:
    ROBOT_CALIBRATION_FILE.write_text(
        json.dumps(cal, indent=2),
        encoding="utf-8",
    )


def _apply_robot_calibration(x: float, y: float) -> tuple[float, float]:
    cal = _load_robot_calibration()
    return (
        x * cal["scale_x"] + cal["offset_x_cm"],
        y * cal["scale_y"] + cal["offset_y_cm"],
    )


def _repair_incision_plan(command: str, state: SceneState, plan: ProcedurePlan) -> ProcedurePlan:
    """
    Replace LLM incision geometry with deterministic robot waypoints.

    Groq still decides intent, but the robot-critical math is done here so
    "make a 3mm incision" cannot become a zero-length tap or use the wrong
    target. Landmarks are already in the ESP32 command frame.
    """
    if plan.procedure != "incision":
        return plan

    target_name = _extract_target_landmark(command)
    target = state.get_landmark(target_name)
    if target is None:
        return plan

    incision_len_cm = _extract_mm_value(command, default_mm=3.0) / 10.0
    cut_depth_cm = incision_len_cm
    start_x, start_y = _apply_robot_calibration(target.x, target.y)
    end_x = start_x + incision_len_cm
    end_y = start_y

    approach_z = TABLE_Z_CM + 0.2
    cut_z = TABLE_Z_CM - cut_depth_cm

    # Choose a lateral hold point that stays closer to the reachable workspace.
    hold_y_candidates = [start_y + 7.0, start_y - 7.0]
    hold_y = min(hold_y_candidates, key=lambda y: math.hypot(start_x, y))

    plan.arm1 = ArmPlan(
        arm_id=1,
        role="cutting",
        feed_rate_mm_s=min(max(plan.arm1.feed_rate_mm_s, 1.0), 3.0),
        waypoints=[
            Waypoint(x=start_x, y=start_y, z=SAFE_Z_CM, label="transit"),
            Waypoint(x=start_x, y=start_y, z=approach_z, label="approach"),
            Waypoint(x=start_x, y=start_y, z=cut_z, label="plunge"),
            Waypoint(x=end_x, y=end_y, z=cut_z, label="drag_end"),
            Waypoint(x=end_x, y=end_y, z=SAFE_Z_CM, label="retract"),
        ],
    )
    plan.arm2 = ArmPlan(
        arm_id=2,
        role="retracting",
        feed_rate_mm_s=min(max(plan.arm2.feed_rate_mm_s, 5.0), 10.0),
        waypoints=[
            Waypoint(x=start_x, y=hold_y, z=SAFE_Z_CM, label="hold"),
        ],
    )
    plan.safety_notes = (
        f"Deterministic incision repair: {incision_len_cm:.2f}cm drag at "
        f"{target_name}; target=({start_x:+.2f},{start_y:+.2f})."
    )
    return plan


def _repair_point_procedure_plan(
    command: str, state: SceneState, plan: ProcedurePlan,
    procedure: str, depth_cm: float, dwell_s: float = 0.0,
) -> ProcedurePlan:
    """
    Shared deterministic-geometry repair for single-point procedures
    (biopsy, cauterization). Plunges straight down at the target landmark
    and retracts to the SAME XY — no drag.
    """
    if plan.procedure != procedure:
        return plan

    target_name = _extract_target_landmark(command)
    target = state.get_landmark(target_name)
    if target is None:
        return plan

    x, y = _apply_robot_calibration(target.x, target.y)
    approach_z = TABLE_Z_CM + 0.2
    plunge_z = TABLE_Z_CM - depth_cm

    plan.arm1 = ArmPlan(
        arm_id=1,
        role="cutting",
        feed_rate_mm_s=min(max(plan.arm1.feed_rate_mm_s, 1.0), 3.0),
        waypoints=[
            Waypoint(x=x, y=y, z=SAFE_Z_CM, label="transit"),
            Waypoint(x=x, y=y, z=approach_z, label="approach"),
            Waypoint(x=x, y=y, z=plunge_z, label="plunge", dwell_s=dwell_s),
            Waypoint(x=x, y=y, z=SAFE_Z_CM, label="retract"),
        ],
    )

    hold_y_candidates = [y + 7.0, y - 7.0]
    hold_y = min(hold_y_candidates, key=lambda hy: math.hypot(x, hy))
    plan.arm2 = ArmPlan(
        arm_id=2,
        role="retracting",
        feed_rate_mm_s=min(max(plan.arm2.feed_rate_mm_s, 5.0), 10.0),
        waypoints=[
            Waypoint(x=x, y=hold_y, z=SAFE_Z_CM, label="hold"),
        ],
    )
    plan.safety_notes = (
        f"Deterministic {procedure} repair: target={target_name} "
        f"at ({x:+.2f},{y:+.2f}), depth={depth_cm:.2f}cm"
        + (f", dwell={dwell_s:.1f}s." if dwell_s else ".")
    )
    return plan


def _repair_biopsy_plan(command: str, state: SceneState, plan: ProcedurePlan) -> ProcedurePlan:
    """Biopsy: plunge a little deeper than a standard incision to sample tissue."""
    depth_cm = _extract_mm_value(command, default_mm=5.0) / 10.0
    return _repair_point_procedure_plan(command, state, plan, "biopsy", depth_cm=depth_cm)


def _repair_cauterization_plan(command: str, state: SceneState, plan: ProcedurePlan) -> ProcedurePlan:
    """Cauterization: shallow contact, held for CAUTERIZATION_DWELL_S."""
    from surgical_agent import CAUTERIZATION_DWELL_S
    return _repair_point_procedure_plan(
        command, state, plan, "cauterization",
        depth_cm=0.1, dwell_s=CAUTERIZATION_DWELL_S,
    )


def _repair_debridement_plan(command: str, state: SceneState, plan: ProcedurePlan) -> ProcedurePlan:
    """
    Debridement: deterministic zigzag sweep over a small region centered on
    the target landmark, at a shallow Z (gentle contact, not a deep cut).
    """
    if plan.procedure != "debridement":
        return plan

    target_name = _extract_target_landmark(command)
    target = state.get_landmark(target_name)
    if target is None:
        return plan

    cx, cy = _apply_robot_calibration(target.x, target.y)
    approach_z = TABLE_Z_CM + 0.2
    sweep_z = TABLE_Z_CM - 0.05   # very shallow — debridement grazes, doesn't cut

    half_w = 1.0   # cm, region is ~2cm x 2cm centered on the landmark
    rows_y = [cy - half_w, cy - half_w / 2, cy, cy + half_w / 2, cy + half_w]

    sweep_wps: list[Waypoint] = [Waypoint(x=cx - half_w, y=rows_y[0], z=SAFE_Z_CM, label="transit"),
                                  Waypoint(x=cx - half_w, y=rows_y[0], z=approach_z, label="approach")]
    for i, ry in enumerate(rows_y):
        left_x, right_x = cx - half_w, cx + half_w
        if i % 2 == 0:
            sweep_wps.append(Waypoint(x=left_x, y=ry, z=sweep_z, label=f"sweep_{2*i}"))
            sweep_wps.append(Waypoint(x=right_x, y=ry, z=sweep_z, label=f"sweep_{2*i+1}"))
        else:
            sweep_wps.append(Waypoint(x=right_x, y=ry, z=sweep_z, label=f"sweep_{2*i}"))
            sweep_wps.append(Waypoint(x=left_x, y=ry, z=sweep_z, label=f"sweep_{2*i+1}"))
    last = sweep_wps[-1]
    sweep_wps.append(Waypoint(x=last.x, y=last.y, z=SAFE_Z_CM, label="retract"))

    plan.arm1 = ArmPlan(
        arm_id=1,
        role="cutting",
        feed_rate_mm_s=min(max(plan.arm1.feed_rate_mm_s, 2.0), 6.0),
        waypoints=sweep_wps,
    )
    hold_y_candidates = [cy + half_w + 7.0, cy - half_w - 7.0]
    hold_y = min(hold_y_candidates, key=lambda hy: math.hypot(cx, hy))
    plan.arm2 = ArmPlan(
        arm_id=2,
        role="retracting",
        feed_rate_mm_s=min(max(plan.arm2.feed_rate_mm_s, 5.0), 10.0),
        waypoints=[Waypoint(x=cx, y=hold_y, z=SAFE_Z_CM, label="hold")],
    )
    plan.safety_notes = (
        f"Deterministic debridement repair: {len(rows_y)}-row zigzag sweep "
        f"centered on {target_name} ({cx:+.2f},{cy:+.2f}), shallow z={sweep_z:.2f}."
    )
    return plan


def _repair_suturing_plan(command: str, state: SceneState, plan: ProcedurePlan) -> ProcedurePlan:
    """
    Suturing (DEMO ONLY): deterministic entry → loop-arc → exit → cinch
    pattern, repeated for N stitches in a row along the incision line.

    This is a simplified visual stand-in for real needle-and-thread
    suturing — the tool tip itself traces the stitch motion (no needle
    driver, no actual thread). It exists to demo the motion-planning
    pipeline end-to-end, not to perform a clinically real closure.

    Geometry, all centered on the target landmark, running along +X:
      stitch_spacing_cm = 0.6   (gap between successive stitches)
      bite_width_cm     = 0.4   (entry → exit distance for one stitch)
      stitch_depth_cm   = 0.15  (how far below the table the tip dips)
      loop_height_cm    = 0.8   (how high the arc rises above the table)
    """
    from surgical_agent import SUTURE_CINCH_DWELL_S, DEFAULT_SUTURE_STITCHES

    if plan.procedure != "suturing":
        return plan

    target_name = _extract_target_landmark(command)
    target = state.get_landmark(target_name)
    if target is None:
        return plan

    n_stitches = _extract_stitch_count(command, default_n=DEFAULT_SUTURE_STITCHES)

    stitch_spacing_cm = 0.6
    bite_width_cm     = 0.4
    stitch_depth_cm   = 0.15
    loop_height_cm    = 0.8

    cx, cy = _apply_robot_calibration(target.x, target.y)
    approach_z = TABLE_Z_CM + 0.2
    stitch_z   = TABLE_Z_CM - stitch_depth_cm
    loop_z     = TABLE_Z_CM + loop_height_cm

    # arm2 "tug" choreography constants — purely cosmetic, no cutting/contact.
    tug_hold_z      = TABLE_Z_CM + 0.5    # settles near the table during the stitch
    tug_pull_z      = TABLE_Z_CM + 1.8    # lifts clear during the cinch
    tug_pull_offset = 0.8                 # cm sideways drift on the pull, away from the line
    tug_pull_dwell  = SUTURE_CINCH_DWELL_S  # pause in sync with arm1's cinch beat

    hold_y_candidates = [cy + 7.0, cy - 7.0]
    hold_y = min(hold_y_candidates, key=lambda hy: math.hypot(cx, hy))
    away_sign = 1.0 if hold_y > cy else -1.0   # drift further away from the line, not toward it

    wps:      list[Waypoint] = []
    tug_wps:  list[Waypoint] = []
    for i in range(1, n_stitches + 1):
        entry_x = cx + (i - 1) * stitch_spacing_cm
        exit_x  = entry_x + bite_width_cm
        mid_x   = (entry_x + exit_x) / 2.0

        wps.append(Waypoint(x=entry_x, y=cy, z=SAFE_Z_CM,  label=f"stitch{i}_transit"))
        wps.append(Waypoint(x=entry_x, y=cy, z=approach_z, label=f"stitch{i}_approach"))
        wps.append(Waypoint(x=entry_x, y=cy, z=stitch_z,   label=f"stitch{i}_entry"))
        wps.append(Waypoint(x=mid_x,   y=cy, z=loop_z,     label=f"stitch{i}_loop"))
        wps.append(Waypoint(x=exit_x,  y=cy, z=stitch_z,   label=f"stitch{i}_exit"))
        wps.append(Waypoint(
            x=exit_x, y=cy, z=TABLE_Z_CM + 0.3, label=f"stitch{i}_cinch",
            dwell_s=SUTURE_CINCH_DWELL_S,
        ))

        # arm2: glide in, settle near the table while arm1 sews this stitch,
        # then lift + drift sideways ("tug") timed with arm1's cinch.
        tug_wps.append(Waypoint(x=mid_x, y=hold_y, z=SAFE_Z_CM, label=f"tug{i}_approach"))
        tug_wps.append(Waypoint(x=mid_x, y=hold_y, z=tug_hold_z, label=f"tug{i}_hold"))
        tug_wps.append(Waypoint(
            x=mid_x, y=hold_y + away_sign * tug_pull_offset, z=tug_pull_z,
            label=f"tug{i}_pull", dwell_s=tug_pull_dwell,
        ))

    last = wps[-1]
    wps.append(Waypoint(x=last.x, y=last.y, z=SAFE_Z_CM, label="retract"))

    last_tug = tug_wps[-1]
    tug_wps.append(Waypoint(x=last_tug.x, y=hold_y, z=SAFE_Z_CM, label="release"))

    plan.arm1 = ArmPlan(
        arm_id=1,
        role="cutting",
        feed_rate_mm_s=min(max(plan.arm1.feed_rate_mm_s, 1.0), 2.5),
        waypoints=wps,
    )
    plan.arm2 = ArmPlan(
        arm_id=2,
        role="retracting",
        feed_rate_mm_s=min(max(plan.arm2.feed_rate_mm_s, 3.0), 6.0),
        waypoints=tug_wps,
    )
    plan.safety_notes = (
        f"Deterministic suturing DEMO repair: {n_stitches} stitch(es) starting at "
        f"{target_name} ({cx:+.2f},{cy:+.2f}); arm2 runs a cosmetic 'tug' "
        "choreography in sync with arm1's cinch beat. Visual stand-in motion, "
        "not a real needle/thread closure."
    )
    return plan


# ---------------------------------------------------------------------------
# Main CLI loop
# ---------------------------------------------------------------------------

class RoboSurgeCLI:
    def __init__(
        self,
        serial_port:   str,
        camera_index:  int | str,
        weights:       str,
        tool_offset:   float,
        dry_run:       bool = False,
    ) -> None:
        self._dry_run     = dry_run
        self._tool_offset = tool_offset
        self._shared      = SharedState()
        self._executor:   Optional[MotionExecutor] = None
        self._serial:     Optional[serial.Serial]  = None
        self._vision_thread: Optional[VisionThread] = None

        # Build subsystems
        self._mapper      = LocalAffineMapper(CALIBRATION_PHYSICAL_PTS, CALIBRATION_PIXEL_PTS)
        self._tracker     = PoseTracker(weights_path=weights, camera_index=camera_index)
        self._lm_detector = LandmarkDetector(mapper=self._mapper)
        self._agent       = SurgicalAgent()
        self._fk          = ForwardKinematics()

        # Serial
        if not dry_run:
            self._serial = self._open_serial(serial_port)

        # Executor
        write_fn = (self._serial_write if self._serial else None)
        self._executor = MotionExecutor(serial_write_fn=write_fn)

        # SIGINT → abort
        signal.signal(signal.SIGINT, self._handle_sigint)

    # ------------------------------------------------------------------
    # Startup / teardown
    # ------------------------------------------------------------------

    def _open_serial(self, port: str) -> Optional[serial.Serial]:
        try:
            s = serial.Serial(port=port, baudrate=SERIAL_BAUD, timeout=SERIAL_TIMEOUT,
                              write_timeout=SERIAL_TIMEOUT)
            logger.info("Serial %s opened.", port)
            return s
        except serial.SerialException as exc:
            logger.warning("Serial unavailable (%s) — dry-run mode.", exc)
            return None

    def _serial_write(self, cmd: str) -> bool:
        if self._serial is None or not self._serial.is_open:
            return False
        try:
            self._serial.write(cmd.encode("ascii"))
            self._serial.flush()
            return True
        except serial.SerialException:
            return False

    def _handle_sigint(self, *_) -> None:
        print(f"\n{_RED}SIGINT received — aborting motion and shutting down.{_R}")
        if self._executor:
            self._executor.abort()
        self.shutdown()
        sys.exit(0)

    def shutdown(self) -> None:
        if self._vision_thread:
            self._vision_thread.stop()
        self._tracker.release_camera()
        if self._serial and self._serial.is_open:
            self._serial.close()
        cv2.destroyAllWindows()
        logger.info("RoboSurge CLI shut down.")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        _print_banner()

        # Start camera and vision thread
        self._tracker.open_camera()
        self._vision_thread = VisionThread(
            tracker=self._tracker,
            mapper=self._mapper,
            lm_detector=self._lm_detector,
            shared_state=self._shared,
            tool_offset=self._tool_offset,
        )
        self._vision_thread.start()

        print("Vision thread running.  Waiting for first scene state…")
        for _ in range(30):   # wait up to 3s
            if self._shared.read() is not None:
                break
            time.sleep(0.1)

        print(f"{_GRN}Ready.{_R}\n")

        try:
            while True:
                try:
                    raw = input(f"{_BOLD}RoboSurge >{_R} ").strip()
                except EOFError:
                    break

                if not raw:
                    continue

                cmd_lower = raw.lower()

                if cmd_lower in ("quit", "exit", "q"):
                    break

                if cmd_lower == "status":
                    state = self._shared.read()
                    if state:
                        _print_scene(state)
                    else:
                        print(f"{_YLW}No scene state yet.{_R}")
                    continue

                if cmd_lower == "abort":
                    if self._executor:
                        self._executor.abort()
                    continue

                # ── Full pipeline ────────────────────────────────────────
                self._handle_command(raw)

        finally:
            self.shutdown()

    def _handle_command(self, command: str) -> None:
        # 1. Get scene state
        state = self._shared.read()
        if state is None:
            print(f"{_RED}No scene state available.  Is the camera running?{_R}")
            return

        warnings = state.validate()
        if warnings:
            print(f"{_YLW}Scene warnings:{_R}")
            for w in warnings:
                print(f"  {_YLW}⚠ {w}{_R}")

        _print_scene(state)

        # 2. LLM planning
        print(f"{_DIM}Planning with Groq…{_R}")
        try:
            plan = self._agent.plan(command, state)
        except SurgicalAgentError as exc:
            print(f"{_RED}Agent failed: {exc}{_R}")
            return

        plan = _repair_incision_plan(command, state, plan)
        plan = _repair_biopsy_plan(command, state, plan)
        plan = _repair_cauterization_plan(command, state, plan)
        plan = _repair_debridement_plan(command, state, plan)
        plan = _repair_suturing_plan(command, state, plan)

        _print_plan(plan)

        # 3. Validation
        validator = ProcedureValidator(landmarks=state.landmarks)
        vresult   = validator.validate(plan)

        print(vresult.summary())

        if not vresult.ok:
            print(f"{_RED}Plan rejected — fix errors above and retry.{_R}")
            return

        _print_serial_preview(plan)

        # 4. Confirm
        try:
            confirm = input(f"{_YLW}Execute? [y/N] >{_R} ").strip().lower()
        except EOFError:
            confirm = "n"

        if confirm != "y":
            print("Cancelled.")
            return

        # 5. Execute
        print(f"\n{_GRN}Executing…{_R}")
        results = self._executor.execute(plan)
        _print_result(results)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _parse_cli() -> dict:
    args = {
        "port":       SERIAL_PORT,
        "cam":        1,
        "weights":    "robosurge_pose_best.pt",
        "calibrate":  False,
        "dry_run":    False,
    }
    i = 1
    while i < len(sys.argv):
        a = sys.argv[i]
        n = sys.argv[i+1] if i+1 < len(sys.argv) else ""
        if   a == "--port"      and n: args["port"]    = n;          i += 2
        elif a == "--cam"       and n: args["cam"]      = int(n) if n.isdigit() else n; i += 2
        elif a == "--weights"   and n: args["weights"]  = n;          i += 2
        elif a == "--calibrate":       args["calibrate"] = True;      i += 1
        elif a == "--dry-run":         args["dry_run"]   = True;      i += 1
        else: i += 1
    return args


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    opts = _parse_cli()

    # Custom weights — search CWD first, then models/
    if not Path(opts["weights"]).exists():
        candidate = MODELS_DIR / Path(opts["weights"]).name
        if candidate.exists():
            opts["weights"] = str(candidate)
            logger.info("Found weights at %s", candidate)
        else:
            logger.error(
                "Weights '%s' not found in CWD or %s.",
                opts["weights"], MODELS_DIR,
            )
            opts["weights"] = "yolov8n-pose.pt"
            logger.warning("Falling back to yolov8n-pose.pt — arm positions will be WRONG.")

    # Tool offset
    fk = ForwardKinematics()
    if opts["calibrate"]:
        tool_offset = run_tool_calibration(fk)
    else:
        tool_offset = load_tool_offset()

    print(f"Tool Z offset: {tool_offset:.4f} cm")

    cli = RoboSurgeCLI(
        serial_port=opts["port"],
        camera_index=opts["cam"],
        weights=opts["weights"],
        tool_offset=tool_offset,
        dry_run=opts["dry_run"],
    )
    cli.run()


if __name__ == "__main__":
    main()