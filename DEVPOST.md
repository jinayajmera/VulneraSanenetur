# RoboSurge

## Inspiration

Surgical robotics today sits at two extremes: million-dollar systems like the
da Vinci that still need a surgeon at the controls every second, or fully
autonomous concepts that only exist in research papers and simulations. We
wanted to find the middle ground — real hardware, under $100, that could take
a plain-English command like *"make a 3mm incision at landmark C"* and
actually execute it, safely, on physical arms. Not a demo of an LLM writing
code. A demo of an LLM directing a robot that can hurt something if it gets
the math wrong — which meant we couldn't let it anywhere near the math.

## What it does

You type a natural-language surgical command. RoboSurge's camera perceives
the scene — tracking both robot arms via a custom-trained YOLO pose model and
locating colored fiducial landmarks via HSV detection, fusing everything into
a live world model. An LLM (Claude, with Groq as fallback) interprets your
intent into a structured procedure plan. But the LLM never touches the actual
geometry — every cut depth, waypoint, and stitch pattern is deterministically
rebuilt from real landmark coordinates by our own code. A pure-math validator
then checks workspace bounds, table-floor limits, inter-arm collision
clearance, and feed rates before a single command is sent. Only after that
passes does a motion executor interpolate waypoints at 10 Hz and stream them
over serial to dual ESP32-driven 3-DOF arms, which run their own on-chip
inverse kinematics.

Supported procedures: incision, biopsy, cauterization, debridement, suturing,
and safe homing/abort.

## How we built it

- **Vision:** OpenCV + a custom-trained YOLOv8-pose model (4 keypoints) for
  arm tracking, HSV thresholding for fiducial landmarks, a locally-fit affine
  mapper to convert pixel coordinates to real-world centimeters
- **Planning:** An LLM call constrained to a strict JSON schema, so it can
  only output *intent* — procedure type, target landmark, rough parameters —
  never raw waypoints
- **Safety:** A standalone `ProcedureValidator` module doing pure arithmetic
  checks — no model in the loop — on every plan before execution is even
  offered to the human operator
- **Hardware control:** Python streams interpolated waypoints over serial at
  10 Hz to an ESP32 running inverse kinematics for two independent 3-DOF
  servo arms
- **Calibration:** A self-calibrating tool that drives the arm across a grid,
  watches where it lands on camera, and fits the pixel↔cm mapping
  automatically — no manual measuring

## Challenges we ran into

- **Provider migration under pressure** — Switching the LLM backend from Groq
  to Anthropic mid-build surfaced real API quirks: no `temperature` parameter
  in the new SDK, a `zstandard` decoding bug requiring a manual
  `Accept-Encoding: gzip` header, and "extended thinking" silently eating the
  entire token budget and returning empty responses on complex plans.
- **The landmark that wasn't where we thought** — A yellow fiducial appeared
  to be detected correctly but sent the arm to the wrong corner of the table.
  Root cause: the calibration only covered part of the pixel space, so
  anything outside it caused the pixel-to-physical mapper to extrapolate —
  the detector was right, the geometry was lying.
- **Ground truth that lied to itself** — Digging deeper into calibration
  accuracy (mean error 2.5 cm, unacceptable for millimeter-scale incisions),
  we found the real culprit: near the edges of the workspace, the arm was
  likely never physically reaching commanded positions (IK saturation), but
  the calibration tool recorded the *commanded* position as truth anyway —
  quietly corrupting its own training data.
- **Trusting an LLM near hardware, safely** — The hardest design constraint
  throughout: how much do you let a language model decide versus
  deterministically compute? We settled on "intent only," which shaped every
  architectural decision after.

## Accomplishments that we're proud of

- A five-layer safety architecture (LLM sandboxing → deterministic geometry
  rebuild → pure-math validation → human confirmation → instant abort) that
  caught real bugs — arm collisions, out-of-bounds waypoints — before they
  ever reached hardware
- Fully autonomous, self-driven calibration: the robot calibrates its own
  vision-to-physical mapping by moving itself and watching the result
- A clean provider-agnostic LLM layer that let us swap from Groq to Claude
  with zero changes anywhere else in the codebase
- Diagnosing a subtle extrapolation bug down to the exact pixel and
  centimeter, rather than just patching the symptom

## What we learned

- **Never let a generative model touch safety-critical numbers.**
  Constraining the LLM to intent-only output and rebuilding all geometry
  deterministically wasn't just safer — it also made failures far easier to
  debug, because a bad outcome was always traceable to either the plan or the
  math, never "the model felt like it."
- **Bad data can look exactly like noisy data.** A 2.5 cm calibration error
  looked like ordinary sensor imprecision until we noticed the pattern was
  concentrated at the workspace edges — which pointed to systematic IK
  saturation, not randomness.
- **Extrapolation fails silently.** A coordinate mapper doesn't know when
  it's guessing outside its trained region — it just returns a confident,
  wrong number. Any system fusing vision and physical coordinates needs an
  explicit "am I inside the trusted region?" check.

## What's next for RoboSurge

- Recalibrate inside a verified, physically-reachable workspace region
  (using our new `probe_workspace.py` reachability probe) instead of chasing
  accuracy at unreachable edges
- Add a hull-boundary guard so out-of-calibration landmark detections are
  automatically flagged with reduced confidence instead of silently
  extrapolating
- Correct the ESP32's link-length constants against the real physical arm to
  reduce baseline IK error everywhere, not just patch it with more
  calibration points
- Add force sensing so the LLM can reason about tissue resistance, and
  stereo vision for full 3D landmark localization
- Move from open-loop servo control toward closed-loop feedback for true
  sub-millimeter precision
