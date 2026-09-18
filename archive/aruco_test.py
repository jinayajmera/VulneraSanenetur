"""
Simple ArUco debug viewer — green box over every detected marker.
Usage:
  python aruco_debug.py --cam http://IP:8080/video
  python aruco_debug.py --cam 0   (laptop webcam)
"""
import cv2
import cv2.aruco as aruco
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--cam", default="0")
args = parser.parse_args()

src = int(args.cam) if args.cam.isdigit() else args.cam
cap = cv2.VideoCapture(src)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

d = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
p = aruco.DetectorParameters()
detector = aruco.ArucoDetector(d, p)

print("Running — press Q to quit")

while True:
    ret, frame = cap.read()
    if not ret:
        continue

    gray = cv2.equalizeHist(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
    corners, ids, _ = detector.detectMarkers(gray)

    if ids is not None:
        for i, corner in enumerate(corners):
            pts = corner[0].astype(int)
            # Green box
            cv2.polylines(frame, [pts], True, (0, 255, 0), 3)
            # ID label
            cx, cy = pts.mean(axis=0).astype(int)
            cv2.putText(frame, f"ID {ids[i][0]}", (cx-20, cy),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,255,0), 2)
        cv2.putText(frame, f"Detected: {len(ids)}", (10, 30),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,255,0), 2)
    else:
        cv2.putText(frame, "No markers detected", (10, 30),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,0,255), 2)

    cv2.imshow("ArUco Debug", cv2.resize(frame, (800, 450)))
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()