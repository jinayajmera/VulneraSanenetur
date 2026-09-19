"""
calibrate_via_fk.py — Self-calibrating LOCAL fit (v5)
=============================================================
Pre-hover version (v5): descends all the way to TABLE_Z_CM for calibration.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from robosurge.vision_pipeline import PoseTracker, ArmPoseResult             # noqa: E402
from robosurge.scene_state import TABLE_Z_CM, SAFE_Z_CM, MIN_REACH, MAX_REACH  # noqa: E402
from robosurge.sensor_fusion import LocalAffineMapper                       # noqa: E402

try:
    import serial
    _SERIAL_AVAILABLE = True
except ImportError:
    _SERIAL_AVAILABLE = False

SERIAL_PORT_DEFAULT = "COM5"   # CP210x USB-UART; COM6/COM7 are Bluetooth here
SERIAL_BAUD         = 115200
SERIAL_TIMEOUT      = 0.02

SETTLE_S        = 3.5
SAMPLES_PER_PT  = 7
SAMPLE_GAP_S    = 0.15
BASELINE_SAMPLES = 5

ARM2_HOLD_XY: tuple[float, float] = (10.0, -9.0)
ARM2_TRACK_RADIUS_PX = 50.0

# Everything within this radius of the parked arm is the parked arm. Its
# keypoint jitters by ~40px between frames, which splits it into several
# clusters; removing only the single nearest one leaves a fragment behind that
# can out-vote the real moving arm. The two arms never come within 300px of
# each other in this camera setup, so 150 is safe.
ARM2_EXCLUDE_RADIUS_PX = 150.0

# Keep a little margin off MAX_REACH — the IK saturates near the limit and the
# tip stops tracking the commanded XY, which poisons the fit.
REACH_MARGIN_CM = 1.0

# Grid spans the whole reachable envelope, not just the middle of it. The old
# 5x5 grid topped out at reach=18.0 cm, so every landmark past that was
# extrapolated rather than interpolated — which is where the 60 cm garbage
# coordinates came from. Points outside [MIN_REACH, MAX_REACH-margin] are
# dropped below rather than commanded.
TARGET_GRID_XY: list[tuple[float, float]] = [
    (x, y)
    for x in (5.0, 8.0, 11.0, 14.0, 17.0, 20.0)
    for y in (-9.0, -6.0, -3.0, 0.0, 3.0, 6.0, 9.0)
]

TOPUP_GRID_XY: list[tuple[float, float]] = [
    (x, y)
    for x in (12.0, 13.0)
    for y in (0.0, 3.0, 6.0)
]


def build_cmd(arm_id: int, x: float, y: float, z: float) -> str:
    return f"arm{arm_id} {x:+.2f} {y:+.2f} {z:.2f}\n"


class ArmLink:
    def __init__(self, port: str, dry_run: bool) -> None:
        self.dry_run = dry_run or not _SERIAL_AVAILABLE
        self._ser: Optional["serial.Serial"] = None
        if not self.dry_run:
            try:
                self._ser = serial.Serial(
                    port=port, baudrate=SERIAL_BAUD,
                    timeout=SERIAL_TIMEOUT, write_timeout=SERIAL_TIMEOUT,
                )
                print(f"Serial {port} opened.")
            except serial.SerialException as exc:
                print(f"Could not open {port} ({exc}) — falling back to dry-run.")
                self.dry_run = True

    def send(self, arm_id: int, x: float, y: float, z: float) -> None:
        cmd = build_cmd(arm_id, x, y, z)
        if self.dry_run:
            print(f"  [DRY-RUN] {cmd.strip()}")
            return
        self._ser.write(cmd.encode("ascii"))
        self._ser.flush()

    def close(self) -> None:
        if self._ser and self._ser.is_open:
            self._ser.close()


def detect_all_tips(tracker: PoseTracker) -> list[tuple[float, float]]:
    frame = tracker.grab_frame()
    if frame is None:
        return []
    poses: list[ArmPoseResult] = tracker.process_frame(frame)
    return [(float(p.tip_pixel[0]), float(p.tip_pixel[1]))
            for p in poses if p.tip_pixel is not None]


def capture_baseline(tracker: PoseTracker, n: int, gap_s: float) -> list[tuple[float, float]]:
    all_frames: list[list[tuple[float, float]]] = []
    for _ in range(n):
        all_frames.append(detect_all_tips(tracker))
        time.sleep(gap_s)

    counts = {len(f) for f in all_frames}
    if len(counts) > 1:
        print(f"  WARNING: inconsistent detection count across baseline frames: {counts}. "
              "Using the most common count.")
    target_n = max(counts, key=lambda c: sum(1 for f in all_frames if len(f) == c))
    usable = [f for f in all_frames if len(f) == target_n]

    if target_n == 0:
        print("  WARNING: no arms detected in baseline frames at all.")
        return []

    sorted_frames = [sorted(f, key=lambda p: p[0]) for f in usable]
    baseline = []
    for slot in range(target_n):
        us = [f[slot][0] for f in sorted_frames]
        vs = [f[slot][1] for f in sorted_frames]
        baseline.append((float(np.median(us)), float(np.median(vs))))
    return baseline


def sample_moved_arm(
    tracker: PoseTracker,
    arm2_pos: list[float],
    n: int,
    gap_s: float,
    cluster_radius_px: float = 25.0,
) -> tuple[Optional[tuple[float, float]], bool]:
    # Collect every detection, tagged with the sample it came from. Which
    # blob is arm2 is decided once over the whole batch rather than greedily
    # per sample: a single bad frame used to knock the arm2 anchor loose and
    # strand it for the rest of the run, because the anchor only updated on a
    # match inside ARM2_TRACK_RADIUS_PX and there was no way back.
    pts: list[tuple[float, float]] = []
    sample_of: list[int] = []
    for sample_i in range(n):
        dets = detect_all_tips(tracker)
        print(f"    sample {sample_i+1}/{n}: {len(dets)} detection(s) -> {dets}")
        pts.extend(dets)
        sample_of.extend([sample_i] * len(dets))
        time.sleep(gap_s)

    return pick_moved_arm(pts, sample_of, arm2_pos, n, cluster_radius_px)


def pick_moved_arm(
    pts: list[tuple[float, float]],
    sample_of: list[int],
    arm2_pos: list[float],
    n: int,
    cluster_radius_px: float = 25.0,
) -> tuple[Optional[tuple[float, float]], bool]:
    """
    Decide which blob is the moved arm, given all detections from one target.

    Split out of sample_moved_arm so it can be replayed against logged
    detections without a camera.
    """
    if not pts:
        return None, True

    P = np.array(pts, dtype=np.float64)
    S = np.array(sample_of)

    # Ball cluster seeded on every detection, scored by how many DISTINCT
    # samples it spans. Scoring by raw member count (the old behaviour) made
    # the threshold unreachable: with k blobs visible per sample the real arm
    # can only ever hold 1/(k-1) of the leftovers, so every 3-detection target
    # capped at 33% and was rejected no matter how rock-steady it was.
    seeds: list[tuple[int, np.ndarray]] = []
    for i in range(len(P)):
        m = np.where(np.linalg.norm(P - P[i], axis=1) <= cluster_radius_px)[0]
        seeds.append((len(set(S[m].tolist())), m))
    seeds.sort(key=lambda c: c[0], reverse=True)

    # Collapse overlapping seeds into distinct clusters.
    uniq: list[tuple[int, np.ndarray, np.ndarray]] = []
    for span, m in seeds:
        c = np.median(P[m], axis=0)
        if all(np.linalg.norm(c - u[1]) > cluster_radius_px for u in uniq):
            uniq.append((span, c, m))

    if not uniq:
        return None, False

    # arm2 is parked and never commanded to move, so it is just the cluster
    # nearest the running anchor. Nearest-unconditionally (no hard radius)
    # means the anchor can always re-acquire after a bad frame.
    anchor = np.array(arm2_pos, dtype=np.float64)
    a2 = min(range(len(uniq)), key=lambda j: float(np.linalg.norm(uniq[j][1] - anchor)))
    jump = float(np.linalg.norm(uniq[a2][1] - anchor))
    if jump > ARM2_TRACK_RADIUS_PX:
        print(f"    note: parked-arm anchor moved {jump:.0f}px "
              f"-> ({uniq[a2][1][0]:.0f},{uniq[a2][1][1]:.0f}); re-anchoring.")
    arm2_pos[0], arm2_pos[1] = float(uniq[a2][1][0]), float(uniq[a2][1][1])

    # Drop every cluster near the parked arm, not just the nearest one.
    a2_c = uniq[a2][1]
    rest = sorted(
        (u for j, u in enumerate(uniq)
         if j != a2 and np.linalg.norm(u[1] - a2_c) > ARM2_EXCLUDE_RADIUS_PX),
        key=lambda u: u[0], reverse=True,
    )
    if not rest:
        print("    only the parked arm was visible — no moved arm to sample.")
        return None, False

    span, centroid, _ = rest[0]
    chosen = (float(centroid[0]), float(centroid[1]))

    if span < 0.5 * n:
        print(f"    WARNING: best candidate appears in only {span}/{n} samples "
              "— arm likely wasn't settled. Flagging unreliable.")
        return chosen, False

    # Two equally persistent blobs means we cannot tell the tip from an elbow
    # or a reflection. Guessing here is how a wrong pixel ends up in the fit.
    if len(rest) > 1 and rest[1][0] >= 0.5 * n:
        print(f"    WARNING: two persistent candidates "
              f"({chosen[0]:.0f},{chosen[1]:.0f}) span={span} and "
              f"({rest[1][1][0]:.0f},{rest[1][1][1]:.0f}) span={rest[1][0]} "
              "— cannot tell which is the moved arm. Flagging unreliable.")
        return chosen, False

    return chosen, True


def run(args: argparse.Namespace) -> None:
    grid = TOPUP_GRID_XY if args.topup else TARGET_GRID_XY
    if args.topup:
        print(f"--topup mode: collecting only {len(grid)} new points "
              f"({grid}), will merge into existing calibration_points.csv.")

    # Drop unreachable targets outright. Previously these were only warned
    # about and then still commanded; the IK clamps them, the tip lands
    # somewhere other than the commanded XY, and that false correspondence
    # goes straight into the fit.
    reach_hi = MAX_REACH - REACH_MARGIN_CM
    kept = [(x, y) for x, y in grid if MIN_REACH <= math.hypot(x, y) <= reach_hi]
    dropped = [(x, y) for x, y in grid if (x, y) not in kept]
    if dropped:
        print(f"Dropping {len(dropped)} target(s) outside reach "
              f"[{MIN_REACH}, {reach_hi}] cm: {dropped}")
    grid = kept
    reaches = [math.hypot(x, y) for x, y in grid]
    print(f"Grid: {len(grid)} targets, reach {min(reaches):.1f}–{max(reaches):.1f} cm.")

    # Same CWD-then-models/ search cli.py does, so running this from the repo
    # root finds models/robosurge_pose_best.pt instead of dying on the default.
    if not Path(args.weights).exists():
        candidate = Path(__file__).resolve().parents[1] / "models" / Path(args.weights).name
        if candidate.exists():
            print(f"Weights not in CWD — using {candidate}")
            args.weights = str(candidate)
        else:
            print(f"Weights '{args.weights}' not found in CWD or {candidate.parent}. Aborting.")
            return

    print(f"Loading pose model from {args.weights} ...")
    tracker = PoseTracker(weights_path=args.weights, camera_index=args.cam)
    if not tracker.open_camera():
        print("Could not open camera. Aborting.")
        return

    arm = ArmLink(port=args.port, dry_run=args.dry_run)
    rows: list[dict] = []

    try:
        print(f"\nParking arm2 at {ARM2_HOLD_XY} (held for the whole run)...")
        arm.send(2, ARM2_HOLD_XY[0], ARM2_HOLD_XY[1], SAFE_Z_CM)
        time.sleep(SETTLE_S)

        print("\nCapturing baseline (do not move anything)...")
        baseline = capture_baseline(tracker, BASELINE_SAMPLES, SAMPLE_GAP_S)
        print(f"Baseline tip positions: {baseline}")
        if len(baseline) < 2:
            print("WARNING: expected 2 arms in baseline, got "
                  f"{len(baseline)}. Arm-identification will be less reliable.")

        if len(baseline) >= 2:
            arm2_pos = list(baseline[1])
        elif len(baseline) == 1:
            arm2_pos = list(baseline[0])
        else:
            arm2_pos = [0.0, 0.0]
            print("  WARNING: no baseline detections at all.")

        for i, (tx, ty) in enumerate(grid, start=1):
            print(f"\n[{i}/{len(grid)}] target=({tx:+.2f},{ty:+.2f})")

            arm.send(2, ARM2_HOLD_XY[0], ARM2_HOLD_XY[1], SAFE_Z_CM)
            arm.send(1, tx, ty, SAFE_Z_CM)
            time.sleep(SETTLE_S)
            # v5: descends all the way to TABLE_Z_CM (full contact)
            arm.send(1, tx, ty, TABLE_Z_CM)
            time.sleep(SETTLE_S)

            pixel, reliable = sample_moved_arm(tracker, arm2_pos, SAMPLES_PER_PT, SAMPLE_GAP_S)

            arm.send(1, tx, ty, SAFE_Z_CM)
            time.sleep(0.3)

            if pixel is None:
                print("  Could not confidently identify the moved arm — skipping.")
                continue
            if not reliable:
                print("  Skipping this point — picks didn't agree.")
                continue

            u, v = pixel
            print(f"  -> chosen pixel=({u:.1f},{v:.1f})")
            rows.append({"target_x": tx, "target_y": ty, "pixel_u": u, "pixel_v": v})

        if rows:
            cx = sum(r["target_x"] for r in rows) / len(rows)
            cy = sum(r["target_y"] for r in rows) / len(rows)
            arm.send(1, cx, cy, SAFE_Z_CM)

    except KeyboardInterrupt:
        print("\nInterrupted — retracting to safe height.")
        arm.send(1, 10.0, 0.0, SAFE_Z_CM)
    finally:
        tracker.release_camera()
        arm.close()

    if args.topup:
        existing_csv = Path(args.outdir) / "calibration_points.csv"
        if not existing_csv.exists():
            print(f"\n--topup specified but {existing_csv} doesn't exist.")
            return
        with existing_csv.open(newline="") as fh:
            existing_rows = [
                {"target_x": float(r["target_x"]), "target_y": float(r["target_y"]),
                 "pixel_u": float(r["pixel_u"]), "pixel_v": float(r["pixel_v"])}
                for r in csv.DictReader(fh)
            ]
        print(f"\nLoaded {len(existing_rows)} existing points, "
              f"merging with {len(rows)} new.")
        rows = existing_rows + rows

    if len(rows) < 7:
        print(f"\nOnly {len(rows)} usable points — need at least 7.")
        return

    _save_and_fit(rows, args.outdir)


def _save_and_fit(rows: list[dict], outdir: str) -> None:
    outdir_path = Path(outdir)
    outdir_path.mkdir(parents=True, exist_ok=True)

    csv_path = outdir_path / "calibration_points.csv"
    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["target_x", "target_y", "pixel_u", "pixel_v"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nSaved raw points -> {csv_path}")

    pixel_pts    = [(r["pixel_u"], r["pixel_v"]) for r in rows]
    physical_pts = [(r["target_x"], r["target_y"]) for r in rows]

    try:
        mapper = LocalAffineMapper(physical_pts, pixel_pts)
    except ValueError as exc:
        print(f"Could not build LocalAffineMapper: {exc}")
        return

    errors = mapper.leave_one_out_errors()
    print("\nLeave-one-out error per point (predicted using only the OTHER points):")
    for (tx, ty), err in zip(physical_pts, errors):
        print(f"  target=({tx:+6.2f},{ty:+6.2f})  err={err:5.2f} cm")

    mean_err = sum(errors) / len(errors)
    max_err  = max(errors)
    print(f"\nMean LOO error: {mean_err:.2f} cm   Max LOO error: {max_err:.2f} cm")
    if max_err > 1.5:
        print("  -> Still large. Add more points in the bad region.")

    fit_path = outdir_path / "calibration_fit.json"
    fit_path.write_text(json.dumps({
        "physical_pts": physical_pts,
        "pixel_pts": pixel_pts,
        "mean_loo_error_cm": mean_err,
        "max_loo_error_cm": max_err,
        "n_points": len(rows),
    }, indent=2))
    print(f"Saved fit -> {fit_path}")

    paste_path = outdir_path / "calibration_paste.py"
    paste_path.write_text(
        "# Auto-generated by calibrate_via_fk.py\n"
        "# Paste these into sensor_fusion.py:\n"
        "#   CALIBRATION_PHYSICAL_PTS = " + repr(physical_pts) + "\n"
        "#   CALIBRATION_PIXEL_PTS    = " + repr(pixel_pts) + "\n"
        "#   mapper = LocalAffineMapper(CALIBRATION_PHYSICAL_PTS, CALIBRATION_PIXEL_PTS)\n"
    )
    print(f"Saved paste-ready snippet -> {paste_path}")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Self-calibrating FK<->vision local-affine fit.")
    p.add_argument("--port", default=SERIAL_PORT_DEFAULT)
    p.add_argument("--cam", default=1)
    p.add_argument("--weights", default="robosurge_pose_best.pt")
    p.add_argument("--outdir", default="data/calibration")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--topup", action="store_true")
    args = p.parse_args()
    try:
        args.cam = int(args.cam)
    except ValueError:
        pass
    return args


if __name__ == "__main__":
    run(_parse_args())