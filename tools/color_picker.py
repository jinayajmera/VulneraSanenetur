"""
tools/color_picker.py — Interactive Frame & Color Inspector
============================================================
Allows you to click on any point or drag a box across a camera frame / saved image
to inspect BGR & HSV color values and generate copy-pasteable LandmarkConfig thresholds.

Usage:
    # Live camera:
    python tools/color_picker.py --cam 1

    # Saved image:
    python tools/color_picker.py --image data/calibration/calibration_frame.png
"""

import argparse
import cv2
import numpy as np


def main():
    parser = argparse.ArgumentParser(description="Sample colors and HSV ranges from camera or image.")
    parser.add_argument("--cam", type=int, default=1, help="Camera index (default 1)")
    parser.add_argument("--image", type=str, default="", help="Path to saved image file")
    args = parser.parse_args()

    if args.image:
        frame = cv2.imread(args.image)
        if frame is None:
            print(f"Error: Could not read image '{args.image}'")
            return
        cap = None
    else:
        cap = cv2.VideoCapture(args.cam)
        if not cap.isOpened():
            print(f"Error: Could not open camera {args.cam}")
            return
        ret, frame = cap.read()
        if not ret:
            print("Error: Could not grab frame from camera")
            return

    blurred = cv2.GaussianBlur(frame, (5, 5), 0)
    hsv_frame = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)

    display_img = frame.copy()
    window_name = "RoboSurge Color Inspector (Click or Drag to Sample, 'q' to exit)"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

    drag_start = None

    def mouse_callback(event, x, y, flags, param):
        nonlocal drag_start, display_img
        h, w, _ = frame.shape
        x = max(0, min(x, w - 1))
        y = max(0, min(y, h - 1))

        if event == cv2.EVENT_LBUTTONDOWN:
            drag_start = (x, y)

        elif event == cv2.EVENT_MOUSEMOVE and drag_start is not None:
            display_img = frame.copy()
            cv2.rectangle(display_img, drag_start, (x, y), (0, 255, 0), 2)
            cv2.imshow(window_name, display_img)

        elif event == cv2.EVENT_LBUTTONUP:
            if drag_start is not None:
                x0, y0 = drag_start
                x1, y1 = x, y
                xmin, xmax = min(x0, x1), max(x0, x1)
                ymin, ymax = min(y0, y1), max(y0, y1)

                if (xmax - xmin) < 3 and (ymax - ymin) < 3:
                    xmin = max(0, x - 2)
                    xmax = min(w - 1, x + 2)
                    ymin = max(0, y - 2)
                    ymax = min(h - 1, y + 2)

                patch_bgr = frame[ymin:ymax+1, xmin:xmax+1]
                patch_hsv = hsv_frame[ymin:ymax+1, xmin:xmax+1]

                mean_bgr = patch_bgr.mean(axis=(0, 1)).astype(int)
                mean_hsv = patch_hsv.mean(axis=(0, 1)).astype(int)
                min_hsv = patch_hsv.min(axis=(0, 1))
                max_hsv = patch_hsv.max(axis=(0, 1))

                # Suggested bounds with ±10 Hue tolerance, ±30 Sat/Val tolerance
                h_lo = int(max(0, min_hsv[0] - 10))
                h_hi = int(min(179, max_hsv[0] + 10))
                s_lo = int(max(40, min_hsv[1] - 30))
                s_hi = int(min(255, max_hsv[1] + 30))
                v_lo = int(max(40, min_hsv[2] - 30))
                v_hi = int(min(255, max_hsv[2] + 30))

                print("\n" + "=" * 60)
                print(f"Region: X=[{xmin}, {xmax}], Y=[{ymin}, {ymax}]  (Center: u={int((xmin+xmax)/2)}, v={int((ymin+ymax)/2)})")
                print(f"BGR Mean : [B={mean_bgr[0]}, G={mean_bgr[1]}, R={mean_bgr[2]}]")
                print(f"HSV Mean : [H={mean_hsv[0]}, S={mean_hsv[1]}, V={mean_hsv[2]}]")
                print(f"HSV Span : Min=[{min_hsv[0]}, {min_hsv[1]}, {min_hsv[2]}] -> Max=[{max_hsv[0]}, {max_hsv[1]}, {max_hsv[2]}]")
                print("-" * 60)
                print("Suggested LandmarkConfig bounds (paste into landmark_detector.py):")
                print(f"  hsv_lower = np.array([{h_lo}, {s_lo}, {v_lo}])")
                print(f"  hsv_upper = np.array([{h_hi}, {s_hi}, {v_hi}])")
                print("=" * 60)

                display_img = frame.copy()
                cv2.rectangle(display_img, (xmin, ymin), (xmax, ymax), (0, 0, 255), 2)
                cv2.putText(
                    display_img,
                    f"H:{mean_hsv[0]} S:{mean_hsv[1]} V:{mean_hsv[2]}",
                    (xmin, max(20, ymin - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 255, 0),
                    2,
                )
                cv2.imshow(window_name, display_img)
                drag_start = None

    cv2.setMouseCallback(window_name, mouse_callback)
    cv2.imshow(window_name, display_img)

    print("\nClick or drag a rectangle over any colored fiducial in the window.")
    print("Press 's' to grab a new live frame (if using camera), or 'q' / ESC to exit.\n")

    while True:
        key = cv2.waitKey(30) & 0xFF
        if key in (ord('q'), 27):
            break
        elif key == ord('s') and cap is not None:
            ret, frame = cap.read()
            if ret:
                blurred = cv2.GaussianBlur(frame, (5, 5), 0)
                hsv_frame = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)
                display_img = frame.copy()
                cv2.imshow(window_name, display_img)
                print("Captured new live frame.")

    if cap is not None:
        cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
