# RoboSurge — CODEBASE.md

Technical documentation of the repository at commit `d98ee39` (branch `main`,
version **0.4.0** per `robosurge/__init__.py`). This document is written for a
new developer or another AI to gain a complete, source-backed understanding of
the project. Everything below is derived from the actual repository contents.

---

## 1. Project overview and purpose

**RoboSurge** is a research/demo platform for a **dual-arm robotic surgical
system** running on a benchtop phantom (NOT a medical device). It lets a user
type a natural-language command such as *"make a 3mm incision at landmark A"*
and the system:

1. **Perceives** the scene with a webcam (`YOLOv8-pose` arm tracking + HSV
   fiducial-landmark detection).
2. **Plans** the procedure with a large language model (Groq
   `llama-3.3-70b-versatile`).
3. **Validates** the plan against deterministic, pure-math safety rules.
4. **Executes** it on real hardware — two custom 3-DOF servo arms — via USB
   serial to an ESP32 that runs the inverse kinematics (IK) on-chip.

The guiding design principle is: **the LLM decides *what* to do, but every
robot-critical number (cut depths, waypoints, stitch patterns) is
deterministically rebuilt and re-checked in Python before a single serial byte
is sent.**

The repository evolved through four phases, all of which are still present:
- **Phase 1** — NL → LLM → waypoint → serial execution (archived).
- **Phase 2** — vision/kinematics (YOLOv8-pose tracking, FK engine, ArUco
  stereo tracking, dataset generation, custom pose-model training data).
- **Phase 3** — vision→hardware fusion bridge (homography / local-affine
  pixel→cm mapping).
- **Phase 4** — the current integrated system: landmark-anchored surgical
  command CLI (the active code path).

---

## 2. Problem being solved

The motivating problem this research platform explores: **can a large language
model act as a safe motion planner for a physical robot doing a surgical-style
procedure?**

Concretely, the system addresses several sub-problems:
- Robustly knowing *where things are* in the scene (arm tips, target
  landmarks) from a single fixed webcam — using both a learned pose model and
  classical computer vision.
- Translating free-form human instructions into a structured, executable
  procedure without the LLM inventing unsafe robot commands.
- A **safety-by-construction** approach: pure-geometry validation in Python
  (workspace bounds, Z floor, inter-arm clearance, teleport detection,
  landmark alignment) plus deterministic post-LLM *plan repair* so the model
  cannot make the robot do something dangerous.
- Coordinated, real-time motion of two arms over serial with an interruptible
  abort path.

It is explicitly **not** a clinically deployable device — it is a demo proving
the perception → LLM-planning → validation → execution pipeline on a phantom
(gel/silicone block) field.

---

## 3. Main features

- **Natural-language procedural commands**: `incision`, `biopsy`,
  `cauterization` (with contact dwell), `debridement` (zigzag sweep),
  `suturing` (visual demo stitch pattern), `retraction`, `hold`, `home`,
  `abort`.
- **LLM plan sandboxing**: the Groq model returns intent + rough geometry only;
  `robosurge/cli.py` rebuilds exact cut geometry deterministically from the
  detected landmarks.
- **Multi-layer safety**:
  1. LLM prompt-level hard rules + refusal to output unsafe plans.
  2. `ProcedureValidator` pure-math checks (workspace reach, Z floor, per-step
     max displacement, interpolated inter-arm clearance, feed-rate bounds,
     incisional/landmark alignment, procedure/role consistency).
  3. Human confirmation before any execution (serial preview + `[y/N]`).
  4. `abort` command / Ctrl+C → both arms retract to safe height.
- **Perception fusion**: YOLOv8-pose multi-arm skeleton detection, HSV-colored
  fiducial landmark detection (A = yellow, B = cyan, C = purple), and
  piecewise-local affine pixel→cm calibration.
- **Concurrent dual-arm execution**: two threads stream interpolated waypoints
  at 10 Hz; lead-follow choreography (arm2 retractor positions first) for
  cutting-type procedures, simultaneous motion otherwise.
- **Dry-run mode**: run the entire pipeline with serial commands printed but
  not sent.
- **Calibration tooling**: interactive tool Z-offset calibration, an automated
  FK-driven pixel↔cm local-affine calibrator, and a live HSV tuner.
- **Module self-tests**: each core module runs a standalone smoke test via
  `python -m robosurge.<module>` with no hardware.

---

## 4. Complete project structure

```
RoboSurge/
├── .gitignore                       # ignores .env, __pycache__, logs/, *.pyc,
│                                   #   live_calib_check.png, yolov8n-pose.pt, runs/, .vscode/
├── main.py                          # entry point → robosurge.cli.main()
├── README.md                        # user-facing documentation
├── requirements.txt                 # Python dependencies
├── sync.ffs_db                      # FreeFileSync sync database (binary, not source)
├── CODEBASE.md                      # this document
├── robosurge/                       # core package (Phase 4)
│   ├── __init__.py                  # package version (0.4.0)
│   ├── cli.py                       # top-level CLI: wiring, command loop, plan repair
│   ├── scene_state.py               # world model / SceneState + workspace constants
│   ├── surgical_agent.py            # Groq LLM planner (NL → ProcedurePlan JSON)
│   ├── procedure_validator.py       # pure-math safety validation layer
│   ├── motion_executor.py           # waypoint interpolation + serial streaming
│   ├── kinematics_engine.py         # forward kinematics for the 3-DOF arm
│   ├── vision_pipeline.py           # YOLOv8-pose arm tracking
│   ├── landmark_detector.py         # HSV fiducial detection
│   └── sensor_fusion.py             # pixel→cm mappers (LocalAffineMapper, HomographyMapper, FusionBridge)
├── config/
│   ├── tool_offset.json             # tool Z-offset calibration result
│   └── robot_calibration.json       # final XY scale/offset nudges
├── models/
│   └── robosurge_pose_best.pt       # custom YOLOv8-pose weights (4 keypoints), ~6.4 MB
├── data/
│   └── calibration/
│       ├── calibration_points.csv   # raw (target_x, target_y, pixel_u, pixel_v) data
│       ├── calibration_fit.json     # saved fit + leave-one-out error metrics
│       ├── calibration_paste.py     # generated snippet for pasting into sensor_fusion.py
│       └── calibration_frame.png    # sample calibration frame
├── logs/                            # created at runtime; last_execution_commands.log (gitignored)
├── tools/                           # standalone utility scripts
│   ├── calibrate_via_fk.py          # auto pixel↔cm calibration by driving the arm
│   ├── cam_test.py                  # grab a single frame
│   └── test.py                      # HSV threshold scratch test
├── training/                        # YOLO dataset generation (Phase 2)
│   ├── generate_training_movements.py  # dual-arm sweep trajectory generator
│   ├── extract_frames.py               # video → frames extraction
│   ├── calibration_video.mp4           # ~16 MB captured sweep video
│   └── dataset_images/                 # frame_0000.png … frame_0123.png (124 frames)
└── archive/                         # legacy Phase 1–2 scripts (not imported)
    ├── procedure_agent.py           # Phase 1 NL→LLM→serial agent
    ├── stereo_tracker.py            # Phase 2 dual-camera ArUco tracker
    ├── aruco_test.py                # ArUco debug viewer
    └── test.py                      # Phase 2 serial "dance" test
```

