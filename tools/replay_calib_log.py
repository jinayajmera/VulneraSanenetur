"""
tools/replay_calib_log.py — replay a calibration run's logged detections
through the point-acceptance logic, with no camera and no robot.

Paste the console output of calibrate_via_fk.py into a file and point this at
it.  It re-runs pick_moved_arm() over the same detections the live run saw, so
a change to the acceptance logic can be checked against real data instead of
being re-tested on the hardware.

Usage:
    python tools/replay_calib_log.py logs/calib_run.txt
"""
import ast
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.calibrate_via_fk import pick_moved_arm, SAMPLES_PER_PT

TARGET_RE = re.compile(r"^\[(\d+)/(\d+)\] target=\(([-+0-9.]+),([-+0-9.]+)\)")
SAMPLE_RE = re.compile(r"^\s+sample \d+/\d+: \d+ detection\(s\) -> (\[.*\])\s*$")
BASELINE_RE = re.compile(r"^Baseline tip positions: (\[.*\])\s*$")


def parse(path: Path):
    """Yield (target_xy, [detections per sample]) plus the baseline list."""
    baseline, targets, cur = None, [], None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if (mb := BASELINE_RE.match(line)):
            baseline = ast.literal_eval(mb.group(1))
        elif (mt := TARGET_RE.match(line)):
            cur = ((float(mt.group(3)), float(mt.group(4))), [])
            targets.append(cur)
        elif (ms := SAMPLE_RE.match(line)) and cur is not None:
            cur[1].append([tuple(p) for p in ast.literal_eval(ms.group(1))])
    return baseline, targets


def main() -> None:
    path = Path(sys.argv[1])
    baseline, targets = parse(path)
    if not targets:
        sys.exit(f"no targets parsed from {path}")
    print(f"parsed {len(targets)} targets from {path}, baseline={baseline}")

    arm2 = list(baseline[1]) if baseline and len(baseline) >= 2 else [0.0, 0.0]
    accepted = 0
    rows = []
    for (tx, ty), samples in targets:
        pts, sof = [], []
        for i, dets in enumerate(samples):
            pts.extend(dets)
            sof.extend([i] * len(dets))
        pixel, ok = pick_moved_arm(pts, sof, arm2, SAMPLES_PER_PT)
        flag = "ACCEPT" if ok else "reject"
        if ok:
            accepted += 1
            rows.append((tx, ty, pixel[0], pixel[1]))
        loc = f"({pixel[0]:6.1f},{pixel[1]:6.1f})" if pixel else "     --      "
        print(f"  target=({tx:+6.2f},{ty:+6.2f})  {flag}  {loc}")

    print(f"\naccepted {accepted}/{len(targets)}")
    if rows:
        print("\ntarget_x,target_y,pixel_u,pixel_v")
        for r in rows:
            print(f"{r[0]},{r[1]},{r[2]},{r[3]}")


if __name__ == "__main__":
    main()
