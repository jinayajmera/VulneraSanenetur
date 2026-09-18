"""
generate_training_movements.py — RoboSurge Phase 2 (DUAL ARM EDITION)
=====================================================================
Automated calibration and training data trajectory generator. Runs a smooth, 
continuous 3D kinematic sweep for exactly 120 seconds for BOTH arms.
Includes phase-shifting to prevent mid-air mechanical collisions.
"""

import argparse
import math
import sys
import time
import serial
import serial.tools.list_ports

# ─── ROBOT GEOMETRIC BOUNDS ────────────────────────────────────────────────
L1 = 9.5          # Shoulder to elbow (cm)
L2 = 12.0         # Elbow to tip (cm)
BASE_HEIGHT = 7.5 # Table surface offset (cm)
MAX_REACH = 20.0  # Kept slightly under 21.5cm physical limit for safety margin
MIN_REACH = 5.0   # Kept slightly above 2.5cm physical limit to prevent self-collision
MIN_Z = 8.5       # 1cm above the table surface
MAX_Z = 22.0      # High vertical clearance reach

def generate_sweep_coordinates(elapsed_time: float, phase_offset: float = 0.0) -> tuple[float, float, float]:
    """
    Uses independent sinusoidal frequencies to generate a smooth, continuous path.
    The phase_offset allows multiple arms to run the same trajectory out-of-sync.
    """
    t = elapsed_time + phase_offset

    # 1. Radial Reach (In/Out) - Period ~ 11 seconds
    r_freq = 2 * math.pi / 11.0
    r_center = (MAX_REACH + MIN_REACH) / 2.0
    r_amplitude = (MAX_REACH - MIN_REACH) / 2.0
    r = r_center + r_amplitude * math.sin(r_freq * t)

    # 2. Base Pan Angle (Left/Right Sweep) - Period ~ 17 seconds
    pan_freq = 2 * math.pi / 17.0
    pan_angle = math.radians(45.0) * math.sin(pan_freq * t)

    # 3. Vertical Reach (Z Height) - Period ~ 7 seconds
    z_freq = 2 * math.pi / 7.0
    z_center = (MAX_Z + MIN_Z) / 2.0
    z_amplitude = (MAX_Z - MIN_Z) / 2.0
    z = z_center + z_amplitude * math.cos(z_freq * t)

    # Convert cylindrical coordinates to Cartesian workspace coordinates
    x = r * math.cos(pan_angle)
    y = r * math.sin(pan_angle)
    
    return round(x, 3), round(y, 3), round(z, 3)

def main() -> None:
    parser = argparse.ArgumentParser(description="RoboSurge Dual-Arm Trajectory Generator")
    parser.add_argument("--port", type=str, default=None, help="ESP32 Serial Port (e.g., COM6 or /dev/ttyUSB0)")
    parser.add_argument("--baud", type=int, default=115200, help="Serial baud rate")
    parser.add_argument("--duration", type=int, default=120, help="Total runtime in seconds")
    parser.add_argument("--rate", type=int, default=15, help="Update frequency in Hz")
    args = parser.parse_args()

    port = args.port
    if not port:
        ports = list(serial.tools.list_ports.comports())
        if ports:
            port = ports[0].device
        else:
            print("[ERROR] No serial ports discovered. Run with --port specifying your ESP32 device.")
            sys.exit(1)

    print(f"[INIT] Connecting to ESP32 on {port} at {args.baud} baud...")
    try:
        ser = serial.Serial(port, args.baud, timeout=1)
        time.sleep(2)  
    except Exception as e:
        print(f"[ERROR] Failed to open serial connection: {e}")
        sys.exit(1)

    print(f"\n{'─'*60}\nROBOSURGE DATA COLLECTION: DUAL ARM SWEEP\n{'─'*60}")
    print(f" -> Execution Duration : {args.duration} seconds")
    print(" -> Action Required    : Start your video camera recording NOW.")
    
    for countdown in range(5, 0, -1):
        print(f"Starting movement generation in {countdown}... ", end="\r")
        time.sleep(1)
        
    start_time = time.time()
    end_time = start_time + args.duration
    interval = 1.0 / args.rate

    try:
        while time.time() < end_time:
            t0 = time.time()
            elapsed = t0 - start_time

            # Generate coordinates (Arm 2 is offset by 5.5 seconds so they move in opposition)
            x1, y1, z1 = generate_sweep_coordinates(elapsed, phase_offset=0.0)
            x2, y2, z2 = generate_sweep_coordinates(elapsed, phase_offset=5.5)

            payload1 = f"arm1 {x1:.2f} {y1:.2f} {z1:.2f}\n"
            payload2 = f"arm2 {x2:.2f} {y2:.2f} {z2:.2f}\n"
            
            # Send with a 15ms gap to prevent ESP32 buffer collisions
            ser.write(payload1.encode('ascii'))
            time.sleep(0.015)  
            ser.write(payload2.encode('ascii'))

            # Terminal UI
            progress_bar = "#" * int((elapsed / args.duration) * 20)
            spaces = " " * (20 - len(progress_bar))
            print(f"\r[{progress_bar}{spaces}] Rem: {end_time - t0:5.1f}s | Arm1 Z: {z1:5.2f} | Arm2 Z: {z2:5.2f}", end="")

            elapsed_processing = time.time() - t0
            time.sleep(max(0.0, interval - elapsed_processing))

    except KeyboardInterrupt:
        print("\n[HALT] Trajectory sequence interrupted prematurely by user.")
    finally:
        print("\n[COMPLETE] 120-second sweep finished. Homing both arms...")
        home_z = BASE_HEIGHT + L1 + L2 - 5.0
        
        # Add the same 15ms buffer to the homing commands
        ser.write(f"arm1 0.00 12.00 {home_z:.2f}\n".encode('ascii'))
        time.sleep(0.015)
        ser.write(f"arm2 0.00 12.00 {home_z:.2f}\n".encode('ascii'))
        ser.close()

if __name__ == "__main__":
    main()