---

## 5. Purpose of important files and folders

### Root files
- **`main.py`** — 12-line entry point. All it does is `from robosurge.cli import
  main; main()`. Supports the same flags as `python -m robosurge.cli`.
- **`requirements.txt`** — pinned-minimum Python dependencies (see §7).
- **`.gitignore`** — excludes `.env`, `__pycache__/`, `*.pyc`, `logs/`,
  `data/calibration/live_calib_check.png`, `yolov8n-pose.pt`, `runs/`, `.vscode/`.
- **`sync.ffs_db`** — binary FreeFileSync database; indicates the repo is
  synced to the robot PC with FreeFileSync. Not part of the Python code.

### `robosurge/` package (the core — see §9 for detail)
| File | Purpose |
|---|---|
| `cli.py` | Top-level controller: wires all subsystems, runs the interactive command loop, deterministic plan-repair functions, tool calibration, live XY calibration commands, SIGINT handling. |
| `scene_state.py` | Single source of truth for physical workspace constants (`TABLE_Z_CM`, `MIN_REACH`, `MAX_REACH`, `SAFE_Z_CM`) and the `SceneState`/`ArmState`/`LandmarkState` dataclasses serialized into the LLM prompt. |
| `surgical_agent.py` | Groq LLM client. Converts NL command + `SceneState` JSON into a typed `ProcedurePlan` with retry/self-correction. |
| `procedure_validator.py` | Deterministic safety layer. Runs 8+ geometry checks on a plan; rejects unsafe plans before execution. |
| `motion_executor.py` | Turns a validated plan into a timed 10 Hz stream of `arm<N> X Y Z\n` serial commands, executing both arms concurrently in threads with abort support. |
| `kinematics_engine.py` | Homogeneous-transform forward kinematics for the 3-DOF arm (base pan, shoulder pitch, elbow pitch) plus an independent scalar cross-check. |
| `vision_pipeline.py` | `PoseTracker` wraps the custom YOLOv8-pose model; detects 4 arm keypoints (base, elbow, wrist, tip) for multiple arms. |
| `landmark_detector.py` | `LandmarkDetector` finds colored fiducial dots via HSV thresholding + morphology + contour circularity, projects to cm, and exposes an interactive HSV tuner. |
| `sensor_fusion.py` | `LocalAffineMapper` (piecewise-local pixel→cm), `HomographyMapper` (global), `FusionBridge` (Phase-3 standalone 10 Hz vision→serial loop), arm assignment helpers, serial command formatting. |

### Supporting folders
- **`config/`** — persisted calibration artifacts loaded/written at runtime.
- **`models/`** — the custom trained YOLOv8-pose weights. If missing and not in
  the CWD, the CLI falls back to stock `yolov8n-pose.pt` with wrong keypoint labels.
- **`data/calibration/`** — the pixel↔cm calibration dataset and fit results,
  produced by `tools/calibrate_via_fk.py`.
- **`tools/`** — standalone utilities that exercise pieces of the pipeline.
- **`training/`** — Phase-2 data-collection artifacts (sweep video + frames +
  generators) used to train `robosurge_pose_best.pt`.
- **`archive/`** — retired Phase 1/2 scripts; kept for reference, not imported
  by any current module.

---

## 6. Technology stack

- **Language**: Python 3.11+ (type hints use modern syntax such as
  `list[X]`, `X | None`, `tuple[int, int] | None`).
- **Platform**: Windows (PowerShell-driven development; `COM6` serial port,
  `\033[` ANSI terminal rendering in code).
- **AI / ML**: YOLOv8-pose via Ultralytics for arm skeletons; Groq hosted
  LLM (`llama-3.3-70b-versatile`) for planning.
- **Vision**: OpenCV (`cv2`) — capture, HSV, morphology, contours, homography.
- **Math**: NumPy (homogeneous transforms, local-affine least squares,
  `cv2.findHomography` RANSAC).
- **Hardware comms**: `pyserial` at 115200 baud.
- **Config / env**: `python-dotenv` (`GROQ_API_KEY` from `.env`).
- **Concurrency**: `threading` (vision thread, arm-execution threads,
  shrink-wrapped `threading.Event`/`Lock`).

---

## 7. Dependencies and libraries

From `requirements.txt`:

| Package | Minimum version | Used for |
|---|---|---|
| `ultralytics` | >= 8.0 | loading/running `YOLO` pose model (`PoseTracker`) |
| `opencv-python` | >= 4.8 | camera capture, HSV, morphology, contours, homography, image display |
| `numpy` | >= 1.24 | matrices, transforms, least squares |
| `pyserial` | >= 3.5 | USB serial to the ESP32 |
| `groq` | >= 0.9 | Groq LLM chat completions |
| `python-dotenv` | >= 1.0 | load `.env` (GROQ_API_KEY) |

Note: `landmark_detector.py` also imports `dotenv` directly. `surgical_agent`
imports the `groq` package unconditionally at module load.

---

## 8. System architecture

The system is split into three logical layers, stitched together by
`robosurge/cli.py`:

```
                            ┌────────────  camera  ────────────┐
                            │                                  │
             PoseTracker (YOLOv8-pose)       LandmarkDetector (HSV)
               arm skeleton pixels             colored fiducial dots
                            │                        │
                            │                        └──► pixel → cm
                            │                             (LocalAffineMapper)
                            ▼                                  ▼
                    ┌─────────────────  SceneState  ─────────────────┐
                    │             (world model, per-frame)          │
                    └───────────────────────────────────────────────┘
   natural-language command
              │
              ▼
      SurgicalAgent ── Groq llama-3.3-70b-versatile ──► ProcedurePlan JSON (intent only)
              │
              ▼
   deterministic plan repair (cli.py) — exact cut geometry rebuilt from landmarks,
   robot_calibration applied, procedure-specific waypoint templates
              │
              ▼
      ProcedureValidator ── pure-math safety checks (bounds, clearance, ...)
              │
              ▼
     MotionExecutor ── waypoint interpolation @ 10 Hz ──► ESP32 (on-chip IK)
                                                             │
                                                        2 × 3-DOF servo arms
```

