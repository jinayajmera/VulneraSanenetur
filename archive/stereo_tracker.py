"""
RoboSurge Phase 2 — Dual-Camera ArUco Tracker

Camera setup:
  Phone 1 (top-down)  → sees markers on TOP of arm segments
  Phone 2 (front)     → sees markers on FRONT FACE of arm panels

Marker IDs:
  0  = table reference (workspace board centre)
  1  = arm 1 tip — TOP face
  2  = arm 2 tip — TOP face
  11 = arm 1 tip — FRONT face  (print separately, same physical tip)
  12 = arm 2 tip — FRONT face

Logic:
  - Top-down cam tracks IDs 1,2 when arms are upright
  - Front cam tracks IDs 11,12 when arms are bent down
  - Z: top-down gives XY, front gives Z height
  - Best available source wins per frame

Usage:
  python stereo_tracker.py --cam0 http://IP:8080/video --cam1 http://IP:8080/video
  python stereo_tracker.py --test
"""

import cv2
import cv2.aruco as aruco
import numpy as np
import argparse
import threading
import time
import json
import sys
from dotenv import load_dotenv
load_dotenv()

# ============================================================
# CONSTANTS — match procedure_agent.py
# ============================================================
BASE_HEIGHT    = 7.5
TABLE_Z        = BASE_HEIGHT
MARKER_SIZE_CM = 3.0   # measure your printed marker and update this

ARUCO_DICT   = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
ARUCO_PARAMS = aruco.DetectorParameters()

# Marker ID assignments
TABLE_ID      = 0
ARM1_TOP_ID   = 1
ARM2_TOP_ID   = 2
ARM1_FRONT_ID = 1  # same marker as top, used on front face too
ARM2_FRONT_ID = 2

# ============================================================
# THREADED CAMERA STREAM
# ============================================================
class CameraStream:
    def __init__(self, src, name: str):
        self.src     = src
        self.name    = name
        self.frame   = None
        self.lock    = threading.Lock()
        self.running = False
        self.cap     = None

    def start(self) -> bool:
        self.cap = cv2.VideoCapture(self.src)
        if not self.cap.isOpened():
            print(f"[error] Cannot open {self.name}: {self.src}")
            return False
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.running = True
        threading.Thread(target=self._grab, daemon=True).start()
        time.sleep(0.5)
        print(f"[cam] {self.name} connected")
        return True

    def _grab(self):
        while self.running:
            ret, frame = self.cap.read()
            if ret:
                with self.lock:
                    self.frame = frame

    def read(self):
        with self.lock:
            return self.frame.copy() if self.frame is not None else None

    def stop(self):
        self.running = False
        if self.cap:
            self.cap.release()

# ============================================================
# ARUCO DETECTION
# ============================================================
def detect(frame):
    if frame is None:
        return None, None
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    detector = aruco.ArucoDetector(ARUCO_DICT, ARUCO_PARAMS)
    corners, ids, _ = detector.detectMarkers(gray)
    return corners, ids

def marker_centre(corners, ids, marker_id: int):
    if ids is None: return None
    flat = ids.flatten()
    if marker_id not in flat: return None
    idx = list(flat).index(marker_id)
    return corners[idx][0].mean(axis=0)  # (px_x, px_y)

def marker_width_px(corners, ids, marker_id: int):
    if ids is None: return None
    flat = ids.flatten()
    if marker_id not in flat: return None
    idx = list(flat).index(marker_id)
    c = corners[idx][0]
    return ((np.linalg.norm(c[1]-c[0]) + np.linalg.norm(c[2]-c[3])) / 2.0)

# ============================================================
# PER-CAMERA CALIBRATION (uses table marker ID 0)
# ============================================================
class CamCal:
    def __init__(self, name):
        self.name       = name
        self.px_per_cm  = None
        self.origin_px  = None
        self.calibrated = False

    def update(self, corners, ids):
        w = marker_width_px(corners, ids, TABLE_ID)
        c = marker_centre(corners, ids, TABLE_ID)
        if w and c is not None and w > 10:
            self.px_per_cm  = w / MARKER_SIZE_CM
            self.origin_px  = c
            self.calibrated = True

    def to_cm(self, px_pt):
        if not self.calibrated: return None
        dx = (px_pt[0] - self.origin_px[0]) / self.px_per_cm
        dy = (px_pt[1] - self.origin_px[1]) / self.px_per_cm
        return (round(dx, 2), round(dy, 2))

