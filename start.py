"""
start.py — RoboSurge Full-Stack Launcher
=========================================
Launches all three services concurrently with unified logging and graceful shutdown on Ctrl+C:
  1. Python Vision & Kinematics Web API (port 8000)
  2. Express Gateway & Worker Queue (port 8080)
  3. React Vite Surgeon Console Frontend (port 5173)

Usage:
  python start.py
  (or py -3.11 start.py)
"""

import os
import sys
import subprocess
import threading
import time

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")

# ANSI Colors for terminal output
COLOR_CYAN = "\033[96m"
COLOR_GREEN = "\033[92m"
COLOR_YELLOW = "\033[93m"
COLOR_RED = "\033[91m"
COLOR_RESET = "\033[0m"
COLOR_BOLD = "\033[1m"

def stream_logs(pipe, prefix, color):
    try:
        for line in iter(pipe.readline, ''):
            if not line:
                break
            print(f"{color}{COLOR_BOLD}[{prefix}]{COLOR_RESET} {line.rstrip()}")
    except Exception:
        pass

def get_python_cmd():
    # Try multiple candidate python commands
    candidates = [
        [sys.executable],
        ["py", "-3.11"],
        [os.path.expanduser(r"~\AppData\Local\Programs\Python\Python311\python.exe")],
        ["python3.11"],
        ["python"],
    ]
    for cand in candidates:
        try:
            res = subprocess.run(
                cand + ["-c", "import cv2, fastapi, uvicorn; print('OK')"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=3
            )
            if res.returncode == 0 and "OK" in res.stdout:
                return cand
        except Exception:
            pass
    return [sys.executable]

def main():
    print(f"\n{COLOR_BOLD}{COLOR_CYAN}==============================================={COLOR_RESET}")
    print(f"{COLOR_BOLD}{COLOR_CYAN}         RoboSurge Full-Stack Launcher         {COLOR_RESET}")
    print(f"{COLOR_BOLD}{COLOR_CYAN}==============================================={COLOR_RESET}\n")

    # Determine python executable
    python_cmd = get_python_cmd()

    processes = []

    # 1. Start Python Web Server
    print(f"{COLOR_CYAN}[LAUNCH]{COLOR_RESET} Starting Python Core API on http://127.0.0.1:8000 (using {' '.join(python_cmd)}) ...")
    p_python = subprocess.Popen(
        python_cmd + ["web_server.py"],
        cwd=ROOT_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    processes.append(("PYTHON ", p_python, COLOR_CYAN))

    # 2. Start Express Gateway
    print(f"{COLOR_GREEN}[LAUNCH]{COLOR_RESET} Starting Express Gateway on http://localhost:8080 ...")
    node_cmd = "node"
    p_backend = subprocess.Popen(
        [node_cmd, "server.js"],
        cwd=BACKEND_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    processes.append(("GATEWAY", p_backend, COLOR_GREEN))

    # 3. Start Frontend Dev Server (if directory exists)
    if os.path.isdir(FRONTEND_DIR):
        print(f"{COLOR_YELLOW}[LAUNCH]{COLOR_RESET} Starting Vite Frontend on http://localhost:5173 ...")
        npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
        p_frontend = subprocess.Popen(
            [npm_cmd, "run", "dev"],
            cwd=FRONTEND_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        processes.append(("FRONTEND", p_frontend, COLOR_YELLOW))

    # Start logging threads
    threads = []
    for prefix, proc, color in processes:
        t = threading.Thread(target=stream_logs, args=(proc.stdout, prefix, color), daemon=True)
        t.start()
        threads.append(t)

    print(f"\n{COLOR_BOLD}{COLOR_GREEN}[OK] All services launched! Press Ctrl+C to stop all services.{COLOR_RESET}\n")
    if os.path.isdir(FRONTEND_DIR):
        print(f"  Surgeon Console : {COLOR_BOLD}http://localhost:5173{COLOR_RESET}")
    print(f"  Express Gateway : {COLOR_BOLD}http://localhost:8080{COLOR_RESET}")
    print(f"  Python Core API : {COLOR_BOLD}http://127.0.0.1:8000{COLOR_RESET}\n")

    def shutdown():
        print(f"\n{COLOR_BOLD}{COLOR_RED}[SHUTDOWN] Stopping all services...{COLOR_RESET}")
        for prefix, proc, _ in processes:
            try:
                if proc.poll() is None:
                    proc.terminate()
            except Exception:
                pass
        time.sleep(1)
        for prefix, proc, _ in processes:
            try:
                if proc.poll() is None:
                    proc.kill()
            except Exception:
                pass
        print(f"{COLOR_BOLD}{COLOR_GREEN}[OK] All services cleanly stopped.{COLOR_RESET}")

    try:
        while True:
            # Check if any process exited unexpectedly
            for prefix, proc, _ in processes:
                if proc.poll() is not None:
                    print(f"\n{COLOR_RED}[WARN] {prefix} process exited with code {proc.returncode}{COLOR_RESET}")
                    shutdown()
                    return
            time.sleep(0.5)
    except KeyboardInterrupt:
        shutdown()

if __name__ == "__main__":
    main()
