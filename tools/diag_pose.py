"""
tools/diag_pose.py — dump every YOLO instance the pose model returns for one
frame, with box confidence and per-keypoint confidence, and write an
annotated image so the tip picks can be eyeballed.

Usage:
    python tools/diag_pose.py live_calib_check.png
"""
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from robosurge.vision_pipeline import PoseTracker

img = sys.argv[1] if len(sys.argv) > 1 else "live_calib_check.png"
frame = cv2.imread(img)
if frame is None:
    sys.exit(f"could not read {img}")

root = Path(__file__).resolve().parents[1]
tracker = PoseTracker(weights_path=root / "models" / "robosurge_pose_best.pt")

for thresh in (0.35, 0.50, 0.70):
    res = tracker.model(frame, conf=thresh, verbose=False)[0]
    print(f"\n=== detection_threshold={thresh} -> {len(res.boxes)} instance(s) ===")
    for i in range(len(res.boxes)):
        box_conf = float(res.boxes[i].conf[0])
        kp = res.keypoints[i].data[0].cpu().numpy()
        kc = res.keypoints[i].conf[0].cpu().numpy()
        names = ["base", "elbow", "wrist", "tip"]
        parts = " ".join(
            f"{n}=({kp[j][0]:.0f},{kp[j][1]:.0f}){kc[j]:.2f}"
            for j, n in enumerate(names)
        )
        print(f"  inst {i}: box_conf={box_conf:.3f}  {parts}")

res = tracker.model(frame, conf=0.35, verbose=False)[0]
out = frame.copy()
for i in range(len(res.boxes)):
    bc = float(res.boxes[i].conf[0])
    kp = res.keypoints[i].data[0].cpu().numpy()
    x1, y1, x2, y2 = map(int, res.boxes[i].xyxy[0])
    cv2.rectangle(out, (x1, y1), (x2, y2), (0, 255, 255), 1)
    cv2.putText(out, f"#{i} {bc:.2f}", (x1, y1 - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
    tx, ty = int(kp[3][0]), int(kp[3][1])
    cv2.circle(out, (tx, ty), 7, (0, 0, 255), -1)
    cv2.putText(out, f"tip{i}", (tx + 9, ty), cv2.FONT_HERSHEY_SIMPLEX,
                0.5, (0, 0, 255), 2)
dst = root / "data" / "calibration" / "pose_debug.png"
cv2.imwrite(str(dst), out)
print(f"\nannotated -> {dst}")