**Key architectural decision**: the LLM is kept *out* of the robot-critical
math. After the model returns a `ProcedurePlan`, `cli.py` calls a "repair"
function for the detected procedure that rewrites all waypoints using the
*database-of-record* landmark coordinates, the calibrated tool Z offset, and
the robot XY calibration — then `ProcedureValidator` re-checks everything
geometrically. Any failed check blocks execution.

---

## 9. Major modules/components

### 9.1 `robosurge/cli.py` — top-level CLI / orchestrator (1031 lines)
The largest and most central module. Contents:

- **`SharedState`** — thread-safe slot holding the latest `SceneState` (and an
  optional annotated frame) produced by the vision thread and consumed by the
  command loop.
- **`VisionThread(threading.Thread)`** — 10 Hz loop calling `_tick()`: grabs a
  frame, runs pose tracking (still run for drawing), **and hardcodes both arm
  tip positions to `HOME_X/HOME_Y/HOME_Z`** (FK would be the ground truth but
  the ESP32 does not yet report live joint angles back), runs landmark
  detection, then publishes a `SceneState`. Note: it also writes
  `live_calib_check.png` to the CWD every tick (gitignored as
  `live_calib_check.png`).
- **`run_tool_calibration(fk)` / `load_tool_offset()`** — interactive Z-offset
  calibration: user drives arm1 tip to the table, enters base/shoulder/elbow
  angles, `offset = TABLE_Z_CM - FK_tip_z`, saved to `config/tool_offset.json`.
- **Plan repair functions** (deterministic geometry rebuild):
  - `_repair_incision_plan` — transit → approach → plunge → drag_end → retract
    at exact landmark, length from `_extract_mm_value`.
  - `_repair_biopsy_plan` / `_repair_cauterization_plan` via
    `_repair_point_procedure_plan` — plunge straight down and retract same XY
    (biopsy default depth 5 mm; cauterization depth 0.1 cm with
    `CAUTERIZATION_DWELL_S` dwell).
  - `_repair_debridement_plan` — 5-row zigzag sweep over a 2 cm × 2 cm region.
  - `_repair_suturing_plan` — per-stitch *entry → loop-arc → exit → cinch*
    pattern (spacing 0.6 cm, bite 0.4 cm) with a cosmetic arm2 "tug"
    choreography.
  - All of them apply `_apply_robot_calibration` (scale + offset) and choose a
    lateral hold point for arm2 (`hold_y` ±7 cm, nearest reachable).
- **Extractors**: `_extract_target_landmark` (landmark B/C by name, else A),
  `_extract_mm_value` (regex `\d+(\.\d+)?\s*mm`), `_extract_stitch_count`
  (regex for `N stitches/sutures/times`, clamped 1–8).
- **Robot-calibration commands**: `_load_robot_calibration`,
  `_save_robot_calibration`, `_apply_robot_calibration`, and
  `_handle_calibration_command` (parses `cal` / `cal reset` / `nudge <dx> <dy>`
  / `scale <sx> <sy>`). **Note:** `_handle_calibration_command` is *defined but
  never invoked* anywhere in the command loop (see §17 limitations).
- **`RoboSurgeCLI`** — builds all subsystems, opens serial (falls back to
  dry-run), installs a SIGINT handler that calls `executor.abort()` +
  `shutdown()`, and runs the interactive `RoboSurge >` prompt. Command
  dispatch: `quit/exit/q`, `status`, `abort`, otherwise `_handle_command`.
- **`_handle_command`** — the end-to-end pipeline per natural-language command:
  read scene state → validate warnings → LLM plan → apply all five repair
  functions → print plan + validation summary → reject if `not vresult.ok` →
  print serial preview → require `[y]` confirmation → `executor.execute(plan)`.
- **`_parse_cli()`** / **`main()`** — manual flag parser (`--port`, `--cam`,
  `--weights`, `--calibrate`, `--dry-run`), weights search (CWD then
  `models/`), logging setup.

### 9.2 `robosurge/scene_state.py` — world model (265 lines)
- Constants (the **single source of truth**, imported by every other module):
  - `TABLE_Z_CM = -7.66` — ESP32 command-frame table Z, physically calibrated
    2026-06-19. The ESP32's Z=0 sits ~7.66 cm *above* the table (near shoulder
    height), so table contact is a *negative* Z in the command frame.
  - `MIN_REACH = 2.5`, `MAX_REACH = 21.5` (cm).
  - `SAFE_Z_CM = TABLE_Z_CM + 2.5 = -5.16` — hover/transit height.
- Dataclasses: `ArmState` (arm_id 1 = left/cutting, 2 = right/retracting; x/y/z;
  source FUSED/FK/VISION), `LandmarkState` (name/x/y/z/confidence),
  `SceneState` (arms, landmarks, timestamp, `tool_z_offset_cm`, notes).
- `SceneState.to_json()` — rounded to 3 d.p. for LLM context efficiency;
  `to_prompt_block()` — human-readable + JSON block fed into the user message;
  `validate()` — returns warnings for blind-spot/excess-reach impediments,
  below-table Z, low-confidence landmarks.
- Zero external imports beyond stdlib + numpy (deliberately unit-testable).

### 9.3 `robosurge/surgical_agent.py` — Groq LLM planner (527 lines)
- Constants: `GROQ_MODEL = "llama-3.3-70b-versatile"`, `MAX_TOKENS = 2048`,
  `TEMPERATURE = 0.0`, `MAX_RETRIES = 3`, feed-rate limits 0.5–15 mm/s,
  per-procedure default feed rates, `CAUTERIZATION_DWELL_S = 3.0`,
  `SUTURE_CINCH_DWELL_S = 0.3`, `DEFAULT_SUTURE_STITCHES = 3`.
- `_SYSTEM_PROMPT` — a static, f-string-built specification describing arm
  roles, coordinate frame, Z-depth math, motion profiles for every procedure,
  landmark semantics, feed-rate guidance, the strict JSON schema, and hard
  rules (exact landmark coords, Z floor, reach, refuse with `procedure="abort"`).
