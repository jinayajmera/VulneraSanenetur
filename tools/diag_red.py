"""
tools/diag_red.py — is anything red in the frame leaking into the three
landmark masks?

Finds red blobs, then for each configured landmark colour reports every blob
that survives the mask, so it is obvious whether a red corner dot is being
picked up as landmark A/B/C or whether it is ignored entirely.

Usage:
    python tools/diag_red.py live_calib_check.png
"""
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from robosurge.landmark_detector import (
    LANDMARK_CONFIGS, MIN_DOT_AREA_PX, MAX_DOT_AREA_PX,
    PIXEL_BOUND_U_MIN, PIXEL_BOUND_U_MAX, PIXEL_BOUND_V_MIN, PIXEL_BOUND_V_MAX,
)

img = sys.argv[1] if len(sys.argv) > 1 else "live_calib_check.png"
frame = cv2.imread(img)
if frame is None:
    sys.exit(f"could not read {img}")
hsv = cv2.cvtColor(cv2.GaussianBlur(frame, (5, 5), 0), cv2.COLOR_BGR2HSV)


def blobs(mask, min_area=60):
    n, _, stats, cents = cv2.connectedComponentsWithStats(mask, connectivity=8)
    out = []
    for i in range(1, n):
        a = int(stats[i, cv2.CC_STAT_AREA])
        if a >= min_area:
            out.append((a, float(cents[i][0]), float(cents[i][1])))
    return sorted(out, reverse=True)


# Red wraps hue 0, so it needs two ranges.
red = cv2.bitwise_or(
    cv2.inRange(hsv, np.array([0, 90, 70]), np.array([10, 255, 255])),
    cv2.inRange(hsv, np.array([170, 90, 70]), np.array([179, 255, 255])),
)
red_blobs = blobs(red)
print(f"RED blobs in frame ({len(red_blobs)} with area>=60):")
for a, u, v in red_blobs[:10]:
    h, s, val = hsv[int(v), int(u)]
    print(f"  area={a:5d} at ({u:6.1f},{v:6.1f})  HSV=({h},{s},{val})")

print("\nDoes any red blob survive a landmark mask?")
for cfg in LANDMARK_CONFIGS:
    m = cv2.inRange(hsv, cfg.hsv_lower, cfg.hsv_upper)
    if cfg.hsv_lower2 is not None:
        m = cv2.bitwise_or(m, cv2.inRange(hsv, cfg.hsv_lower2, cfg.hsv_upper2))
    overlap = cv2.bitwise_and(m, red)
    n_ov = int(overlap.sum() // 255)
    print(f"\n{cfg.name}  (H {cfg.hsv_lower[0]}-{cfg.hsv_upper[0]}, "
          f"S>={cfg.hsv_lower[1]}, V>={cfg.hsv_lower[2]})")
    print(f"  pixels shared with red mask: {n_ov}")
    for a, u, v in blobs(m):
        in_area = MIN_DOT_AREA_PX <= a <= MAX_DOT_AREA_PX
        in_box = (PIXEL_BOUND_U_MIN <= u <= PIXEL_BOUND_U_MAX and
                  PIXEL_BOUND_V_MIN <= v <= PIXEL_BOUND_V_MAX)
        is_red = any(abs(u - ru) < 25 and abs(v - rv) < 25 for _, ru, rv in red_blobs)
        verdict = ("SURVIVES" if (in_area and in_box) else
                   f"filtered ({'area' if not in_area else ''}"
                   f"{' ' if not in_area and not in_box else ''}"
                   f"{'bounds' if not in_box else ''})")
        print(f"    area={a:5d} at ({u:6.1f},{v:6.1f})  {verdict}"
              f"{'   <-- RED BLOB' if is_red else ''}")
