import cv2
import serial
import time

COM_PORT = 'COM6'

print(f"Opening bridge to {COM_PORT}...")
try:
    robot = serial.Serial(COM_PORT, 115200, timeout=1)
    time.sleep(3)
except Exception as e:
    print(f"CRITICAL: Connection failed. {e}")
    exit()

def send_command(arm, x, y, z, delay=0.5):
    cmd = f"{arm} {round(x, 2)} {round(y, 2)} {z}\n"
    print(f"> Sending: {cmd.strip()}")
    robot.write(cmd.encode('utf-8'))
    time.sleep(delay)

print("\nExecuting Dance Sequence...\n")

try:
    # 1. Neutral Position
    send_command("arm1", 12.0, 0.0, 10.0)
    send_command("arm2", 12.0, 0.0, 10.0)
    time.sleep(1)

    # 2. Side to Side (Horizontal Sweep)
    for _ in range(2):
        send_command("arm1", 12.0, 5.0, 10.0, 0.4)
        send_command("arm2", 12.0, -5.0, 10.0, 0.4)
        send_command("arm1", 12.0, -5.0, 10.0, 0.4)
        send_command("arm2", 12.0, 5.0, 10.0, 0.4)

    # 3. The "Peck" (Z-Axis Dip)
    for _ in range(3):
        send_command("arm1", 12.0, 0.0, 4.0, 0.3)
        send_command("arm2", 12.0, 0.0, 4.0, 0.3)
        send_command("arm1", 12.0, 0.0, 10.0, 0.3)
        send_command("arm2", 12.0, 0.0, 10.0, 0.3)

    # 4. Alternating Forward/Back (X-Axis Extension)
    for _ in range(2):
        send_command("arm1", 16.0, 0.0, 10.0, 0.5)
        send_command("arm2", 8.0, 0.0, 10.0, 0.5)
        send_command("arm1", 8.0, 0.0, 10.0, 0.5)
        send_command("arm2", 16.0, 0.0, 10.0, 0.5)

    # 5. Return to Neutral
    send_command("arm1", 12.0, 0.0, 10.0)
    send_command("arm2", 12.0, 0.0, 10.0)
    
    print("\nDance Complete!")

except KeyboardInterrupt:
    print("\nDance Aborted by User.")
finally:
    robot.close()