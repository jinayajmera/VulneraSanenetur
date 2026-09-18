
import cv2
cap = cv2.VideoCapture(1)
ret, frame = cap.read()
cv2.imwrite('calibration_frame.png', frame)
cap.release()
print('Saved calibration_frame.png')