- Dataclasses: `Waypoint` (x, y, z, label, `dwell_s`), `ArmPlan` (arm_id,
  role, waypoints, feed_rate), `ProcedurePlan` (procedure, rationale, arm1,
  arm2, estimated_duration_s, safety_notes, raw_json, timestamp).
- `SurgicalAgent.plan(command, scene_state)`:
  1. Validates scene state (warning only).
  2. Builds messages: SYSTEM prompt + USER (command + `to_prompt_block()`) +
     ASSISTANT seed `"{"` to force JSON output.
  3. Calls Groq; on JSON/ValueError/KeyError, feeds the parse error back up to
     `MAX_RETRIES` times; raises `SurgicalAgentError` afterwards.
  4. `_parse_response` strips markdown fences, validates required keys, coerces
     feeds into [0.5, 15.0].
- `_call_groq` prepends `"{"` back onto the response content (the seed is
  *sent* but not *echoed*).

### 9.4 `robosurge/procedure_validator.py` — safety layer (654 lines)
- Constants: `MAX_CUT_DEPTH_CM = 12.0`, `MIN_ARM_CLEARANCE_CM = 2.5`,
  `MAX_WAYPOINT_DELTA_CM = 15.0`, feed bounds 0.5–15 mm/s,
  `LANDMARK_TOLERANCE_CM = 2.0`, `INTERP_STEP_CM = 0.1`,
  `MIN_INCISION_LENGTH_CM = 0.25`, point-procedure tolerance 2.0,
  debridement extent 4.0, `MIN_CAUTERIZATION_DWELL_S = 0.5`, suture tolerances.
- `ValidationResult` — ok flag + errors/warnings lists with `add_error`,
  `add_warning`, `summary()`.
- `ProcedureValidator.validate(plan)` runs all checks even after failures so the
  user gets a complete error list. Checks (all deterministic, stdlib+numpy):
  1. `_check_workspace_bounds` — every waypoint reach within [MIN_REACH, MAX_REACH].
  2. `_check_z_floor` — Z ≥ `TABLE_Z_CM - 12.0`.
  3. `_check_feed_rates` — within servo capability bounds.
  4. `_check_max_step_delta` — consecutive-waypoint 3-D distance ≤ 15 cm
     (catches LLM "teleports").
  5. `_check_inter_arm_clearance` — interpolates both paths at 1 mm resolution,
     pads shorter path, pairwise 3-D distance ≥ 2.5 cm at every step.
  6. `_check_procedure_arm_roles` — role sets valid per procedure (warning only).
  7. Procedure-specific: `_check_incision_landmark` (point-to-segment distance
     from drag line to target), `_check_point_procedure_landmark`,
     `_check_cauterization_dwell`, `_check_debridement_region`,
     `_check_suturing_pattern` (grouped by `stitchN_` labels).
- `_resolve_incision_target` infers the target from rationale/safety_notes text
  or nearest plunge point, defaulting to landmark_A.
- Static math helpers: `_point_to_segment_dist_2d`,
  `_interpolate_path` (linear at INTERP_STEP_CM).

### 9.5 `robosurge/motion_executor.py` — execution engine (388 lines)
- Constants: `LOOP_RATE_HZ = 10.0`, `WAYPOINT_DWELL_S = 0.15`,
  `SETUP_LEAD_S = 2.0`, `ABORT_FEED_MM_S = 15.0`, home = (10.0, 0.0,
  `SAFE_Z_CM`); `logs/last_execution_commands.log` path.
- `ExecutionResult` — per-arm stats (steps_sent, waypoints_hit, aborted,
  duration_s, final_position).
- `MotionExecutor(serial_write_fn=None, loop_rate_hz=10)`:
  - `execute(plan)` — clears abort flag, wipes the command log, then picks a
    strategy: **lead-follow** for incision/biopsy/cauterization/debridement
    (arm2 runs first to hang at the hold position; arm1 waits for that and
    follows with a 0.1 s sync gap), **concurrent** otherwise (e.g. suturing,
    where arm2's tug is timed to arm1's beats). Both arms run in daemon
    threads; returns a dict of `ExecutionResult`.
  - `abort()` — sets the abort flag, sleeps 200 ms for threads to see it, then
    synchronously sends both arms to `SAFE_Z_CM`.
  - `_execute_single_arm` — prepends a synthetic `"current"` waypoint at the
    arm's last commanded position, then per segment computes
    `n_steps = seg_mm / feed_rate / loop_interval`, sends interpolated commands
    every ~100 ms, dwells `WAYPOINT_DWELL_S` per waypoint, honors `dwell_s`
    (cauterization hold) via abort-checkable sleeps.
  - `_format_command` → `f"arm{id} {x:+.2f} {y:+.2f} {z:.2f}\n"`.
  - `_send` also appends each command to `logs/last_execution_commands.log`.
  - `current_positions` — thread-safe read of last commanded positions used by
    the abort path.

### 9.6 `robosurge/kinematics_engine.py` — forward kinematics (381 lines)
- Constants: `BASE_HEIGHT = 7.5`, `L1 = 9.5`, `L2 = 12.0`,
  `MAX_REACH = L1 + L2 = 21.5`, `MIN_REACH = 2.5`.
- `FKResult` — frozen dataclass: tip/elbow (x, y, z), `reach_xy`,
  `in_reachable_workspace`.
- `ForwardKinematics.calculate_fk(base_angle, shoulder_angle, elbow_angle)` —
  product of 4×4 homogeneous matrices: `T_world_base` (translate +Z by
  BASE_HEIGHT) → `T_base_shoulder` (Rz pan) → `T_shoulder_elbow`
  (Ry pitch, translate L1) → `T_elbow_tip` (Ry elbow, translate L2); extracts
  `[:3,3]` as positions. Joint conventions are documented as DH-compatible.
- `batch_calculate_fk`, `scalar_cross_check` (pure trigonometry) — used for
  independent unit verification.
- Standalone `__main__` smoke test prints matrix vs scalar deltas for 4 poses.

### 9.7 `robosurge/vision_pipeline.py` — pose tracking (176 lines)
- `ArmPoseResult` — pixel coords for base/elbow/wrist/tip (or None when below
  threshold/occluded).
- `PoseTracker(weights_path="robosurge_pose_best.pt", camera_index=1)`:
  `conf_threshold = 0.60` (keypoint), `detection_threshold = 0.35` (box);
  opens 1280×720@30 camera; `process_frame` runs the YOLOv8-pose model and
  returns **a list of poses** (multi-arm); `draw_pose` overlays labeled
  skeletons. Gracefully degrades (`_ULTRALYTICS_AVAILABLE`) if ultralytics is
  missing.

