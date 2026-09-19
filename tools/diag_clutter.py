"""
tools/diag_clutter.py — compare the HSV statistics of the real fiducial dot
against the clutter blobs competing in the same mask, so thresholds can be
tightened on evidence instead of guesswork.

Usage:
    python tools/diag_clutter.py live_calib_check.png
"""
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from robosurge.landmark_detector import LANDMARK_CONFIGS

img = sys.argv[1] if len(sys.argv) > 1 else "live_calib_check.png"
frame = cv2.imread(img)
if frame is None:
    sys.exit(f"could not read {img}")
hsv = cv2.cvtColor(cv2.GaussianBlur(frame, (5, 5), 0), cv2.COLOR_BGR2HSV)

for cfg in LANDMARK_CONFIGS:
    m = cv2.inRange(hsv, cfg.hsv_lower, cfg.hsv_upper)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN,
                         cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE,
                         cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    rows = []
    for c in cnts:
        a = cv2.contourArea(c)
        if a < 50:
            continue
        p = cv2.arcLength(c, True)
        circ = (4 * np.pi * a) / (p * p) if p > 0 else 0.0
        mask1 = np.zeros(m.shape, np.uint8)
        cv2.drawContours(mask1, [c], -1, 255, -1)
        px = hsv[mask1 > 0]
        mo = cv2.moments(c)
        cu, cv_ = mo["m10"] / mo["m00"], mo["m01"] / mo["m00"]
        rows.append((a, circ, cu, cv_, px.mean(axis=0), px.std(axis=0)))

    rows.sort(reverse=True, key=lambda r: r[0])
    print(f"\n=== {cfg.name}  H {cfg.hsv_lower[0]}-{cfg.hsv_upper[0]}  "
          f"S>={cfg.hsv_lower[1]}  V>={cfg.hsv_lower[2]} ===")
    for i, (a, circ, cu, cv_, mean, std) in enumerate(rows):
        tag = "REAL DOT" if i == 0 else "clutter "
        print(f"  {tag} area={a:7.0f} circ={circ:.2f} at ({cu:6.1f},{cv_:6.1f})  "
              f"H={mean[0]:5.1f}±{std[0]:4.1f}  "
              f"S={mean[1]:5.1f}±{std[1]:4.1f}  "
              f"V={mean[2]:5.1f}±{std[2]:4.1f}")