# ============================================================
# POSE TRACKER
# ============================================================
class ArmPose:
    def __init__(self):
        self.x       = None
        self.y       = None
        self.z       = None
        self.visible = False
        self.source  = ""

    def to_dict(self):
        return {"x": self.x, "y": self.y, "z": self.z,
                "visible": self.visible, "source": self.source}

class DualCamTracker:
    def __init__(self, cam_top: CameraStream, cam_front: CameraStream | None):
        self.cam_top   = cam_top
        self.cam_front = cam_front
        self.cal_top   = CamCal("front")
        self.cal_front = CamCal("top-down")
        self.arm1      = ArmPose()
        self.arm2      = ArmPose()
        # Raw frames for display
        self.frame_top   = None
        self.frame_front = None
        self.det_top     = (None, None)
        self.det_front   = (None, None)

    def update(self):
        # Grab
        ft = self.cam_top.read()
        ff = self.cam_front.read() if self.cam_front else None
        self.frame_top, self.frame_front = ft, ff

        ct, it = detect(ft)
        cf, if_ = detect(ff)
        self.det_top   = (ct, it)
        self.det_front = (cf, if_)

        # Calibrate both cams from table marker
        if ct is not None: self.cal_top.update(ct, it)
        if cf is not None: self.cal_front.update(cf, if_)

        # Update each arm
        self._update_arm(self.arm1, ARM1_TOP_ID, ARM1_FRONT_ID, ct, it, cf, if_)
        self._update_arm(self.arm2, ARM2_TOP_ID, ARM2_FRONT_ID, ct, it, cf, if_)

        return self.arm1, self.arm2

    def _update_arm(self, arm: ArmPose,
                    top_id: int, front_id: int,
                    ct, it, cf, if_):
        # Detect in each camera
        px_top   = marker_centre(ct, it, top_id)
        px_front = marker_centre(cf, if_, front_id)

        arm.visible = (px_top is not None) or (px_front is not None)
        if not arm.visible:
            arm.source = ""
            return

        sources = []

        # XY — top-down camera is best for XY (looking straight down)
        if px_top is not None and self.cal_top.calibrated:
            xy = self.cal_top.to_cm(px_top)
            if xy:
                arm.x = xy[0]
                arm.y = xy[1]
                sources.append("top→XY")

        # Z — front camera vertical pixel = height
        # When arm bends down, front camera sees it; top-down loses it
        if px_front is not None and self.cal_front.calibrated:
            # Vertical pixel offset from table marker = Z offset
            dz = (self.cal_front.origin_px[1] - px_front[1]) / self.cal_front.px_per_cm
            arm.z = round(TABLE_Z + dz, 2)
            sources.append("front→Z")

            # If top-down lost XY, estimate from front cam horizontal
            if px_top is None and self.cal_front.calibrated:
                xy_f = self.cal_front.to_cm(px_front)
                if xy_f:
                    arm.x = xy_f[0]
                    sources.append("front→XY(fallback)")

        # Z fallback from top-down if front not available
        elif px_top is not None and self.cal_top.calibrated:
            # From top-down we can't get Z directly, use IK estimate
            # (Z will be None until front camera sees the arm)
            pass

        arm.source = " | ".join(sources)

    # --------------------------------------------------------
    # DISPLAY
    # --------------------------------------------------------
    def draw(self, frame, corners, ids, cal: CamCal,
             cam_label: str, arm1: ArmPose, arm2: ArmPose):
        if frame is None:
            return None
        out = frame.copy()

        if corners is not None and ids is not None:
            aruco.drawDetectedMarkers(out, corners, ids)
            labels = {
                TABLE_ID: "TABLE REF",
                1:        "ARM1",
                2:        "ARM2",
            }
            for i, mid in enumerate(ids.flatten()):
                c = corners[i][0]
                cx, cy = c.mean(axis=0).astype(int)
                cv2.putText(out, labels.get(mid, f"ID{mid}"),
                           (cx-35, cy-12), cv2.FONT_HERSHEY_SIMPLEX,
                           0.55, (0,255,0), 2)
                if cal.calibrated:
                    xy = cal.to_cm((cx, cy))
                    if xy:
                        cv2.putText(out, f"({xy[0]:.1f},{xy[1]:.1f})cm",
                                   (cx-35, cy+18), cv2.FONT_HERSHEY_SIMPLEX,
                                   0.45, (255,255,0), 1)

        # Status
        cal_txt = f"CAL {cal.px_per_cm:.1f}px/cm" if cal.calibrated else "Needs ID 0 in frame"
        cv2.putText(out, f"{cam_label} | {cal_txt}", (10, 28),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.65,
                   (0,255,0) if cal.calibrated else (0,80,255), 2)

        # Arm poses
        y = 58
        for label, arm in [("ARM1", arm1), ("ARM2", arm2)]:
            if arm.visible:
                x_s = f"{arm.x:.1f}" if arm.x is not None else "?"
                y_s = f"{arm.y:.1f}" if arm.y is not None else "?"
                z_s = f"{arm.z:.1f}" if arm.z is not None else "?"
                cv2.putText(out,
                    f"{label}: x={x_s} y={y_s} z={z_s}",
                    (10, y), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (0,255,255), 2)
                y += 28

        return cv2.resize(out, (640, 360))

# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cam0", default="0",
                        help="Top-down phone. '0'=webcam or http://IP:8080/video")
    parser.add_argument("--cam1", default=None,
                        help="Front phone. http://IP:8080/video")
    parser.add_argument("--test", action="store_true",
                        help="Single webcam test mode")
    args = parser.parse_args()

    if args.test:
        args.cam0 = "0"
        args.cam1 = None
        print("[test] Single webcam mode — point at table marker ID 0 to calibrate")

    src0 = int(args.cam0) if str(args.cam0).isdigit() else args.cam0
    cam_top = CameraStream(src0, "front")
    if not cam_top.start():
        sys.exit(1)

    cam_front = None
    if args.cam1:
        cam_front = CameraStream(args.cam1, "top-down")
        if not cam_front.start():
            print("[warn] Front camera failed — single cam mode")
            cam_front = None

    tracker = DualCamTracker(cam_top, cam_front)

    print("\n╔══════════════════════════════════════╗")
    print("║  RoboSurge Phase 2 — Arm Tracker    ║")
    print("╚══════════════════════════════════════╝")
    print("Controls: Q=quit  S=print poses  C=cal status")
    print("Place table marker ID 0 in both camera views first.\n")

    last_print = 0

    try:
        while True:
            arm1, arm2 = tracker.update()

            # Draw top-down view
            ct, it = tracker.det_top
            vis_top = tracker.draw(tracker.frame_top, ct, it,
                                   tracker.cal_top, "Phone 2 (front)",
                                   arm1, arm2)
            if vis_top is not None:
                cv2.imshow("Top-Down Camera", vis_top)

            # Draw front view
            if cam_front:
                cf, if_ = tracker.det_front
                vis_front = tracker.draw(tracker.frame_front, cf, if_,
                                         tracker.cal_front, "Phone 1 (top-down)",
                                         arm1, arm2)
                if vis_front is not None:
                    cv2.imshow("Front Camera", vis_front)

            # Terminal output ~2Hz
            now = time.time()
            if now - last_print > 0.5:
                last_print = now
                parts = []
                for label, arm in [("ARM1", arm1), ("ARM2", arm2)]:
                    if arm.visible:
                        parts.append(
                            f"{label}=(x={arm.x},y={arm.y},z={arm.z})"
                            f"[{arm.source}]"
                        )
                if parts:
                    print(f"\r[pose] {'  |  '.join(parts)}    ", end="")

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('s'):
                out = {
                    "arm1": arm1.to_dict(),
                    "arm2": arm2.to_dict()
                }
                print(f"\n{json.dumps(out, indent=2)}")
            elif key == ord('c'):
                t = tracker.cal_top
                f = tracker.cal_front
                print(f"\n[cal] top  : {'OK '+str(round(t.px_per_cm,1))+' px/cm' if t.calibrated else 'NOT calibrated'}")
                print(f"[cal] front: {'OK '+str(round(f.px_per_cm,1))+' px/cm' if f.calibrated else 'NOT calibrated'}")

            time.sleep(0.033)  # ~30Hz

    except KeyboardInterrupt:
        pass

    cam_top.stop()
    if cam_front: cam_front.stop()
    cv2.destroyAllWindows()
    print("\n[tracker] Stopped.")

if __name__ == "__main__":
    main()