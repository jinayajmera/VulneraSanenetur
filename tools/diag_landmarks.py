"""
tools/diag_landmarks.py — one-shot diagnostic on a saved frame.

Reports, for each configured landmark colour:
  * the detected centroid in pixels
  * the physical (X, Y) the LocalAffineMapper produces
  * whether that centroid falls INSIDE the calibration hull

Usage:
    python tools/diag_landmarks.py live_calib_check.png
"""

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from robosurge.landmark_detector import LandmarkDetector, LANDMARK_CONFIGS
from robosurge.sensor_fusion import (
    LocalAffineMapper, CALIBRATION_PHYSICAL_PTS, CALIBRATION_PIXEL_PTS,
)

img_path = sys.argv[1] if len(sys.argv) > 1 else "live_calib_check.png"
frame = cv2.imread(img_path)
if frame is None:
    sys.exit(f"could not read {img_path}")
print(f"frame: {img_path}  shape={frame.shape}")

pix = np.array(CALIBRATION_PIXEL_PTS)
phys = np.array(CALIBRATION_PHYSICAL_PTS)
u_lo, v_lo = pix.min(axis=0)
u_hi, v_hi = pix.max(axis=0)
print(f"\ncalibration hull : u=[{u_lo:.0f}, {u_hi:.0f}]  v=[{v_lo:.0f}, {v_hi:.0f}]"
      f"   ({len(pix)} points)")
print(f"physical span    : X=[{phys[:,0].min():.1f}, {phys[:,0].max():.1f}] cm"
      f"  Y=[{phys[:,1].min():.1f}, {phys[:,1].max():.1f}] cm")

mapper = LocalAffineMapper(CALIBRATION_PHYSICAL_PTS, CALIBRATION_PIXEL_PTS)
errs = mapper.leave_one_out_errors()
print(f"leave-one-out err: mean={np.mean(errs):.2f} cm  max={np.max(errs):.2f} cm")

det = LandmarkDetector(mapper=mapper)
lf = det.process_frame(frame)

print("\n--- detections ---")
for c in LANDMARK_CONFIGS:
    d = lf.get(c.name)
    if d is None:
        print(f"{c.name:12s} NOT DETECTED   (hsv {c.hsv_lower.tolist()} -> {c.hsv_upper.tolist()})")
        continue
    inside = (u_lo <= d.pixel_u <= u_hi) and (v_lo <= d.pixel_v <= v_hi)
    du = 0 if u_lo <= d.pixel_u <= u_hi else min(abs(d.pixel_u - u_lo), abs(d.pixel_u - u_hi))
    dv = 0 if v_lo <= d.pixel_v <= v_hi else min(abs(d.pixel_v - v_lo), abs(d.pixel_v - v_hi))
    print(f"{c.name:12s} pixel=({d.pixel_u:7.1f},{d.pixel_v:7.1f})  "
          f"phys=({d.physical_x:+7.2f},{d.physical_y:+7.2f}) cm  "
          f"area={d.area_px:6.0f}  conf={d.confidence:.2f}  "
          f"{'INSIDE hull' if inside else f'OUTSIDE hull by ({du:.0f},{dv:.0f}) px'}")

# How badly does the mapper extrapolate? Walk right from the hull edge.
print("\n--- extrapolation sweep at v=470 ---")
for u in range(500, 1000, 50):
    x, y = mapper.pixel_to_physical(float(u), 470.0)
    tag = "" if u_lo <= u <= u_hi else "   <-- outside hull"
    print(f"  u={u:4d}  ->  X={x:+8.2f}  Y={y:+9.2f} cm{tag}")

# Raw mask pixel counts per colour, before any area/circularity/bounds filter.
print("\n--- raw mask coverage (before filters) ---")
hsv = cv2.cvtColor(cv2.GaussianBlur(frame, (5, 5), 0), cv2.COLOR_BGR2HSV)
for c in LANDMARK_CONFIGS:
    m = cv2.inRange(hsv, c.hsv_lower, c.hsv_upper)
    n, _, stats, cents = cv2.connectedComponentsWithStats(m, connectivity=8)
    blobs = sorted(
        ((stats[i, cv2.CC_STAT_AREA], cents[i]) for i in range(1, n)),
        reverse=True, key=lambda t: t[0],
    )[:4]
    print(f"{c.name:12s} mask px={int(m.sum()//255):6d}  top blobs: "
          + ", ".join(f"{int(a)}px@({cx:.0f},{cy:.0f})" for a, (cx, cy) in blobs))
