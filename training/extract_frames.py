"""
extract_frames.py — RoboSurge Phase 2
====================================
Slices the 120-second data collection video into distinct, uncompressed 
images at a fixed rate (1 frame per second) for structural keypoint annotation.
"""

import cv2
import os
import argparse
from pathlib import Path

def extract_frames(video_path: str, output_dir: str, frame_rate_hz: float = 1.0) -> None:
    """
    Parses a video file and saves frames at specified temporal intervals.
    """
    video_path_obj = Path(video_path)
    if not video_path_obj.exists():
        print(f"[ERROR] Video file not found at: {video_path_obj.resolve()}")
        return

    output_path_obj = Path(output_dir)
    output_path_obj.mkdir(parents=True, exist_ok=True)

    # Initialize video capture stream
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    if fps == 0:
        print("[ERROR] Could not read video properties. Verify the video file format.")
        return

    duration = total_frames / fps
    print(f"[INFO] Video loaded successfully:")
    print(f" -> Resolution : {int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}")
    print(f" -> Frame Rate : {fps:.2f} FPS")
    print(f" -> Duration   : {duration:.2f} seconds")
    print(f" -> Target     : Extracting 1 frame every {1.0/frame_rate_hz:.1f} second(s)")

    # Calculate frame step interval
    frame_step = int(round(fps / frame_rate_hz))
    saved_count = 0
    frame_index = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # Extract precisely at the calculated step interval
        if frame_index % frame_step == 0:
            frame_filename = f"frame_{saved_count:04d}.png"
            frame_output_path = output_path_obj / frame_filename
            
            # Save as high-quality PNG to protect edge details for YOLOv8
            cv2.imwrite(str(frame_output_path), frame)
            saved_count += 1

        frame_index += 1

    cap.release()
    print(f"\n[SUCCESS] Extraction complete. Saved {saved_count} frames to: '{output_dir}/'")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RoboSurge Video Frame Extractor")
    parser.add_argument("--video", type=str, default="calibration_video.mp4", help="Path to recorded video file")
    parser.add_argument("--out", type=str, default="dataset_images", help="Target output directory for images")
    parser.add_argument("--hz", type=float, default=1.0, help="Extraction frequency (frames per second)")
    args = parser.parse_args()

    extract_frames(args.video, args.out, args.hz)