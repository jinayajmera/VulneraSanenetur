"""
RoboSurge Phase 1 — Procedure Agent
NL command → LLM (Groq) → validated XYZ waypoints → Serial → ESP32 IK → servos

Usage:
  python procedure_agent.py --port COM6
  python procedure_agent.py --dry-run
"""

from groq import Groq
import os
import serial
import serial.tools.list_ports
import argparse
import json
import time
import math
import sys


from dotenv import load_dotenv
load_dotenv()
# ============================================================
# ROBOT PHYSICAL CONSTANTS
# ============================================================
L1          = 9.5
L2          = 12.0
BASE_HEIGHT = 7.5
MAX_REACH   = L1 + L2
MIN_REACH   = abs(L1 - L2)
TABLE_Z     = BASE_HEIGHT
DEFAULT_Y   = 15.0
DEFAULT_Z   = TABLE_Z + 2.0
MAX_DOWN_Z  = TABLE_Z - 1.5  # allow up to 15mm penetration below surface

# ============================================================
# SYSTEM PROMPT
# ============================================================
SYSTEM_PROMPT = f"""
You are the motion planner for RoboSurge, a two-arm surgical robot.

PHYSICAL CONFIGURATION:
- Arm segments: L1={L1}cm (shoulder to elbow), L2={L2}cm (elbow to tip)
- Base tower height: {BASE_HEIGHT}cm
- Table surface: z={TABLE_Z}cm
- Max reach from base: {MAX_REACH}cm
- Min reach from base: {MIN_REACH}cm (blind spot, avoid)
- Safe working z range: {TABLE_Z}cm to {TABLE_Z + 10}cm
- Default workspace centre: x=0, y={DEFAULT_Y}, z={DEFAULT_Z}

ARM CONVENTION:
- Arm 1 = LEFT arm — PRIMARY CUTTING ARM (scalpel/incision)
- Arm 2 = RIGHT arm — SECONDARY ARM (suturing or cauterization after arm 1)
- For any incision: arm 1 cuts first, then arm 2 follows to suture/cauterize
- Arm 2 approaches the same site AFTER arm 1 fully retracts, never simultaneously

COORDINATE SYSTEM:
- Origin at base of each arm tower
- x: left/right offset from arm centre
- y: forward distance from arm base
- z: height (z={BASE_HEIGHT} is table surface)

OUTPUT FORMAT:
Return ONLY a JSON object. No explanation, no markdown, no code fences:
{{
  "procedure": "brief name",
  "steps": [
    {{
      "label": "human readable description",
      "arm": 1,
      "x": 0.0,
      "y": 15.0,
      "z": 10.0,
      "wait_ms": 500
    }}
  ]
}}

PLANNING RULES:
1. Always start with an APPROACH step 2-3cm above the target (z = target_z + 2.5)
2. For incisions: arm1 approach -> arm1 press to depth -> arm1 translate -> arm1 retract -> arm2 approach same site -> arm2 contact (suture/cauterize) -> arm2 retract
3. depth_mm maps to z as a pre-computed float. e.g. 3mm depth = z=7.20, 5mm = z=7.00, 10mm = z=6.50, 15mm = z=6.00. NEVER write expressions in JSON, only plain numbers.
4. Never set z below 6.0 (that is 15mm max penetration depth)
5. Never place end-effector more than {MAX_REACH}cm from base
6. Never place end-effector less than {MIN_REACH}cm from base
7. End every procedure with BOTH arms retracted to safe height z=11.5
8. wait_ms minimum 500, use 1500 for any tissue contact step
9. Arm 2 always starts AFTER arm 1 has fully retracted
10. Return ONLY the JSON object, nothing else
"""

# ============================================================
# VALIDATION
# ============================================================
def validate_waypoint(step: dict) -> tuple[bool, str]:
    x, y, z = step["x"], step["y"], step["z"]
    arm = step["arm"]
    if z < MAX_DOWN_Z:
        return False, f"z={z} is below table surface ({MAX_DOWN_Z})"
    true_z = z - BASE_HEIGHT
    r = math.sqrt(x**2 + y**2)
    d = math.sqrt(r**2 + true_z**2)
    if d > MAX_REACH:
        return False, f"arm {arm}: distance {d:.1f}cm exceeds max reach {MAX_REACH}cm"
    if d < MIN_REACH:
        return False, f"arm {arm}: distance {d:.1f}cm is in blind spot (min {MIN_REACH}cm)"
    if arm not in (1, 2):
        return False, f"invalid arm number {arm}"
    return True, "ok"


def validate_procedure(steps: list) -> list:
    errors = []
    for i, step in enumerate(steps):
        ok, msg = validate_waypoint(step)
        if not ok:
            errors.append(f"Step {i+1} '{step.get('label','')}': {msg}")
    return errors


