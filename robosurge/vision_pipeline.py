"""
vision_pipeline.py — RoboSurge Phase 2 (Multi-Arm Ready)
========================================================
Deep Learning-based pose tracker using YOLOv8-pose.
Updated to support 4 keypoints and MULTIPLE arms in a single frame.
"""

import cv2
import numpy as np
import logging
from dataclasses import dataclass
from pathlib import Path

try:
    from ultralytics import YOLO
    _ULTRALYTICS_AVAILABLE = True
except ImportError:
    _ULTRALYTICS_AVAILABLE = False
    YOLO = None 

logger = logging.getLogger("VisionPipeline")

@dataclass
class ArmPoseResult:
    """Stores pixel coordinates (u, v) for the detected joints."""
    base_pixel: tuple[int, int] | None
    elbow_pixel: tuple[int, int] | None
    wrist_pixel: tuple[int, int] | None
    tip_pixel: tuple[int, int] | None

class PoseTracker:
    def __init__(self, weights_path: str | Path = "robosurge_pose_best.pt", camera_index: int | str = 1):
        self.weights_path = Path(weights_path)
        self.camera_index = camera_index
        self.cap = None
        self.conf_threshold = 0.60  # keypoints confirmed at 0.78-0.90
        self.detection_threshold = 0.35  # lowered — arms confirmed at conf=0.79/0.77

        if not _ULTRALYTICS_AVAILABLE:
            raise ImportError("Ultralytics is not installed. Run: pip install ultralytics")

        logger.info("Loading YOLO model from: %s", self.weights_path)
        try:
            self.model = YOLO(str(self.weights_path))
        except Exception as e:
            logger.error("Failed to load YOLO model: %s", e)
            raise

    def open_camera(self) -> bool:
        if self.cap is not None and self.cap.isOpened():
            return True
        
        logger.info("Opening Camera Feed: %s...", self.camera_index)
        self.cap = cv2.VideoCapture(self.camera_index)
        
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        self.cap.set(cv2.CAP_PROP_FPS, 30)

        if not self.cap.isOpened():
            logger.error("Could not open camera stream: %s.", self.camera_index)
            return False
            
        logger.info("Camera online.")
        return True

    def release_camera(self):
        if self.cap is not None:
            self.cap.release()
            logger.info("Camera released.")

    def grab_frame(self) -> np.ndarray | None:
        if self.cap is None or not self.cap.isOpened():
            return None
        ret, frame = self.cap.read()
        return frame if ret else None

    # UPDATED: Now returns a LIST of poses instead of just one
    def process_frame(self, frame: np.ndarray | None) -> list[ArmPoseResult]:
        if frame is None or frame.size == 0:
            return []

        results = self.model(frame, conf=self.detection_threshold, verbose=False)

        if not results or len(results[0].boxes) == 0:
            return []

        detected_arms = []
        
        # LOOP through every detected arm instead of grabbing just the best one
        for i in range(len(results[0].boxes)):
            keypoints = results[0].keypoints[i]
            
            if keypoints is None or not hasattr(keypoints, 'data') or len(keypoints.data[0]) < 4:
                continue

            kpts = keypoints.data[0].cpu().numpy()
            confs = keypoints.conf[0].cpu().numpy()

            base_px = tuple(map(int, kpts[0][:2])) if confs[0] > self.conf_threshold else None
            elbow_px = tuple(map(int, kpts[1][:2])) if confs[1] > self.conf_threshold else None
            wrist_px = tuple(map(int, kpts[2][:2])) if confs[2] > self.conf_threshold else None
            tip_px = tuple(map(int, kpts[3][:2])) if confs[3] > self.conf_threshold else None

            detected_arms.append(ArmPoseResult(base_pixel=base_px, elbow_pixel=elbow_px, wrist_pixel=wrist_px, tip_pixel=tip_px))

        return detected_arms

    # UPDATED: Now accepts a list of poses to draw multiple skeletons
    def draw_pose(self, frame: np.ndarray, poses: list[ArmPoseResult]) -> np.ndarray:
        annotated = frame.copy()
        colors = [(0, 0, 255), (0, 165, 255), (255, 255, 0), (0, 255, 0)] 
        labels = ["Base", "Elbow", "Wrist", "Tip"]

        for pose in poses:
            pts = [pose.base_pixel, pose.elbow_pixel, pose.wrist_pixel, pose.tip_pixel]
            
            for i in range(len(pts) - 1):
                if pts[i] and pts[i+1]:
                    cv2.line(annotated, pts[i], pts[i+1], (255, 255, 255), 2, cv2.LINE_AA)

            for i, pt in enumerate(pts):
                if pt:
                    cv2.circle(annotated, pt, 6, colors[i], -1)
                    cv2.putText(annotated, labels[i], (pt[0] + 10, pt[1] - 10), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, colors[i], 1, cv2.LINE_AA)

        return annotated

# ---------------------------------------------------------------------------
# Standalone Testing Block
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    weights = sys.argv[1] if len(sys.argv) > 1 else "robosurge_pose_best.pt"
    
    # Safely handle command line arguments
    if len(sys.argv) > 2:
        try:
            cam_source = int(sys.argv[2])
        except ValueError:
            cam_source = sys.argv[2]
    else:
        cam_source = 1  # Defaults to Camo Studio over USB!

    tracker = PoseTracker(weights_path=weights, camera_index=cam_source)
    if tracker.open_camera():
        logger.info("Press 'q' to quit.")
        try:
            while True:
                frame = tracker.grab_frame()
                if frame is None:
                    continue

                poses = tracker.process_frame(frame)
                annotated = tracker.draw_pose(frame, poses)

                # Dynamically print coordinates for every arm found
                for i, pose in enumerate(poses):
                    tip = pose.tip_pixel
                    tip_str = f"({tip[0]}, {tip[1]})" if tip else "OCCLUDED"
                    y_offset = 30 + (i * 30) # Stack the text vertically
                    cv2.putText(annotated, f"Arm {i+1} Tip: {tip_str}", (15, y_offset),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 0), 2)

                cv2.imshow("RoboSurge Vision Pipeline", annotated)
                
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
        except KeyboardInterrupt:
            pass
        finally:
            tracker.release_camera()
            cv2.destroyAllWindows()