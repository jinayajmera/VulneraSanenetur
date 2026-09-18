"""
procedure_validator.py — RoboSurge Phase 4
============================================
Pure-math safety validation layer.  Runs AFTER the LLM produces a ProcedurePlan
and BEFORE any serial command is sent to the ESP32.

This module has NO external dependencies beyond stdlib + numpy.
It never calls the LLM and never touches the camera or serial port.
Every check is deterministic and unit-testable.

Validation checks (in order)
------------------------------
1.  WORKSPACE_BOUNDS    — every waypoint's (x,y) reach is within [MIN_REACH, MAX_REACH].
2.  Z_FLOOR             — every waypoint Z ≥ TABLE_Z_CM - MAX_CUT_DEPTH_CM.
3.  INTER_ARM_CLEARANCE — at every time step (waypoints interpolated at 1 mm resolution),
                          the 3-D distance between arm1 tip and arm2 tip ≥ MIN_ARM_CLEARANCE.
4.  MAX_STEP_DELTA      — consecutive waypoints are not more than MAX_WAYPOINT_DELTA_CM apart
                          (catches LLM-hallucinated teleports).
5.  FEED_RATE_BOUNDS    — feed rate is within [FEED_RATE_MIN, FEED_RATE_MAX] mm/s.
6.  INCISION_LANDMARK   — for procedure="incision", the drag vector passes within
                          LANDMARK_TOLERANCE_CM of the declared target landmark.
7.  PROCEDURE_ARM_ROLES — arm roles are consistent with the procedure type.

On any failure: ValidationResult.ok = False, ValidationResult.errors lists the issues.
The MotionExecutor will refuse to execute a plan with ok=False.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .surgical_agent import ArmPlan, ProcedurePlan, Waypoint
from .scene_state import (
    TABLE_Z_CM, MIN_REACH, MAX_REACH, SAFE_Z_CM, LandmarkState
)

logger = logging.getLogger("ProcedureValidator")

# ---------------------------------------------------------------------------
# Safety constants
# ---------------------------------------------------------------------------

MAX_CUT_DEPTH_CM:       float = 12.0   # max incision depth below table Z
MIN_ARM_CLEARANCE_CM:   float = 2.5    # minimum tip-to-tip distance (LLM targets 5cm)
MAX_WAYPOINT_DELTA_CM:  float = 15.0    # max jump between consecutive waypoints
FEED_RATE_MIN_MM_S:     float = 0.5
FEED_RATE_MAX_MM_S:     float = 15.0
LANDMARK_TOLERANCE_CM:  float = 2.0    # incision drag must pass within this of landmark
INTERP_STEP_CM:         float = 0.1    # interpolation resolution for clearance check
MIN_INCISION_LENGTH_CM: float = 0.25   # 3mm incision must not become a zero-length tap
POINT_PROCEDURE_TOLERANCE_CM: float = 2.0   # biopsy/cauterization plunge must be this close to target
DEBRIDEMENT_MAX_EXTENT_CM:    float = 4.0   # max distance any sweep point may stray from target
MIN_CAUTERIZATION_DWELL_S:    float = 0.5   # below this, dwell is too short to actually cauterize
SUTURE_REGION_TOLERANCE_CM:   float = 3.0   # entry/exit points must stay this close to target landmark
MIN_SUTURE_LOOP_HEIGHT_CM:    float = 0.3   # 'loop' waypoint must rise at least this far above the table
MIN_SUTURE_CINCH_DWELL_S:     float = 0.1   # below this, cinch is too brief to look like a thread pull
MIN_SUTURE_STITCHES:          int   = 1     # at least one entry/exit pair required


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    ok:      bool
    errors:  list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.ok = False
        logger.error("VALIDATION FAIL: %s", msg)

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)
        logger.warning("VALIDATION WARN: %s", msg)

    def summary(self) -> str:
        status = "PASS" if self.ok else "FAIL"
        lines  = [f"[{status}]  {len(self.errors)} errors, {len(self.warnings)} warnings"]
        for e in self.errors:
            lines.append(f"  ERROR   {e}")
        for w in self.warnings:
            lines.append(f"  WARNING {w}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# ProcedureValidator
# ---------------------------------------------------------------------------

class ProcedureValidator:
    """
    Validates a ProcedurePlan before execution.

    Parameters
    ----------
    landmarks : list[LandmarkState], optional
        Current landmark detections.  Required for INCISION_LANDMARK check.
    """

    def __init__(
        self,
        landmarks: Optional[list[LandmarkState]] = None,
    ) -> None:
        self._landmarks = landmarks or []

    def validate(self, plan: ProcedurePlan) -> ValidationResult:
        """
        Run all checks on plan.  Returns a ValidationResult.
        Checks are independent — all run even if earlier ones fail,
        so the user gets a complete error list in one shot.
        """
        result = ValidationResult(ok=True)

        self._check_workspace_bounds(plan.arm1, result)
        self._check_workspace_bounds(plan.arm2, result)
        self._check_z_floor(plan.arm1, result)
        self._check_z_floor(plan.arm2, result)
        self._check_feed_rates(plan.arm1, result)
        self._check_feed_rates(plan.arm2, result)
        self._check_max_step_delta(plan.arm1, result)
        self._check_max_step_delta(plan.arm2, result)
        self._check_inter_arm_clearance(plan.arm1, plan.arm2, result)
        self._check_procedure_arm_roles(plan, result)

        if plan.procedure == "incision":
            self._check_incision_landmark(plan, result)
        elif plan.procedure in ("biopsy", "cauterization"):
            self._check_point_procedure_landmark(plan, result)
        elif plan.procedure == "debridement":
            self._check_debridement_region(plan, result)
        elif plan.procedure == "suturing":
            self._check_suturing_pattern(plan, result)

        if plan.procedure == "cauterization":
            self._check_cauterization_dwell(plan, result)

        if result.ok:
            logger.info("Validation PASSED for procedure=%s", plan.procedure)
        else:
            logger.error(
                "Validation FAILED for procedure=%s  errors=%d",
                plan.procedure, len(result.errors),
            )
        return result

    # ------------------------------------------------------------------
    # Individual checks (private)
    # ------------------------------------------------------------------

    def _check_workspace_bounds(self, arm: ArmPlan, r: ValidationResult) -> None:
        """
        Check 1: Every waypoint must have a horizontal reach within
        [MIN_REACH, MAX_REACH] cm from the base pan axis.

        reach_xy = sqrt(x² + y²)
        """
        for i, wp in enumerate(arm.waypoints):
            reach = math.hypot(wp.x, wp.y)
            if reach < MIN_REACH:
                # Only error if reach is truly in blind spot (< 2.5cm)
                # Negative X coords are valid — reach uses sqrt(x²+y²)
                r.add_error(
                    f"arm{arm.arm_id} wp[{i}] '{wp.label}': "
                    f"reach={reach:.3f} cm < MIN_REACH={MIN_REACH} cm (blind spot)."
                )
            elif reach > MAX_REACH:
                r.add_error(
                    f"arm{arm.arm_id} wp[{i}] '{wp.label}': "
                    f"reach={reach:.3f} cm > MAX_REACH={MAX_REACH} cm."
                )

    def _check_z_floor(self, arm: ArmPlan, r: ValidationResult) -> None:
        """
        Check 2: Z must not go below TABLE_Z_CM - MAX_CUT_DEPTH_CM.

        A 3mm incision sets Z = TABLE_Z_CM - 0.3, which is well within the
        0.5 cm floor.  Anything deeper is a hardware collision risk.
        """
        z_floor = TABLE_Z_CM - MAX_CUT_DEPTH_CM
        for i, wp in enumerate(arm.waypoints):
            if wp.z < z_floor:
                r.add_error(
                    f"arm{arm.arm_id} wp[{i}] '{wp.label}': "
                    f"z={wp.z:.3f} cm < floor={z_floor:.3f} cm "
                    f"(max cut depth {MAX_CUT_DEPTH_CM*10:.0f}mm exceeded)."
                )

    def _check_feed_rates(self, arm: ArmPlan, r: ValidationResult) -> None:
        """Check 3: Feed rate within servo capability bounds."""
        if arm.feed_rate_mm_s < FEED_RATE_MIN_MM_S:
            r.add_error(
                f"arm{arm.arm_id} feed_rate={arm.feed_rate_mm_s} mm/s "
                f"< minimum {FEED_RATE_MIN_MM_S} mm/s."
            )
        if arm.feed_rate_mm_s > FEED_RATE_MAX_MM_S:
            r.add_error(
                f"arm{arm.arm_id} feed_rate={arm.feed_rate_mm_s} mm/s "
                f"> maximum {FEED_RATE_MAX_MM_S} mm/s."
            )

    def _check_max_step_delta(self, arm: ArmPlan, r: ValidationResult) -> None:
        """
        Check 4: Consecutive waypoints must not be more than MAX_WAYPOINT_DELTA_CM
        apart in 3-D Euclidean distance.

        LLMs occasionally hallucinate teleports (e.g. jumping from x=5 to x=20
        in a single step).  This catches that.
        """
        wps = arm.waypoints
        for i in range(len(wps) - 1):
            a, b = wps[i], wps[i + 1]
            dist = math.sqrt((b.x-a.x)**2 + (b.y-a.y)**2 + (b.z-a.z)**2)
            if dist > MAX_WAYPOINT_DELTA_CM:
                r.add_error(
                    f"arm{arm.arm_id} step [{i}→{i+1}] "
                    f"('{a.label}'→'{b.label}'): "
                    f"delta={dist:.2f} cm > MAX={MAX_WAYPOINT_DELTA_CM} cm (teleport?)."
                )

    def _check_inter_arm_clearance(
        self,
        arm1: ArmPlan,
        arm2: ArmPlan,
        r:    ValidationResult,
    ) -> None:
        """
        Check 5: The 3-D distance between arm1 tip and arm2 tip must be
        ≥ MIN_ARM_CLEARANCE_CM at every point along their paths.

        Method: interpolate each arm's path at INTERP_STEP_CM resolution
        (linear segments between waypoints), then compute pairwise distances.
        Both paths are padded to the same length by repeating the final
        waypoint of the shorter path.

        This is O(N) in the number of interpolated steps — fast enough.
        """
        path1 = self._interpolate_path(arm1.waypoints)
        path2 = self._interpolate_path(arm2.waypoints)

        # Pad to same length
        max_len = max(len(path1), len(path2))
        if len(path1) < max_len:
            path1 += [path1[-1]] * (max_len - len(path1))
        if len(path2) < max_len:
            path2 += [path2[-1]] * (max_len - len(path2))

        violations: list[int] = []
        for i, (p1, p2) in enumerate(zip(path1, path2)):
            dist = math.sqrt(sum((a-b)**2 for a,b in zip(p1, p2)))
            if dist < MIN_ARM_CLEARANCE_CM:
                violations.append(i)

        if violations:
            # Report only first and last violation to keep error concise
            first_cm = violations[0]  * INTERP_STEP_CM
            last_cm  = violations[-1] * INTERP_STEP_CM
            r.add_error(
                f"Inter-arm clearance < {MIN_ARM_CLEARANCE_CM} cm at "
                f"{len(violations)} interpolated steps "
                f"(path distance {first_cm:.1f}–{last_cm:.1f} cm along trajectory). "
                "Risk of arm collision."
            )

    def _check_procedure_arm_roles(self, plan: ProcedurePlan, r: ValidationResult) -> None:
        """Check 6: Arm roles are consistent with the declared procedure."""
        valid_roles = {
            "incision":      ({"cutting"},                    {"retracting", "holding", "idle"}),
            "biopsy":        ({"cutting"},                    {"retracting", "holding", "idle"}),
            "cauterization": ({"cutting"},                    {"retracting", "holding", "idle"}),
            "debridement":   ({"cutting"},                    {"retracting", "holding", "idle"}),
            "suturing":      ({"cutting"},                    {"retracting", "holding", "idle"}),
            "retraction":    ({"idle", "holding", "cutting"}, {"retracting"}),
            "hold":          ({"holding", "idle"},            {"holding", "idle"}),
            "home":          ({"idle"},                       {"idle"}),
            "abort":         ({"idle"},                       {"idle"}),
        }
        if plan.procedure not in valid_roles:
            r.add_warning(f"Unknown procedure type '{plan.procedure}'.")
            return

        valid_arm1_roles, valid_arm2_roles = valid_roles[plan.procedure]
        if plan.arm1.role not in valid_arm1_roles:
            r.add_warning(
                f"arm1 role='{plan.arm1.role}' unexpected for "
                f"procedure='{plan.procedure}'. Expected one of {valid_arm1_roles}."
            )
        if plan.arm2.role not in valid_arm2_roles:
            r.add_warning(
                f"arm2 role='{plan.arm2.role}' unexpected for "
                f"procedure='{plan.procedure}'. Expected one of {valid_arm2_roles}."
            )

    def _check_incision_landmark(self, plan: ProcedurePlan, r: ValidationResult) -> None:
        """
        Check 7 (incision only): The drag segment of arm1's path must pass
        within LANDMARK_TOLERANCE_CM of the declared target landmark.

        Method: find the 'plunge' and 'drag_end' waypoints in arm1.
        Compute the minimum distance from the target landmark to the line segment
        plunge→drag_end using the point-to-segment formula.
        """
        if not self._landmarks:
            r.add_warning(
                "No landmarks available — cannot verify incision target alignment."
            )
            return

        target_lm = self._resolve_incision_target(plan)
        if target_lm is None:
            r.add_warning(
                "Target landmark not detected — cannot verify incision site alignment."
            )
            return

        # Find plunge and drag_end waypoints
        wps = plan.arm1.waypoints
        plunge   = next((w for w in wps if w.label == "plunge"),   None)
        drag_end = next((w for w in wps if w.label == "drag_end"), None)

        if plunge is None or drag_end is None:
            r.add_warning(
                "Could not find 'plunge' and 'drag_end' waypoints to verify "
                "incision-landmark alignment.  Check waypoint labels."
            )
            return

        # Point-to-segment distance (2-D: XY plane only, Z excluded intentionally)
        lm = np.array([target_lm.x, target_lm.y])
        A  = np.array([plunge.x,    plunge.y])
        B  = np.array([drag_end.x,  drag_end.y])

        incision_len = float(np.linalg.norm(B - A))
        if incision_len < MIN_INCISION_LENGTH_CM:
            r.add_error(
                f"Incision length is {incision_len:.2f} cm; expected at least "
                f"{MIN_INCISION_LENGTH_CM:.2f} cm. The robot would tap instead of cut."
            )
            return

        dist = self._point_to_segment_dist_2d(lm, A, B)

        if dist > LANDMARK_TOLERANCE_CM:
            r.add_error(
                f"Incision drag segment is {dist:.2f} cm from {target_lm.name} "
                f"(tolerance={LANDMARK_TOLERANCE_CM} cm).  "
                "The incision may miss the target site."
            )
        else:
            logger.debug(
                "Incision-landmark alignment OK: dist=%.2f cm to %s.",
                dist, target_lm.name
            )

    def _check_point_procedure_landmark(self, plan: ProcedurePlan, r: ValidationResult) -> None:
        """
        Check (biopsy/cauterization): the 'plunge' waypoint must land within
        POINT_PROCEDURE_TOLERANCE_CM of the declared target landmark.
        Unlike incision, these are single-point procedures — there is no
        drag segment, so we check the plunge point directly.
        """
        if not self._landmarks:
            r.add_warning(
                "No landmarks available — cannot verify "
                f"{plan.procedure} target alignment."
            )
            return

        target_lm = self._resolve_incision_target(plan)
        if target_lm is None:
            r.add_warning(
                f"Target landmark not detected — cannot verify {plan.procedure} site alignment."
            )
            return

        plunge = next((w for w in plan.arm1.waypoints if w.label == "plunge"), None)
        if plunge is None:
            r.add_warning(
                f"Could not find 'plunge' waypoint to verify {plan.procedure}-landmark alignment."
            )
            return

        dist = math.hypot(plunge.x - target_lm.x, plunge.y - target_lm.y)
        if dist > POINT_PROCEDURE_TOLERANCE_CM:
            r.add_error(
                f"{plan.procedure} plunge point is {dist:.2f} cm from {target_lm.name} "
                f"(tolerance={POINT_PROCEDURE_TOLERANCE_CM} cm). May miss the target site."
            )
        else:
            logger.debug(
                "%s-landmark alignment OK: dist=%.2f cm to %s.",
                plan.procedure, dist, target_lm.name,
            )

    def _check_cauterization_dwell(self, plan: ProcedurePlan, r: ValidationResult) -> None:
        """
        Check (cauterization only): the 'plunge' waypoint must carry a
        dwell_s long enough to actually cauterize, not just a momentary touch.
        """
        plunge = next((w for w in plan.arm1.waypoints if w.label == "plunge"), None)
        if plunge is None:
            return
        if plunge.dwell_s < MIN_CAUTERIZATION_DWELL_S:
            r.add_error(
                f"Cauterization dwell={plunge.dwell_s:.2f}s at plunge point is below "
                f"minimum {MIN_CAUTERIZATION_DWELL_S}s — this would just be a touch, not a burn."
            )

    def _check_debridement_region(self, plan: ProcedurePlan, r: ValidationResult) -> None:
        """
        Check (debridement only): every sweep waypoint must stay within
        DEBRIDEMENT_MAX_EXTENT_CM of the declared target landmark, so the
        LLM cannot wander the sweep across the whole workspace.
        """
        if not self._landmarks:
            r.add_warning("No landmarks available — cannot verify debridement region.")
            return

        target_lm = self._resolve_incision_target(plan)
        if target_lm is None:
            r.add_warning("Target landmark not detected — cannot verify debridement region.")
            return

        sweep_wps = [w for w in plan.arm1.waypoints if w.label.startswith("sweep")]
        if not sweep_wps:
            r.add_warning("No 'sweep_*' waypoints found — cannot verify debridement coverage.")
            return

        for i, wp in enumerate(sweep_wps):
            dist = math.hypot(wp.x - target_lm.x, wp.y - target_lm.y)
            if dist > DEBRIDEMENT_MAX_EXTENT_CM:
                r.add_error(
                    f"debridement sweep point '{wp.label}' (#{i}) is {dist:.2f} cm from "
                    f"{target_lm.name} (max extent={DEBRIDEMENT_MAX_EXTENT_CM} cm)."
                )

    def _check_suturing_pattern(self, plan: ProcedurePlan, r: ValidationResult) -> None:
        """
        Check (suturing only): validates the demo stitch pattern produced by
        _repair_suturing_plan() in robosurge_cli.py.

        For every stitch found (grouped by the "stitchN_" label prefix):
          - an 'entry' and an 'exit' waypoint must both exist
          - both must stay within SUTURE_REGION_TOLERANCE_CM of the target landmark
          - the 'loop' waypoint (if present) must rise at least
            MIN_SUTURE_LOOP_HEIGHT_CM above the table — otherwise the demo
            motion is just a flat drag and doesn't read as a stitch
          - the 'cinch' waypoint (if present) must carry a dwell long enough
            to visually register as a thread-pull pause
        At least MIN_SUTURE_STITCHES stitch group must be present at all.
        """
        wps = plan.arm1.waypoints

        # Group waypoints by stitch index, e.g. "stitch1_entry" → stitch "1"
        stitch_groups: dict[str, dict[str, Waypoint]] = {}
        for wp in wps:
            if "_" not in wp.label or not wp.label.startswith("stitch"):
                continue
            stitch_id, _, step = wp.label.partition("_")
            stitch_groups.setdefault(stitch_id, {})[step] = wp

        if len(stitch_groups) < MIN_SUTURE_STITCHES:
            r.add_error(
                f"Suturing plan has {len(stitch_groups)} stitch(es); "
                f"expected at least {MIN_SUTURE_STITCHES}."
            )
            return

        target_lm = None
        if self._landmarks:
            target_lm = self._resolve_incision_target(plan)
        if target_lm is None:
            r.add_warning(
                "Target landmark not detected — cannot verify suturing site alignment."
            )

        table_z = TABLE_Z_CM

        for stitch_id, steps in sorted(stitch_groups.items()):
            entry = steps.get("entry")
            exit_ = steps.get("exit")
            loop  = steps.get("loop")
            cinch = steps.get("cinch")

            if entry is None or exit_ is None:
                r.add_error(
                    f"{stitch_id}: missing 'entry' or 'exit' waypoint — "
                    "cannot verify this stitch."
                )
                continue

            if target_lm is not None:
                for name, wp in (("entry", entry), ("exit", exit_)):
                    dist = math.hypot(wp.x - target_lm.x, wp.y - target_lm.y)
                    if dist > SUTURE_REGION_TOLERANCE_CM:
                        r.add_error(
                            f"{stitch_id} {name} point is {dist:.2f} cm from "
                            f"{target_lm.name} (tolerance={SUTURE_REGION_TOLERANCE_CM} cm)."
                        )

            if loop is not None:
                rise = loop.z - table_z
                if rise < MIN_SUTURE_LOOP_HEIGHT_CM:
                    r.add_error(
                        f"{stitch_id} loop height={rise:.2f} cm above table is below "
                        f"minimum {MIN_SUTURE_LOOP_HEIGHT_CM} cm — motion would not "
                        "visually read as a stitch passing through tissue."
                    )

            if cinch is not None and cinch.dwell_s < MIN_SUTURE_CINCH_DWELL_S:
                r.add_warning(
                    f"{stitch_id} cinch dwell={cinch.dwell_s:.2f}s is very brief — "
                    "thread-pull pause may not be visible in the demo."
                )

    def _resolve_incision_target(self, plan: ProcedurePlan) -> Optional[LandmarkState]:
        """Infer the intended target landmark from plan text or nearest plunge point."""
        haystack = f"{plan.rationale} {plan.safety_notes}".lower()
        for name, labels in {
            "landmark_A": ("landmark a", "landmark_a", "target a"),
            "landmark_B": ("landmark b", "landmark_b", "target b"),
            "landmark_C": ("landmark c", "landmark_c", "target c"),
        }.items():
            if any(label in haystack for label in labels):
                lm = next((l for l in self._landmarks if l.name == name), None)
                if lm is not None:
                    return lm

        plunge = next((w for w in plan.arm1.waypoints if w.label == "plunge"), None)
        if plunge is None:
            return next((l for l in self._landmarks if l.name == "landmark_A"), None)

        return min(
            self._landmarks,
            key=lambda l: math.hypot(l.x - plunge.x, l.y - plunge.y),
        )

    # ------------------------------------------------------------------
    # Math helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _point_to_segment_dist_2d(
        p: np.ndarray,
        a: np.ndarray,
        b: np.ndarray,
    ) -> float:
        """
        Minimum distance from point p to line segment a→b in 2-D.

        Formula:
          t = clamp( (p-a)·(b-a) / |b-a|², 0, 1 )
          closest = a + t·(b-a)
          dist    = |p - closest|
        """
        ab = b - a
        len_sq = float(np.dot(ab, ab))
        if len_sq < 1e-10:
            return float(np.linalg.norm(p - a))
        t = float(np.clip(np.dot(p - a, ab) / len_sq, 0.0, 1.0))
        closest = a + t * ab
        return float(np.linalg.norm(p - closest))

    @staticmethod
    def _interpolate_path(
        waypoints: list[Waypoint],
    ) -> list[tuple[float, float, float]]:
        """
        Linear interpolation of a waypoint list at INTERP_STEP_CM resolution.

        Returns a list of (x, y, z) tuples.
        """
        if not waypoints:
            return []
        if len(waypoints) == 1:
            return [(waypoints[0].x, waypoints[0].y, waypoints[0].z)]

        path: list[tuple[float, float, float]] = []
        for i in range(len(waypoints) - 1):
            a = waypoints[i]
            b = waypoints[i + 1]
            seg_len = math.sqrt((b.x-a.x)**2 + (b.y-a.y)**2 + (b.z-a.z)**2)
            n_steps = max(1, int(seg_len / INTERP_STEP_CM))
            for j in range(n_steps):
                t = j / n_steps
                path.append((
                    a.x + t * (b.x - a.x),
                    a.y + t * (b.y - a.y),
                    a.z + t * (b.z - a.z),
                ))
        last = waypoints[-1]
        path.append((last.x, last.y, last.z))
        return path


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    from .surgical_agent import ArmPlan, ProcedurePlan, Waypoint
    from .scene_state import LandmarkState

    # Test: valid 3mm incision at landmark_A = (11.0, 1.0)
    good_plan = ProcedurePlan(
        procedure="incision",
        rationale="3mm incision at landmark_A",
        arm1=ArmPlan(arm_id=1, role="cutting", feed_rate_mm_s=2.0, waypoints=[
            Waypoint(x=11.0, y=1.0, z=10.0, label="transit"),
            Waypoint(x=11.0, y=1.0, z=7.7,  label="approach"),
            Waypoint(x=11.0, y=1.0, z=7.35, label="plunge"),
            Waypoint(x=11.3, y=1.0, z=7.35, label="drag_end"),
            Waypoint(x=11.3, y=1.0, z=10.0, label="retract"),
        ]),
        arm2=ArmPlan(arm_id=2, role="retracting", feed_rate_mm_s=8.0, waypoints=[
            Waypoint(x=11.0, y=4.0, z=7.5, label="hold"),
        ]),
        estimated_duration_s=12.0,
        safety_notes="",
    )

    # Test: bad plan with Z violation and arm collision
    bad_plan = ProcedurePlan(
        procedure="incision",
        rationale="bad plan",
        arm1=ArmPlan(arm_id=1, role="cutting", feed_rate_mm_s=2.0, waypoints=[
            Waypoint(x=11.0, y=1.0, z=10.0, label="transit"),
            Waypoint(x=11.0, y=1.0, z=6.0,  label="plunge"),   # Z too low
            Waypoint(x=11.3, y=1.0, z=6.0,  label="drag_end"),
        ]),
        arm2=ArmPlan(arm_id=2, role="retracting", feed_rate_mm_s=8.0, waypoints=[
            Waypoint(x=11.0, y=1.0, z=7.5, label="hold"),   # same XY as arm1 → collision
        ]),
        estimated_duration_s=5.0,
        safety_notes="",
    )

    landmarks = [LandmarkState(name="landmark_A", x=11.0, y=1.0, z=7.5, confidence=0.92)]
    validator = ProcedureValidator(landmarks=landmarks)

    print("=== GOOD PLAN ===")
    print(validator.validate(good_plan).summary())
    print("\n=== BAD PLAN ===")
    print(validator.validate(bad_plan).summary())