### 9.8 `robosurge/landmark_detector.py` — fiducial detection (503 lines)
- Detects colored dots (~8 mm) on the table. Actual configured colors in
  `LANDMARK_CONFIGS`: **landmark_A = yellow** (H 20–35), **landmark_B = cyan**
  (H 80–100), **landmark_C = purple** (H 115–165, widened). (Note: the
  module's header docstring says A=magenta/B=cyan/C=yellow but the live config
  and README agree on yellow/cyan/purple — the docstring is stale.)
- Preferable parameters: blur 5×5, elliptical 5×5 open/close morphology, dot
  area filter 100–3000 px, pixel bounding box to reject servo/background
  false positives, circularity ≥ 0.40.
- Algorithm per color: HSV inRange (two ranges merged for hue-wrap) → morph
  open/close → largest external contour passing filters → subpixel centroid via
  image moments → `mapper.pixel_to_physical()` → `Z = TABLE_Z_CM + z_offset`.
- Confidence = 0.75·circularity + 0.25·(area/600), clamped [0,1].
- `run_tuner(camera_index)` — interactive HSV trackbar tuner (run with
  `--tune`).
- `LandmarkFrame` — per-frame detection container with lookups.
- Standalone entry: `python -m robosurge.landmark_detector --tune 1` or
  `python -m robosurge.landmark_detector 1`.

### 9.9 `robosurge/sensor_fusion.py` — pixel→cm mapping / Phase-3 bridge (767 lines)
- `HomographyMapper` — global 3×3 planar homography via
  `cv2.findHomography(..., RANSAC, 0.5 px)`; `pixel_to_physical`, `recalibrate`.
- `LocalAffineMapper` — **the default mapper**: for each query, fits a fresh
  inverse-distance-weighted affine (`[x,y] = [u,v,1] @ A`) over the k=6 nearest
  calibration points (`np.linalg.lstsq`), so pose-dependent IK error that a
  single global plane can't absorb gets corrected regionally.
  `leave_one_out_errors()` gives honest out-of-sample error.
- Calibration constants `CALIBRATION_PHYSICAL_PTS` / `CALIBRATION_PIXEL_PTS`
  (15 points spanning a ~16×12 cm rectangle at X=5..17, Y=-6..6) — marked
  "replace with measured values".
- `filter_and_sort_arms` — drop no-tip detections, sort left→right by pixel X,
  cap at `MAX_ARMS = 2`.
- `build_serial_command(arm_id, x, y, z)` → `arm<N> +X +Y Z\n` (2 d.p.).
- `assign_arms` — full raw-detections → `AssignedArm` (arm_id, pixel, physical,
  serial_command).
- `FusionBridge` — standalone Phase-3 controller: opens camera + serial
  (dry-runs on failure), spins the 10 Hz loop (grab → YOLO → assign → write
  serial → ANSI status block → OpenCV live window), clean teardown + summary.
- `_parse_cli` for `--port`, `--weights`, `--cam` (also falls back to stock
  `yolov8n-pose.pt`).
- This is the only module that prints a continuously-overwritten ANSI terminal
  block (six fixed lines).

---

## 10. How the components interact

Interaction is driven by `robosurge/cli.py`:

1. **Startup** (`main()` → `RoboSurgeCLI.__init__`):
   - Builds `LocalAffineMapper` from calibration constants.
   - Builds `PoseTracker` (YOLO weights, camera index), `LandmarkDetector`
     (wraps the mapper), `SurgicalAgent` (Groq key from env), `ForwardKinematics`.
   - Opens serial (or null→dry-run) and hands a write-callback wrapper to
     `MotionExecutor`.
   - Installs SIGINT → abort+shutdown.
2. **Per frame** (`VisionThread`): `PoseTracker.process_frame` →
   (arm tips **hardcoded to home**; FK not used because the ESP32 does not
   report joint angles) → `LandmarkDetector.process_frame` → assembled
   `SceneState` pushed into `SharedState`.
3. **Per command** (`_handle_command`): reads `SharedState` → `SurgicalAgent.plan`
   → repair functions overwrite arm plans with deterministic geometry using
   `LandmarkState` coords + `TABLE_Z_CM` + tool offset + robot calibration →
   `ProcedureValidator.validate` → on pass, `MotionExecutor.execute` streams
   serial commands → ESP32 on-chip IK drives servo goals.

Arrow summary:

```
PoseTracker ──pixels──► LocalAffineMapper ──cm──► (not used for arms currently)
LandmarkDetector ──detections──► LandmarkState ──► SceneState ──► SurgicalAgent
MotionExecutor ──serial──► ESP32 IK ──► servos        ▲
ProcedureValidator ◄── ProcedurePlan ── repairs ◄──────┘ (cli.py rebuilds geometry)
```

---

## 11. Data flow

### Vision data flow (per tick, ~10 Hz)
```
Webcam frame
  → PoseTracker.process_frame          → list[ArmPoseResult]   (pixel keypoints)
  → LandmarkDetector.process_frame     → LandmarkFrame         (pixel centroids)
  → mapper.pixel_to_physical           → (x_cm, y_cm)          (LandmarkDetector)
  → LandmarkState list
  → SceneState{arms=[home,home], landmarks=[...], tool_z_offset}
  → SharedState.write(state, annotated)   [thread-safe]
  → (CLI reads later)
```

### Command data flow (on user input)
```
"make a 3mm incision at landmark A"
  → _handle_command
  → state = SharedState.read()
  → SurgicalAgent.plan(cmd, state)
       [Groq HTTP → llama-3.3-70b-versatile → JSON → ProcedurePlan]
  → _repair_incision_plan / _repair_biopsy_plan / _repair_cauterization_plan /
    _repair_debridement_plan / _repair_suturing_plan   (rewrite waypoints)
  → ProcedureValidator.validate(plan) → ValidationResult
  → (print plan + serial preview; user confirms [y])
  → MotionExecutor.execute(plan)
       [threads interpolate waypoints → call serial_write_fn at 10 Hz]
  → ESP32 (IK) → servo motions
  → ExecutionResult reported; log written to logs/last_execution_commands.log
```

### Calibration data flow
- Tool Z-offset: user pins tip → angles → FK → `offset = TABLE_Z_CM − tip_z` →
  `config/tool_offset.json` → loaded at startup → embedded in every plan's Z math.
