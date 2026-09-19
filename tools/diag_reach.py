"""
tools/diag_reach.py — estimate where the fiducial dots actually are in
physical cm, using a GLOBAL fit (affine + homography) instead of the local
affine.  A global fit extrapolates far more sanely outside the calibration
hull, so it is good enough to answer "can the arm even reach these dots?".
"""
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from robosurge.scene_state import MIN_REACH, MAX_REACH
from robosurge.sensor_fusion import (
    CALIBRATION_PHYSICAL_PTS as P, CALIBRATION_PIXEL_PTS as X,
)

phys = np.array(P, dtype=np.float64)
pix = np.array(X, dtype=np.float64)

# --- global least-squares affine: [u v 1] @ A = [x y]
Apix = np.hstack([pix, np.ones((len(pix), 1))])
A, *_ = np.linalg.lstsq(Apix, phys, rcond=None)
pred = Apix @ A
res = np.linalg.norm(pred - phys, axis=1)
print(f"global affine   : mean residual {res.mean():.2f} cm, max {res.max():.2f} cm")

# --- global homography
H, _ = cv2.findHomography(pix.reshape(-1, 1, 2), phys.reshape(-1, 1, 2), 0)
ph = cv2.perspectiveTransform(pix.reshape(-1, 1, 2), H).reshape(-1, 2)
rh = np.linalg.norm(ph - phys, axis=1)
print(f"global homography: mean residual {rh.mean():.2f} cm, max {rh.max():.2f} cm")

print(f"\narm reach envelope: {MIN_REACH} .. {MAX_REACH} cm")
print(f"calibration grid reach: "
      f"{np.hypot(phys[:,0], phys[:,1]).min():.1f} .. "
      f"{np.hypot(phys[:,0], phys[:,1]).max():.1f} cm")

DOTS = {
    "landmark_A (yellow)": (664.8, 428.6),
    "landmark_B (cyan)":   (859.6, 445.6),
    "landmark_C (purple)": (767.7, 506.9),
}

print("\nestimated physical position of each dot:")
for name, (u, v) in DOTS.items():
    xa, ya = (np.array([u, v, 1.0]) @ A)
    xh, yh = cv2.perspectiveTransform(
        np.array([[[u, v]]], dtype=np.float64), H).reshape(2)
    ra, rh_ = np.hypot(xa, ya), np.hypot(xh, yh)
    ok = MIN_REACH <= rh_ <= MAX_REACH
    print(f"  {name:22s} affine=({xa:+6.1f},{ya:+6.1f}) r={ra:5.1f}   "
          f"homography=({xh:+6.1f},{yh:+6.1f}) r={rh_:5.1f}cm   "
          f"{'REACHABLE' if ok else 'OUT OF REACH'}")

# Where does the arm's reach envelope land in pixels?  Invert the homography.
Hinv = np.linalg.inv(H)
print("\npixel footprint of the reachable workspace (via homography):")
pts = []
for r in np.linspace(MIN_REACH, MAX_REACH, 24):
    for th in np.linspace(-np.pi / 2, np.pi / 2, 48):
        pts.append([r * np.cos(th), r * np.sin(th)])
pp = cv2.perspectiveTransform(
    np.array(pts, dtype=np.float64).reshape(-1, 1, 2), Hinv).reshape(-1, 2)
inframe = pp[(pp[:, 0] >= 0) & (pp[:, 0] < 1280) & (pp[:, 1] >= 0) & (pp[:, 1] < 720)]
print(f"  u range {inframe[:,0].min():.0f} .. {inframe[:,0].max():.0f}")
print(f"  v range {inframe[:,1].min():.0f} .. {inframe[:,1].max():.0f}")