# ============================================================
# LLM PLANNING via GROQ
# ============================================================
def plan_procedure(command: str, client: Groq) -> dict:
    print(f"\n[agent] Planning: '{command}'")

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            temperature=0.1,
            max_tokens=4096,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": command}
            ]
        )
        print("  [model: llama-3.3-70b-versatile via Groq]")
    except Exception as e:
        print(f"[error] Groq failed: {e}")
        sys.exit(1)

    raw = response.choices[0].message.content.strip()

    # Strip markdown fences if model added them anyway
    if "```" in raw:
        parts = raw.split("```")
        for part in parts:
            p = part.strip()
            if p.startswith("json"):
                raw = p[4:].strip()
                break
            elif p.startswith("{"):
                raw = p
                break

    # Extract JSON object boundaries
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start != -1 and end > start:
        raw = raw[start:end]

    try:
        plan = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[error] LLM returned invalid JSON: {e}")
        print(f"  Raw: {raw[:400]}")
        sys.exit(1)

    return plan


# ============================================================
# SERIAL EXECUTION
# ============================================================
def wait_for_esp32(ser: serial.Serial, timeout: float = 15.0):
    ser.timeout = 0.3
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = ser.readline()
        if line:
            print(f"  ESP32: {line.decode(errors='replace').strip()}")
        else:
            break
    ser.timeout = 2.0


def send_waypoint(step: dict, ser, dry_run: bool):
    arm = step["arm"]
    x, y, z = step["x"], step["y"], step["z"]
    wait_ms = step.get("wait_ms", 500)
    cmd = f"arm{arm} {x:.1f} {y:.1f} {z:.1f}\n"

    print(f"\n  -> [{step['label']}]")
    print(f"     cmd: {cmd.strip()}")

    if dry_run or ser is None:
        print(f"     [DRY RUN] would send, then wait {wait_ms}ms")
        time.sleep(wait_ms / 1000.0)
        return

    ser.write(cmd.encode())
    wait_for_esp32(ser)
    if wait_ms > 0:
        time.sleep(wait_ms / 1000.0)


def execute_procedure(plan: dict, ser, dry_run: bool):
    steps = plan["steps"]
    print(f"\n[exec] Executing '{plan['procedure']}' — {len(steps)} steps")
    for step in steps:
        send_waypoint(step, ser, dry_run)
    print("\n[exec] Procedure complete.")


# ============================================================
# MAIN
# ============================================================
def connect_serial(port: str, baud: int = 115200) -> serial.Serial:
    try:
        ser = serial.Serial(port, baud, timeout=2)
        time.sleep(2.5)
        ser.flushInput()
        print(f"[serial] Connected on {port} @ {baud}")
        return ser
    except serial.SerialException as e:
        print(f"[error] Cannot open {port}: {e}")
        print("\nAvailable ports:")
        for p in serial.tools.list_ports.comports():
            print(f"  {p.device} — {p.description}")
        sys.exit(1)


def print_plan(plan: dict):
    print(f"\n{'─'*58}")
    print(f"  Procedure : {plan['procedure']}")
    print(f"  Steps     : {len(plan['steps'])}")
    print(f"{'─'*58}")
    for i, s in enumerate(plan["steps"], 1):
        print(f"  {i:2}. ARM{s['arm']}  ({s['x']:+.1f}, {s['y']:.1f}, {s['z']:.1f})"
              f"  wait={s.get('wait_ms',500)}ms   {s['label']}")
    print(f"{'─'*58}")


def main():
    parser = argparse.ArgumentParser(description="RoboSurge Phase 1 — Procedure Agent")
    parser.add_argument("--port",    default=None,   help="Serial port e.g. COM6")
    parser.add_argument("--baud",    default=115200,  type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    dry_run = args.dry_run or args.port is None
    if dry_run and args.port is None:
        print("[info] No --port given, running in dry-run mode")

    ser = None
    if not dry_run:
        ser = connect_serial(args.port, args.baud)

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("[error] Set GROQ_API_KEY environment variable")
        print("  Get free key: https://console.groq.com")
        sys.exit(1)

    client = Groq(api_key=api_key)

    print("\n╔══════════════════════════════════╗")
    print("║  RoboSurge Phase 1 — Agent CLI  ║")
    print("╚══════════════════════════════════╝")
    print("Model : llama-3.3-70b via Groq (free)")
    print("Type a procedure or 'quit' to exit\n")
    print("Examples:")
    print("  make a 3mm incision horizontally")
    print("  lift arm 1 to safe height")
    print("  home both arms")
    print("  retract arm 2")

    while True:
        try:
            command = input("\nProcedure > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[exit]")
            break

        if not command:
            continue
        if command.lower() in ("quit", "exit", "q"):
            break

        plan = plan_procedure(command, client)
        print_plan(plan)

        errors = validate_procedure(plan["steps"])
        if errors:
            print("\n[VALIDATION FAILED]")
            for e in errors:
                print(f"  x {e}")
            continue

        print("\n[validation] All waypoints OK")

        if dry_run:
            print("[dry-run] Would execute above steps.")
            continue

        confirm = input("Execute? (y/n) > ").strip().lower()
        if confirm != "y":
            print("[abort] Not executing.")
            continue

        execute_procedure(plan, ser, dry_run)

    if ser:
        ser.close()
    print("[done]")


if __name__ == "__main__":
    main()