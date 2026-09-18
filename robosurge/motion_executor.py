"""
motion_executor.py — RoboSurge Phase 4
========================================
Executes a validated ProcedurePlan by interpolating waypoints and streaming
"arm1 X Y Z\n" / "arm2 X Y Z\n" commands to the ESP32 at 10 Hz.

Execution model
---------------
Both arms execute CONCURRENTLY in separate threads.  arm2 (retractor) gets a
SETUP_LEAD_S second head start to reach its hold position before arm1 begins
the cutting motion.  This prevents the cutter from entering the field while
the retractor is still moving.

For each arm the executor:
  1. Iterates through waypoints in sequence.
  2. Linearly interpolates between consecutive waypoints at the arm's
     feed_rate_mm_s, producing one serial command per step.
  3. Sends each command at LOOP_RATE_HZ (10 Hz).
  4. Waits at each waypoint for WAYPOINT_DWELL_S before proceeding.

Abort mechanism
---------------
Call executor.abort() from any thread to immediately stop both arms and
send them to safe height.  The SIGINT handler in robosurge_cli.py calls this.

Dry-run mode
------------
If serial_write_fn is None, commands are printed but not sent.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .surgical_agent import ArmPlan, ProcedurePlan, Waypoint
from .scene_state import SAFE_Z_CM, TABLE_Z_CM

logger = logging.getLogger("MotionExecutor")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOOP_RATE_HZ:      float = 10.0
LOOP_INTERVAL_S:   float = 1.0 / LOOP_RATE_HZ
WAYPOINT_DWELL_S:  float = 0.15   # pause at each waypoint before next segment
SETUP_LEAD_S:      float = 2.0    # arm2 starts N seconds before arm1 for incision
ABORT_FEED_MM_S:   float = 15.0   # fastest retract on abort

# Home position (both arms move here after abort or home procedure)
HOME_X: float = 10.0
HOME_Y: float =  0.0
HOME_Z: float = SAFE_Z_CM

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR:       Path = _PROJECT_ROOT / "logs"


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class ExecutionResult:
    arm_id:          int
    steps_sent:      int
    waypoints_hit:   int
    aborted:         bool
    duration_s:      float
    final_position:  tuple[float, float, float]


# ---------------------------------------------------------------------------
# MotionExecutor
# ---------------------------------------------------------------------------

class MotionExecutor:
    """
    Executes a validated ProcedurePlan by streaming serial commands.

    Parameters
    ----------
    serial_write_fn : callable (str) → bool, optional
        Function that writes one command string to the serial port and returns
        True on success.  If None, runs in dry-run mode (print only).
    loop_rate_hz : float
        Command send rate.  Keep at 10.0 to match the ESP32's expected rate.
    """

    def __init__(
        self,
        serial_write_fn: Optional[Callable[[str], bool]] = None,
        loop_rate_hz:    float = LOOP_RATE_HZ,
    ) -> None:
        self._write       = serial_write_fn or self._dry_run_write
        self._interval    = 1.0 / loop_rate_hz
        self._abort_flag  = threading.Event()
        self._lock        = threading.Lock()
        self._current_pos: dict[int, tuple[float, float, float]] = {
            1: (HOME_X, HOME_Y, HOME_Z),
            2: (HOME_X, HOME_Y, HOME_Z),
        }
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self._command_log = LOG_DIR / "last_execution_commands.log"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(self, plan: ProcedurePlan) -> dict[int, ExecutionResult]:
        """
        Execute a ProcedurePlan.  Blocks until both arms complete or abort.

        Parameters
        ----------
        plan : ProcedurePlan — must have passed ProcedureValidator.validate()

        Returns
        -------
        dict[arm_id → ExecutionResult]
        """
        self._abort_flag.clear()
        self._command_log.write_text("", encoding="utf-8")

        results: dict[int, Optional[ExecutionResult]] = {1: None, 2: None}

        if plan.procedure in ("incision", "biopsy", "cauterization", "debridement"):
            # arm2 leads: retract/hold tissue first, then arm1 operates
            self._execute_arm_lead_follow(plan, results)
        else:
            # "suturing" lands here too: both arms move together the whole
            # time (arm2's tug choreography is timed to arm1's stitch
            # rhythm), so lead-follow would defeat the point.
            self._execute_concurrent(plan, results)

        return {k: v for k, v in results.items() if v is not None}

    def abort(self) -> None:
        """
        Signal both arm threads to stop immediately.
        Sends a retract-to-safe-height command for both arms synchronously
        after the threads stop.
        """
        logger.warning("ABORT requested.")
        self._abort_flag.set()
        # Give threads ~200ms to see the flag
        time.sleep(0.2)
        # Force both arms to safe height
        for arm_id in (1, 2):
            pos = self._current_pos[arm_id]
            cmd = self._format_command(arm_id, pos[0], pos[1], SAFE_Z_CM)
            self._send(cmd)
            logger.info("Abort retract arm%d: %r", arm_id, cmd.strip())

    @property
    def current_positions(self) -> dict[int, tuple[float, float, float]]:
        """Thread-safe read of the last commanded position for each arm."""
        with self._lock:
            return dict(self._current_pos)

    # ------------------------------------------------------------------
    # Execution strategies
    # ------------------------------------------------------------------

    def _execute_arm_lead_follow(
        self,
        plan:    ProcedurePlan,
        results: dict,
    ) -> None:
        """
        arm2 executes first (reaches hold position), then arm1 begins.
        Both run in threads; arm1 waits SETUP_LEAD_S before starting.
        """
        arm2_ready = threading.Event()

        def run_arm2():
            res = self._execute_single_arm(plan.arm2)
            results[2] = res
            arm2_ready.set()

        def run_arm1():
            # Wait for arm2 to reach its first waypoint (hold position)
            arm2_ready.wait()
            if self._abort_flag.is_set():
                return
            time.sleep(0.1)   # brief sync gap
            results[1] = self._execute_single_arm(plan.arm1)

        t2 = threading.Thread(target=run_arm2, daemon=True, name="arm2_exec")
        t1 = threading.Thread(target=run_arm1, daemon=True, name="arm1_exec")
        t2.start()
        t1.start()
        t2.join()
        t1.join()

    def _execute_concurrent(
        self,
        plan:    ProcedurePlan,
        results: dict,
    ) -> None:
        """Both arms start simultaneously."""
        def run_arm(arm_plan: ArmPlan):
            results[arm_plan.arm_id] = self._execute_single_arm(arm_plan)

        threads = [
            threading.Thread(target=run_arm, args=(plan.arm1,), daemon=True),
            threading.Thread(target=run_arm, args=(plan.arm2,), daemon=True),
        ]
        for t in threads: t.start()
        for t in threads: t.join()

    # ------------------------------------------------------------------
    # Single-arm execution
    # ------------------------------------------------------------------

    def _execute_single_arm(self, arm: ArmPlan) -> ExecutionResult:
        """
        Stream interpolated waypoints for one arm until done or aborted.

        For each segment (waypoint[i] → waypoint[i+1]):
          - Compute the number of steps = segment_length_mm / feed_rate_mm_s / dt
          - Send one command per step, sleeping LOOP_INTERVAL_S between each
          - Dwell at the waypoint for WAYPOINT_DWELL_S

        Returns ExecutionResult.
        """
        t_start = time.monotonic()
        steps_sent    = 0
        waypoints_hit = 0
        start = self._current_pos[arm.arm_id]
        wps = [
            Waypoint(x=start[0], y=start[1], z=start[2], label="current"),
            *arm.waypoints,
        ]

        if not arm.waypoints:
            return ExecutionResult(
                arm_id=arm.arm_id, steps_sent=0, waypoints_hit=0,
                aborted=False, duration_s=0.0,
                final_position=self._current_pos[arm.arm_id],
            )

        for i in range(len(wps) - 1):
            if self._abort_flag.is_set():
                logger.warning("arm%d execution aborted at wp[%d].", arm.arm_id, i)
                break

            a, b      = wps[i], wps[i + 1]
            seg_len_mm = self._dist_mm(a, b)

            if seg_len_mm < 0.1:
                # Negligible segment — snap to target
                cmd = self._format_command(arm.arm_id, b.x, b.y, b.z)
                self._send(cmd)
                self._update_pos(arm.arm_id, b.x, b.y, b.z)
                steps_sent += 1
                waypoints_hit += 1
                time.sleep(WAYPOINT_DWELL_S)
                if b.dwell_s > 0:
                    logger.info("arm%d dwelling %.2fs at '%s' (cauterization hold).",
                                arm.arm_id, b.dwell_s, b.label)
                    self._dwell_with_abort_check(b.dwell_s)
                continue

            # Number of serial ticks to cover this segment
            seg_duration_s = seg_len_mm / arm.feed_rate_mm_s
            n_steps        = max(1, int(seg_duration_s / self._interval))

            for step in range(1, n_steps + 1):
                if self._abort_flag.is_set():
                    break
                t0   = time.monotonic()
                frac = step / n_steps
                x    = a.x + frac * (b.x - a.x)
                y    = a.y + frac * (b.y - a.y)
                z    = a.z + frac * (b.z - a.z)

                cmd = self._format_command(arm.arm_id, x, y, z)
                self._send(cmd)
                self._update_pos(arm.arm_id, x, y, z)
                steps_sent += 1

                # Rate limiting
                elapsed = time.monotonic() - t0
                sleep_for = max(0.0, self._interval - elapsed)
                time.sleep(sleep_for)

            waypoints_hit += 1
            time.sleep(WAYPOINT_DWELL_S)
            if b.dwell_s > 0:
                logger.info("arm%d dwelling %.2fs at '%s' (cauterization hold).",
                            arm.arm_id, b.dwell_s, b.label)
                self._dwell_with_abort_check(b.dwell_s)

        return ExecutionResult(
            arm_id=arm.arm_id,
            steps_sent=steps_sent,
            waypoints_hit=waypoints_hit,
            aborted=self._abort_flag.is_set(),
            duration_s=time.monotonic() - t_start,
            final_position=self._current_pos[arm.arm_id],
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _dwell_with_abort_check(self, duration_s: float, poll_s: float = 0.1) -> None:
        """Sleep for duration_s in small increments so abort() can interrupt a long dwell."""
        end_t = time.monotonic() + duration_s
        while time.monotonic() < end_t:
            if self._abort_flag.is_set():
                return
            time.sleep(min(poll_s, max(0.0, end_t - time.monotonic())))

    @staticmethod
    def _format_command(arm_id: int, x: float, y: float, z: float) -> str:
        """Format the ESP32 serial command string."""
        return f"arm{arm_id} {x:+.2f} {y:+.2f} {z:.2f}\n"

    def _send(self, cmd: str) -> bool:
        """Write one command and append it to last_execution_commands.log."""
        with self._command_log.open("a", encoding="utf-8") as fh:
            fh.write(cmd)
        return self._write(cmd)

    def _update_pos(self, arm_id: int, x: float, y: float, z: float) -> None:
        with self._lock:
            self._current_pos[arm_id] = (x, y, z)

    @staticmethod
    def _dist_mm(a: Waypoint, b: Waypoint) -> float:
        """3-D Euclidean distance between two waypoints in mm."""
        return math.sqrt((b.x-a.x)**2 + (b.y-a.y)**2 + (b.z-a.z)**2) * 10.0

    @staticmethod
    def _dry_run_write(cmd: str) -> bool:
        """Default write function: print instead of sending."""
        print(f"  [DRY-RUN] {cmd.strip()}")
        return True


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    from .surgical_agent import ArmPlan, ProcedurePlan, Waypoint

    # Simulate a 3mm incision at landmark_A = (11.0, 1.0) with tool_offset=0.15
    cut_z = TABLE_Z_CM - 0.3 + 0.15   # = 7.35

    test_plan = ProcedurePlan(
        procedure="incision",
        rationale="Test 3mm incision",
        arm1=ArmPlan(arm_id=1, role="cutting", feed_rate_mm_s=2.0, waypoints=[
            Waypoint(x=11.0, y=1.0, z=10.0, label="transit"),
            Waypoint(x=11.0, y=1.0, z=7.7,  label="approach"),
            Waypoint(x=11.0, y=1.0, z=cut_z, label="plunge"),
            Waypoint(x=11.3, y=1.0, z=cut_z, label="drag_end"),
            Waypoint(x=11.3, y=1.0, z=10.0, label="retract"),
        ]),
        arm2=ArmPlan(arm_id=2, role="retracting", feed_rate_mm_s=8.0, waypoints=[
            Waypoint(x=11.0, y=4.0, z=7.5, label="hold"),
        ]),
        estimated_duration_s=15.0,
        safety_notes="",
    )

    executor = MotionExecutor()   # dry-run
    print("Executing test plan (dry-run)...\n")
    results = executor.execute(test_plan)

    for arm_id, res in results.items():
        print(
            f"\nArm {arm_id}: steps={res.steps_sent}  wps={res.waypoints_hit}  "
            f"duration={res.duration_s:.2f}s  aborted={res.aborted}  "
            f"final={tuple(round(v,2) for v in res.final_position)}"
        )