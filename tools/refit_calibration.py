"""
tools/refit_calibration.py — recover ambiguous calibration points offline.

The per-target acceptance logic in calibrate_via_fk.py can only look at one
target's detections at a time, so when the pose model reports two equally
persistent blobs (the tool tip and an elbow keypoint) it has no way to tell
which is which and must reject the point.

Globally the two are easy to separate: the tip tracks the commanded grid, the
elbow does not.  This script bootstraps that:

  1. Cluster each target's detections, drop the parked arm.
  2. Seed with the targets that had exactly one surviving candidate.
  3. Fit a RANSAC homography physical(cm) -> pixel on the seed set.
  4. For every ambiguous target, predict the pixel and keep the candidate
     nearest the prediction.
  5. Refit and repeat until the assignment stops changing.
  6. Prune whatever still has a large leave-one-out error.

Runs entirely on a saved log — no camera, no robot, no model changes.

Usage:
    python tools/refit_calibration.py logs/calib_run3.txt
    python tools/refit_calibration.py logs/calib_run3.txt --write
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.calibrate_via_fk import (
    ARM2_EXCLUDE_RADIUS_PX, SAMPLES_PER_PT,
)
from tools.replay_calib_log import parse
from robosurge.sensor_fusion import LocalAffineMapper

CLUSTER_RADIUS_PX = 15.0
MIN_SPAN_FRAC = 0.6          # a candidate must appear in >=60% of samples
PREDICT_TOL_PX = 140.0       # candidate must land this close to the prediction
LOO_DROP_ABOVE_CM = 1.5      # prune points worse than this, worst-first
MIN_POINTS = 8


def candidates(samples: list[list[tuple[float, float]]], arm2_anchor: np.ndarray):
    """Persistent blobs for one target, with the parked arm removed."""
    pts, sof = [], []
    for i, dets in enumerate(samples):
        pts.extend(dets)
        sof.extend([i] * len(dets))
    if not pts:
        return [], arm2_anchor
    P = np.array(pts, float)
    S = np.array(sof)

    seeds = []
    for i in range(len(P)):
        m = np.where(np.linalg.norm(P - P[i], axis=1) <= CLUSTER_RADIUS_PX)[0]
        seeds.append((len(set(S[m].tolist())), m))
    seeds.sort(key=lambda t: t[0], reverse=True)

    uniq = []
    for span, m in seeds:
        c = np.median(P[m], axis=0)
        if all(np.linalg.norm(c - u[1]) > CLUSTER_RADIUS_PX for u in uniq):
            uniq.append((span, c))
    if not uniq:
        return [], arm2_anchor

    a2 = min(range(len(uniq)), key=lambda j: np.linalg.norm(uniq[j][1] - arm2_anchor))
    a2_c = uniq[a2][1]
    keep = [(s, c) for j, (s, c) in enumerate(uniq)
            if j != a2 and np.linalg.norm(c - a2_c) > ARM2_EXCLUDE_RADIUS_PX]
    keep = [(s, c) for s, c in keep if s >= MIN_SPAN_FRAC * SAMPLES_PER_PT]
    return keep, a2_c


def fit_phys_to_pixel(phys, pix):
    """RANSAC homography physical cm -> pixel. Falls back to least-squares affine."""
    phys = np.asarray(phys, float)
    pix = np.asarray(pix, float)
    if len(phys) >= 4:
        H, _ = cv2.findHomography(phys.reshape(-1, 1, 2), pix.reshape(-1, 1, 2),
                                  cv2.RANSAC, 25.0)
        if H is not None:
            return lambda p: cv2.perspectiveTransform(
                np.asarray(p, float).reshape(-1, 1, 2), H).reshape(-1, 2)
    A, *_ = np.linalg.lstsq(np.hstack([phys, np.ones((len(phys), 1))]), pix, rcond=None)
    return lambda p: np.hstack([np.asarray(p, float).reshape(-1, 2),
                                np.ones((len(np.atleast_2d(p)), 1))]) @ A


def main() -> None:
    path = Path(sys.argv[1])
    write = "--write" in sys.argv
    baseline, targets = parse(path)
    anchor = np.array(baseline[1], float) if baseline and len(baseline) >= 2 \
        else np.array([0.0, 0.0])

    cands, xy = [], []
    for (tx, ty), samples in targets:
        c, anchor = candidates(samples, anchor)
        cands.append(c)
        xy.append((tx, ty))

    n_amb = sum(1 for c in cands if len(c) > 1)
    n_none = sum(1 for c in cands if not c)
    print(f"{len(targets)} targets: {len(targets)-n_amb-n_none} unambiguous, "
          f"{n_amb} ambiguous, {n_none} with no candidate")

    # Seed on the unambiguous targets only.
    assign: dict[int, np.ndarray] = {
        i: c[0][1] for i, c in enumerate(cands) if len(c) == 1
    }
    print(f"seeded with {len(assign)} unambiguous points")

    for it in range(1, 11):
        idx = sorted(assign)
        predict = fit_phys_to_pixel([xy[i] for i in idx], [assign[i] for i in idx])
        new: dict[int, np.ndarray] = {}
        for i, c in enumerate(cands):
            if not c:
                continue
            want = predict([xy[i]])[0]
            best = min(c, key=lambda sc: np.linalg.norm(sc[1] - want))
            if np.linalg.norm(best[1] - want) <= PREDICT_TOL_PX:
                new[i] = best[1]
        changed = (set(new) != set(assign) or
                   any(np.any(new[k] != assign[k]) for k in new if k in assign))
        assign = new
        print(f"  iter {it}: {len(assign)} points assigned")
        if not changed:
            break

    # Prune remaining outliers worst-first using leave-one-out error.
    idx = sorted(assign)
    phys = [xy[i] for i in idx]
    pix = [tuple(map(float, assign[i])) for i in idx]
    while len(phys) > MIN_POINTS:
        errs = LocalAffineMapper(phys, pix).leave_one_out_errors()
        w = int(np.argmax(errs))
        if errs[w] <= LOO_DROP_ABOVE_CM:
            break
        print(f"  dropping {phys[w]} (LOO {errs[w]:.2f} cm)")
        phys.pop(w)
        pix.pop(w)

    errs = LocalAffineMapper(phys, pix).leave_one_out_errors()
    print(f"\nfinal: {len(phys)} points   "
          f"mean LOO {np.mean(errs):.2f} cm   max LOO {np.max(errs):.2f} cm")
    for (tx, ty), (u, v), e in zip(phys, pix, errs):
        print(f"  ({tx:+6.2f},{ty:+6.2f}) -> ({u:6.1f},{v:6.1f})  err={e:5.2f} cm")

    print("\nCALIBRATION_PHYSICAL_PTS = " + repr([tuple(p) for p in phys]))
    print("CALIBRATION_PIXEL_PTS    = " + repr([tuple(p) for p in pix]))

    if write:
        out = Path("data/calibration/calibration_points.csv")
        out.write_text(
            "target_x,target_y,pixel_u,pixel_v\n"
            + "".join(f"{a},{b},{u},{v}\n" for (a, b), (u, v) in zip(phys, pix))
        )
        print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