- XY calibration: `tools/calibrate_via_fk.py` drives arm1 over a grid, samples
  tip pixels, builds/`LocalAffineMapper` fit, writes
  `data/calibration/{calibration_points.csv, calibration_fit.json,
  calibration_paste.py}`; live nudges (`nudge`/`scale`, unwired — see §17)
  persist to `config/robot_calibration.json` and are applied by
  `_apply_robot_calibration`.

---

## 12. Program execution flow

1. `python main.py [--port COM6] [--cam 1] [--weights ...] [--calibrate]
   [--dry-run]`
2. `robosurge.cli.main()`: parse flags → resolve YOLO weights (CWD then
   `models/`) → `run_tool_calibration` (if `--calibrate`, interactive) or
   `load_tool_offset` → construct `RoboSurgeCLI`.
3. `RoboSurgeCLI.__init__` builds subsystems + serial + SIGINT handler.
4. `RoboSurgeCLI.run()`:
   - banner → `PoseTracker.open_camera()` → start `VisionThread` → wait ≤3 s for
     first `SceneState` → "Ready".
   - loop: read stdin; dispatch `quit/exit/q`, `status`, `abort`, else
     `_handle_command`; finally `shutdown()` (stops vision thread, releases
     camera, closes serial, destroys OpenCV windows).
5. Ctrl+C anywhere → SIGINT handler → `executor.abort()` → `shutdown()` → exit.

---

## 13. Important functions, classes, and modules

The most important callable surfaces (file:line in parentheses):

| Symbol | Where | Role |
|---|---|---|
| `main()` | `robosurge/cli.py:988` | CLI entry point |
| `RoboSurgeCLI` | `cli.py:770` | orchestrator + run loop |
| `VisionThread` | `cli.py:139` | 10 Hz perception publish |
| `_handle_command` | `cli.py:904` | full per-command pipeline |
| `_repair_incision_plan` | `cli.py:489` | deterministic incision geometry |
| `_repair_suturing_plan` | `cli.py:665` | stitch-pattern generator |
| `run_tool_calibration` | `cli.py:238` | Z-offset calibration |
| `SurgicalAgent.plan` | `surgical_agent.py:338` | NL→ProcedurePlan |
| `ProcedureValidator.validate` | `procedure_validator.py:114` | all safety checks |
| `MotionExecutor.execute` | `motion_executor.py:116` | threaded serial execution |
| `MotionExecutor.abort` | `motion_executor.py:144` | emergency stop/retract |
| `SceneState.to_prompt_block` | `scene_state.py:181` | LLM world-state block |
| `SceneState.validate` | `scene_state.py:211` | pre-plan warnings |
| `ForwardKinematics.calculate_fk` | `kinematics_engine.py:194` | joint→tip FK |
| `PoseTracker.process_frame` | `vision_pipeline.py:79` | YOLO multi-arm keypoints |
| `LandmarkDetector.process_frame` | `landmark_detector.py:239` | HSV fiducial detection |
| `LocalAffineMapper.pixel_to_physical` | `sensor_fusion.py:362` | pixel→cm |
| `LocalAffineMapper.leave_one_out_errors` | `sensor_fusion.py:369` | calibration QA |
| `assign_arms` | `sensor_fusion.py:432` | detections→AssignedArm |
| `FusionBridge.run` | `sensor_fusion.py:632` | Phase-3 loop |

---

## 14. Algorithms and logic used

- **Forward kinematics**: product of 4×4 homogeneous transforms
  (T_world_base · Rz(pan) · [Ry(shoulder)·T(L1)] · [Ry(elbow)·T(L2)]) —
  verified by an independent planar-trig `scalar_cross_check`.
- **Pixel→cm mapping**:
  - Global: `cv2.findHomography(src=pixels, dst=cm, RANSAC,
    ransacReprojThreshold=0.5)`.
  - Local (default): for each query, k=6 nearest calibration points →
    inverse-distance-weighted least-squares affine fit over `[u,v,1]`,
    `np.linalg.lstsq`. Leave-one-out errors quantify accuracy
    (current fit mean ≈ 2.49 cm, max ≈ 6.82 cm — see §17).
- **Landmark detection**: HSV inRange + union of wrap-around ranges →
  morphological open/close → external contours → area + circularity
  (`4πA/P² ≥ 0.4`) filters → largest contour → image-moment subpixel centroid
  → rejection by calibrated pixel bounding box → pixel→cm → blended confidence.
- **Incidence/point alignment checks**: point-to-segment distance for
  incision drag; point distance for biopsy/cauterization plunge.
- **Inter-arm clearance**: linear interpolation of both paths at 0.1 cm steps
  (per 3-D Euclidean length), pad to equal length, pairwise spacing ≥ 2.5 cm.
- **Deterministic plan repair**: regex-based extraction of millimeters /
  stitch counts / target landmark from the NL command, then waypoint template
  generation (±7 cm lateral hold choice via reach minimization, scale/offset
  calibration applied).
- **Waypoint streaming**: equal-duration step fraction (not equal-distance)
  along each segment — `n_steps = segment_mm / feed_rate / dt`, one command
  every ~100 ms — giving servo feed-rate control in mm/s.
- **Z-depth math**: cut Z = `TABLE_Z_CM − depth_cm`; approach Z =
  `TABLE_Z_CM + 0.2`; all surgical Z never below `TABLE_Z_CM − 12.0`.
- **LLM self-correction**: parse errors are fed back to the model as a
  correction request, up to 3 attempts.

---

## 15. APIs and external services

- **Groq API** (`https://api.groq.com` via the `groq` Python SDK): chat
  completions with model `llama-3.3-70b-versatile`, `max_tokens=2048`,
  `temperature=0.0`. The only external network dependency. Key: `GROQ_API_KEY`.
- **Ultralytics YOLO** inference is local (CPU/GPU) via the `ultralytics`
  package loading `models/robosurge_pose_best.pt`.
- **ESP32 firmware** is *not in this repository*; the Python side only speaks
  the line protocol `arm<N> X Y Z\n` (ASCII, 115200 baud) and never reads
  status back (see §17).
- No other external APIs, databases, or cloud services are used.

---

## 16. Hardware components

