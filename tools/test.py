
import cv2, numpy as np
cap = cv2.VideoCapture(1)
ret, frame = cap.read()
cap.release()
blurred = cv2.GaussianBlur(frame, (5,5), 0)
hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)

configs = {
    'landmark_A YELLOW': (np.array([20,100,100]), np.array([35,255,255])),
    'landmark_B CYAN':   (np.array([80,100, 80]), np.array([100,255,255])),
    'landmark_C BLUE':   (np.array([105, 60, 60]), np.array([135,255,255])),
}
for name, (lo, hi) in configs.items():
    mask = cv2.inRange(hsv, lo, hi)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(5,5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)
    cnts,_ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    print(f'\n{name}:')
    for c in cnts:
        area = cv2.contourArea(c)
        if area < 50: continue
        p = cv2.arcLength(c, True)
        circ = (4*3.14159*area)/(p**2) if p>0 else 0
        M = cv2.moments(c)
        cx = M['m10']/M['m00'] if M['m00']>0 else 0
        cy = M['m01']/M['m00'] if M['m00']>0 else 0
        in_b = 200<=cx<=1100 and 150<=cy<=700
        passes = area>=100 and area<=3000 and circ>=0.40 and in_b
        print(f'  area={area:.0f} circ={circ:.2f} px=({cx:.0f},{cy:.0f}) bounds={in_b} -> {"PASS" if passes else "FAIL"}')
