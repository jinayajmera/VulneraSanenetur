# RoboSurge

Dual-arm robotic surgical system demo: type a natural-language command ("make a 3mm incision at landmark A") and the system **perceives** the scene with a camera, **plans** the procedure with an LLM, **validates** it against hard safety rules, and **executes** it on real hardware over serial.

> ⚠️ This is a research/demo platform running on a benchtop phantom — not a medical device.

---

## How it works

```
                 ┌───────────────────────────  camera ───────────────────────────┐
                 │                                                                │
        PoseTracker (YOLOv8-pose)                          LandmarkDetector (HSV)
          arm skeleton pixels                               colored fiducial dots
                 │                                                 pixel → cm
                 │                                                        │
                 └──────────────►  SceneState  ◄─────────────────────────┘
                                   (world model)

   natural-language command
              │
              ▼
       SurgicalAgent ── Groq gpt-oss-120b ──► ProcedurePlan JSON (intent only)
              │
              ▼
   deterministic plan repair ── exact cut geometry rebuilt from landmarks
              │
              ▼
     ProcedureValidator ── pure-math safety checks (bounds, clearance, ...)
              │
              ▼
      MotionExecutor ── waypoint interpolation @ 10 Hz ──► ESP32 (on-chip IK)
```

The LLM decides **what** to do; every robot-critical number (depths, waypoints,
stitch patterns) is deterministically rebuilt and re-checked before a single
serial byte is sent.

## Hardware

| Component | Detail |
|---|---|
| Robot | 2 × 3-DOF servo arms (base pan + shoulder + elbow), IK runs on the ESP32 |
| Serial | USB serial, default `COM6` @ 115200 baud |
| Camera | Any webcam, default index `1` |
| Fiducials | Colored dots on the field: **A = yellow**, **B = cyan**, **C = purple** (~8 mm) |

## Project structure

```
RoboSurge/
├── main.py                  # entry point
├── robosurge/               # core package
│   ├── cli.py               #   interactive command loop, plan repair, wiring
│   ├── scene_state.py       #   world model + workspace constants (TABLE_Z_CM)
│   ├── surgical_agent.py    #   Groq LLM planner (NL → ProcedurePlan JSON)
│   ├── procedure_validator.py#  safety validation layer (pure math)
│   ├── motion_executor.py   #   waypoint interpolation + serial streaming
│   ├── kinematics_engine.py #   forward kinematics for the 3-DOF arm
│   ├── vision_pipeline.py   #   YOLOv8-pose arm tracking
│   ├── landmark_detector.py #   HSV fiducial detection
│   └── sensor_fusion.py     #   pixel→cm mapping (LocalAffineMapper) + legacy bridge
├── config/
│   ├── tool_offset.json     # tool Z-offset calibration result
│   └── robot_calibration.json # final XY scale/offset nudges
├── models/
│   └── robosurge_pose_best.pt # custom YOLOv8-pose weights (4 keypoints)
├── data/calibration/        # calibration points, fits, generated snippets
├── logs/                    # last_execution_commands.log (auto-generated)
├── tools/
│   ├── calibrate_via_fk.py  # auto pixel↔cm calibration by driving the arm
│   ├── cam_test.py          # grab a single frame
│   └── test.py              # HSV threshold scratch test
├── training/                # YOLO dataset generation + frames
└── archive/                 # legacy Phase 1–2 scripts
```

## Setup

Requires Python 3.11+.

```powershell
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```
GROQ_API_KEY=<your Groq API key>
```

Verify your hardware paths (change via CLI flags if different):
- ESP32 firmware on `COM6`, 115200 baud
- camera at index `1`

## Usage

```powershell
# With hardware
python main.py --port COM6 --cam 1

# No robot attached (serial commands printed, not sent; camera still used)
python main.py --dry-run --cam 1
```

| Flag | Meaning |
|---|---|
| `--port <port>` | Serial port (default `COM6`) |
| `--cam <n\|url>` | Camera index or URL (default `1`) |
| `--weights <file>` | YOLO weights (default searches CWD then `models/`) |
| `--calibrate` | Run interactive tool Z-offset calibration at startup |
| `--dry-run` | Print serial commands instead of sending them |

### In-session commands

| Command | Action |
|---|---|
| any natural language | Plan + confirm + execute a procedure |
| `status` | Print current SceneState (arms, landmarks, calibration) |
| `abort` | Immediately stop both arms and retract to safe height |
| `cal`, `nudge <dx> <dy>`, `scale <sx> <sy>` | Live XY target corrections (saved to `config/robot_calibration.json`) |
| `quit` | Exit cleanly |

Ctrl+C at any time triggers abort + shutdown.

### Supported procedures

`incision`, `biopsy`, `cauterization` (with dwell), `debridement` (zigzag sweep),
`suturing` (visual demo stitch pattern, e.g. *"put in 3 sutures"*), `retraction`,
`hold`, `home`, `abort`.

Example commands:
```
make a 3mm incision at landmark A
biopsy landmark B
cauterize the mark at landmark A
put in 4 sutures at landmark A
go home
```

## Safety layers

1. **LLM sandboxing** — the model outputs intent + rough geometry only; all cut
   depths and waypoint sequences are deterministically reconstructed in
   `robosurge/cli.py`.
2. **ProcedureValidator** (`robosurge/procedure_validator.py`) — workspace bounds,
   Z floor, inter-arm clearance along interpolated paths, feed-rate limits,
   teleport detection, per-procedure landmark alignment checks. A failed plan is
   never executed.
3. **Human confirmation** — every plan prints a serial preview and requires `[y]`.
4. **Abort path** — `abort` command or Ctrl+C retracts both arms to safe height.

Feed rates are clamped to 0.5–15 mm/s; Z can never go below
`TABLE_Z_CM − MAX_CUT_DEPTH_CM`.

## Calibration workflows

| Task | Tool |
|---|---|
| Tool Z-offset (tip touching table) | `python main.py --calibrate` → saves `config/tool_offset.json` |
| Pixel ↔ cm mapping | `python tools/calibrate_via_fk.py --port COM6` — drives arm1 across a grid, samples pixels, fits a local-affine mapper, writes results to `data/calibration/` |
| Fiducial HSV tuning | `python -m robosurge.landmark_detector --tune 1` (interactive trackbars) |
| Live landmark check | `python -m robosurge.landmark_detector 1` |

Calibration constants currently live in `robosurge/sensor_fusion.py`
(`CALIBRATION_PHYSICAL_PTS` / `CALIBRATION_PIXEL_PTS`). The physical table Z is
defined once in `robosurge/scene_state.py` (`TABLE_Z_CM`) and imported everywhere.

## Module self-tests (no hardware needed)

```powershell
python -m robosurge.kinematics_engine      # FK vs scalar cross-check
python -m robosurge.scene_state            # world-model serialization
python -m robosurge.procedure_validator    # good/bad plan validation demo
python -m robosurge.motion_executor        # dry-run execution of a test plan
```

## Known limitations

- Arm positions fed to the LLM are hardcoded to home until the ESP32 reports
  live joint angles back over serial (see `VisionThread._tick` in
  `robosurge/cli.py`).
- Landmarks are assumed to lie on the table plane (Z = `TABLE_Z_CM`).
- Suturing is a visual demo (the tool tip traces the stitch motion; there is no
  needle/thread mechanism).