| Component | Detail |
|---|---|
| Robot arms | 2 × 3-DOF servo arms (base pan + shoulder + elbow), IK runs on board the ESP32 |
| Serial link | USB serial, default `COM6`, 115200 baud, 20 ms timeout |
| Camera | Any webcam / RTSP URL, default index `1` (was "Camo Studio over USB") |
| Fiducials | Colored dots on the field: **A = yellow**, **B = cyan**, **C = purple** (~8 mm) |
| Workspace geometry | Link lengths L1=9.5 cm, L2=12.0 cm, base height 7.5 cm, reach 2.5–21.5 cm |
| Z-frame note | ESP32 Z=0 is ~7.66 cm above table; table contact = `TABLE_Z_CM = -7.66` |
| Tool | scalpel tip on arm1; the calibrated tool Z offset (`11.13 cm` in config) reconciles FK datum vs. physical tip when touching the table |

---

## 17. Configuration requirements

### Environment variables
- `GROQ_API_KEY` — required by `SurgicalAgent` (raised as `EnvironmentError`
  if missing). Loaded from `.env` (via `python-dotenv` in `cli.py` and
  `landmark_detector.py`). `.env` is gitignored.

### Runtime config files
- `config/tool_offset.json` — `{"tool_z_offset_cm": 11.130...}`. Written by
  `--calibrate`, loaded at startup; used in cut-Z math by the executor tests
  and by repair logic conceptually.
- `config/robot_calibration.json` — `{scale_x, scale_y, offset_x_cm,
  offset_y_cm}` (currently identity/default). Applied by
  `_apply_robot_calibration` to every XY target; editable live with the
  `nudge`/`scale` commands (defined, but not yet wired into the loop).

### Hardcoded calibration (edit in source)
- `CALIBRATION_PHYSICAL_PTS` / `CALIBRATION_PIXEL_PTS` in
  `sensor_fusion.py` (also mirrored in `data/calibration/calibration_fit.json`
  and `calibration_paste.py`).
- Fiducial HSV ranges in `LANDMARK_CONFIGS` (`landmark_detector.py`).
- Pixel bounding box for landmark rejection (`PIXEL_BOUND_*`).
- YOLO weights path default `robosurge_pose_best.pt` (CWD, then `models/`).

### Hardware assumptions
- ESP32 on `COM6` @ 115200; camera index `1`; both overridable with flags.

---

## 18. Build and installation instructions

No compilation/build step — pure Python. Requires **Python 3.11+** (newer
type-hint syntax).

```powershell
# 1. (Recommended) virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create .env at project root
#    GROQ_API_KEY=<your Groq API key>
```

Optional but expected for real hardware: the YOLO weights file
`models/robosurge_pose_best.pt`, the ESP32 device, and the webcam are
grouped-in artifacts (weights ship in the repo).

---

## 19. How to run the project

```powershell
# With hardware
python main.py --port COM6 --cam 1

# No robot attached — serial commands are printed, camera still used
python main.py --dry-run --cam 1

# Interactive tool Z-offset calibration at startup
python main.py --calibrate --port COM6 --cam 1

# Equivalent module invocation
python -m robosurge.cli --port COM6 --cam 1
```

### CLI flags
| Flag | Meaning |
|---|---|
| `--port <port>` | Serial port (default `COM6`) |
| `--cam <n|url>` | Camera index or URL (default `1`) |
| `--weights <file>` | YOLO weights (default searches CWD then `models/`) |
| `--calibrate` | Run interactive tool Z-offset calibration at startup |
| `--dry-run` | Print serial commands instead of sending them |

### In-session commands
| Input | Action |
|---|---|
| any natural language | Plan + confirm + execute a procedure |
| `status` | Print current SceneState (arms, landmarks, calibration) |
| `abort` | Immediately stop both arms and retract to safe height |
| `quit` / `exit` / `q` | Exit cleanly |

`cal` / `nudge <dx> <dy>` / `scale <sx> <sy>` are documented in the README as
live XY-correction commands; the parser/handler exists in `cli.py` but is **not
currently invoked** by the command loop (see §22 limitations).

Supported procedure examples:
```
make a 3mm incision at landmark A
biopsy landmark B
cauterize the mark at landmark A
put in 4 sutures at landmark A
debride the region at landmark A
go home
```

### Standalone utility invocations
```powershell
# Phase-3 fusion loop (vision → serial bridge)
python -m robosurge.sensor_fusion --port COM6 --cam 1

# Pose-tracking preview window
python -m robosurge.vision_pipeline [weights] [cam]

# Landmark detector live view / HSV tuner
python -m robosurge.landmark_detector 1
python -m robosurge.landmark_detector --tune 1

# Auto pixel↔cm calibration by driving arm1
python tools/calibrate_via_fk.py --port COM6

# Grab one camera frame
python tools/cam_test.py

# Generate YOLO training sweeps / extract frames (Phase 2; needs ESP32+video)
python training/generate_training_movements.py --port COM6
python training/extract_frames.py --video calibration_video.mp4 --out dataset_images
```

---

## 20. Testing procedure

There is **no automated test suite** (no pytest/CI) in the repo. Testing is done
through:

1. **Module self-tests** (no hardware needed). Each runs its own demo scenario
   when executed as `__main__`:
   ```powershell
   python -m robosurge.kinematics_engine      # FK vs. scalar cross-check table
   python -m robosurge.scene_state            # world-model prompt-block + validation demo
   python -m robosurge.procedure_validator    # "good" vs "bad" plan validation demo
   python -m robosurge.motion_executor        # dry-run execution of a 3 mm incision test plan
   ```
   Note: `python -m robosurge.surgical_agent` requires `GROQ_API_KEY` and makes
   a live Groq call (it will plan and print a plan for a default command).
2. **Dry-run end-to-end drill**: `python main.py --dry-run --cam 1`, then type
   `make a 3mm incision at landmark A` and confirm — exercises vision, planning,
   repair, validation, and the executor's print-only mode without any robot.
3. **Validation-layer negative test**: the `procedure_validator` self-test
   includes an intentionally bad plan (Z below floor + arm collision) that must
   produce `FAIL`.
4. **Hardware-level validation**: the standalone `procedure_validator` and
   `motion_executor` logs, plus post-run `logs/last_execution_commands.log`,
   provide an audit trail of exactly what commands were sent.

---

## 21. Important implementation details

- **Single source of truth for Z**: `TABLE_Z_CM` lives only in `scene_state.py`
  and is imported by `sensor_fusion`, `landmark_detector`, `surgical_agent`,
  `procedure_validator`, `motion_executor`, and `cli`. The value (-7.66) was
  physically proven by the command `arm1 +12.95 +3.47 -7.66` touching
  `landmark_A` on 2026-06-19.
- **Arm positions are FK-stubbed**: the LLM is currently told the arms are at
  home because the ESP32 never reports live joint angles back (see README note
  and `VisionThread._tick`). Timestamps/sources still flow through.
- **Serial protocol**: `arm<N> X Y Z\n`, explicit `+` signs on signed values,
  2 d.p.; all Python-side coordinates use a *negative* Z for table/penetration
  in the ESP32 command frame while several older docstrings/tests still assume
  positive table Z (legacy drift, see limitations).
- **Threading model**: vision thread (daemon) + two arm-execution threads
  (daemon) per command + locking around shared positions; `MotionExecutor`
  guards its command log only while executing; `SharedState` guards scene reads.
- **The `_send` audit log** appends every command to
  `logs/last_execution_commands.log`.
- **Programmatic fallbacks**: missing serial → dry-run; missing ultralytics →
  ImportError with guidance; missing weights → stock `yolov8n-pose.pt` (keypoint
  labels then won't match); invalid calibration parse → identity/default.
- **`Sync.ffs_db`** indicates the repo tree is kept in sync with the robot PC
  via FreeFileSync — files may be edited there and synced back here.

---

## 22. Known limitations

- **No automated test suite** — validation relies on module `__main__` demos
  and manual drills.
- **Arm positions fed to the LLM are hardcoded to home** until the ESP32
  reports live joint angles back over serial (the FK engine and vision bridge
  exist, but the current loop doesn't use either for arm state).
- **`_handle_calibration_command` is dead code**: the `cal`/`nudge`/`scale`
  in-session commands documented in the README parse but are never dispatched
  from the command loop, so live XY nudges cannot actually be applied. (The
  file `config/robot_calibration.json` still is applied at plan-repair time via
  `_apply_robot_calibration`.)
- **Potential broken absolute imports in two repair functions**:
  `cli.py:604` and `cli.py:681` use `from surgical_agent import ...`
  (top-level), but no top-level module `surgical_agent` exists — it lives at
  `robosurge.surgical_agent`. Running `python main.py` from the project root,
  the cauterization and suturing repair paths will raise `ModuleNotFoundError`
  when reached.
- **Stale Z assumptions in older code/tests**: `TABLE_Z_CM = -7.66` is the live
  calibration, but `motion_executor`'s self-test comment/values, several
  `surgical_agent`/`scene_state` self-test fixtures, and Phase-1/2 archive code
  still reason with the old `7.5` table Z (e.g. `cut_z 7.35`). Some module
  self-tests may therefore print physically meaningless numbers without failing.
- **Calibration accuracy**: the current local-affine fit reports mean
  leave-one-out error ≈ 2.49 cm, max ≈ 6.82 cm (`data/calibration/
  calibration_fit.json`) — notable for mm-scale surgical motions; accuracy is
  camera/IK-pose dependent, and the header in `sensor_fusion.py` still labels
  the constants "APPROXIMATE for initial wiring validation".
- **Vision→IK mismatch**: `sensor_fusion.py`'s Phase-3 loop streams vision
  tips straight to the ESP32 fixed at `TABLE_Z_CM` (all points assumed on the
  table plane); this is not wired into the Phase-4 path.
- **`live_calib_check.png` overwritten at ~10 Hz** by `VisionThread._tick`
  (unnecessary disk I/O in the loop; file is gitignored).
- **LLM-dependent planning**: a valid plan requires Groq connectivity and a
  parseable model response; malformed JSON is retried up to 3× then the
  command is rejected (no offline fallback).
- **Landmarks assumed on the table plane** (Z = `TABLE_Z_CM`); elevated tissue
  needs a `z_offset_cm` per config.
- **Suturing is a visual demo only** — the tool tip traces stitch motion; there
  is no needle/thread mechanism.
- **Stale docstrings**: e.g. `landmark_detector.py` header lists different
  fiducial colors (magenta/cyan/yellow) than the live config and README
  (yellow/cyan/purple); `cli.py` module docstring refers to itself as
  `robosurge_cli.py`, and `surgical_agent`/`scene_state` fixtures still assume
  old Z values.
- **ESP32 firmware is not in this repo**; joint-angle reporting and IK details
  are off-repo assumptions.

---

## 23. Possible future extensions

(These are suggestions informed by gaps in the current repo — none are
implemented.)

- **Live joint-angle feedback over serial**: have the ESP32 stream current IK
  angles/Jacobian state so `VisionThread._tick` can populate real `ArmState`s
  (source="FK") instead of hardcoded home; this unlocks true vision/FK fusion
  and closed-loop positioning.
- **Wire up `_handle_calibration_command`** so `nudge`/`scale` take effect
  live, and invoke `/calibrate`-style workflows from within a session.
- **Fix the top-level `surgical_agent` imports** in `cli.py` (make them
  relative) and add regression/unit tests (hypothesis/pytest) for the repair,
  validation, and kinematics modules — including numeric cross-checks against
  the now-mismatched legacy Z fixtures.
- **Automated calibration refresh**: load `CALIBRATION_PHYSICAL_PTS/PIXEL_PTS`
  from `data/calibration/calibration_fit.json` instead of source constants.
- **End-to-end dry-run tests** that mock Groq (fixed `ProcedurePlan` JSON) and
  the serial port, asserting the exact command stream for each procedure type.
- **Camera-parametric tool offset**: incorporate z_offset_cm per landmark and
  tissue-thickness estimates in Z math.
- **Multi-view / ArUco fusion**: Phase 2's `stereo_tracker.py` could be revived
  to add 3-D and occlusion resilience where YOLO keypoints drop out.
- **Health-check/telemetry**: periodic serial status queries, watchdog
  heartbeat, and richer session logging.
- **Move calibration Z/frame constants fully into one config file** (JSON/env)
  rather than source constants, to end the docstring/constant drift.

---

## 24. Quick reference — key serial command format

```
arm1 +12.95 +3.47 -7.66\n     # move arm 1 to X=12.95, Y=3.47, Z=-7.66 cm (table contact)
arm2 +10.00 +0.00 -5.16\n     # move arm 2 to home/safe height
```

Physical frame (per `kinematics_engine.py`): origin at base-tower bottom-centre
on the table, X forward, Y left, Z up — but the **ESP32 command frame has Z≈0
at ~7.66 cm above the table**, so table-level Z is `-7.66` (constant
`TABLE_Z_CM`).

---

*End of CODEBASE.md. Compiled directly from the repository at commit `d98ee39`
— sources of truth: `robosurge/*.py`, `README.md`, `requirements.txt`,
`config/`, `data/calibration/`, `tools/`, `training/`, `archive/`.*