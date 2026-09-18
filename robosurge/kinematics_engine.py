"""
kinematics_engine.py — RoboSurge Phase 2
=========================================
Forward Kinematics engine for a 3-DOF planar arm mounted on a fixed base tower.

Coordinate frame convention
----------------------------
  Origin  : Bottom-center of the base tower, at the table surface (z = 0).
  X-axis  : Points "forward" away from the robot base (positive = away from chassis).
  Y-axis  : Points left when viewed from above (right-hand rule, X cross Z → Y).
  Z-axis  : Points straight up.

Physical constants
------------------
  BASE_HEIGHT  = 7.5 cm   — The pivot point (shoulder) is elevated off the table.
  L1           = 9.5 cm   — Shoulder-to-elbow rigid link.
  L2           = 12.0 cm  — Elbow-to-tip rigid link.
  MAX_REACH    = 21.5 cm  — Full extension (L1 + L2); hard hardware limit.
  MIN_REACH    = 2.5 cm   — Blind-spot radius; arm cannot safely enter this zone.

Joint definitions (DH-compatible numbering)
-------------------------------------------
  Joint 0 — Base Pan     : Revolute, rotates around global +Z axis.
                           θ=0 → arm points along +X.
  Joint 1 — Shoulder Pitch: Revolute, rotates around the shoulder's local Y axis.
                           θ=0 → link L1 is horizontal (parallel to table).
                           Positive angle elevates the elbow above the table.
  Joint 2 — Elbow Pitch  : Revolute, rotates around the elbow's local Y axis.
                           θ=0 → link L2 is co-linear with L1 (full extension).
                           Positive angle bends the tip toward the base.

DH parameter table (standard convention: Rz(θ) · Tz(d) · Tx(a) · Rx(α))
--------------------------------------------------------------------------
  Frame | θ              | d            | a    | α
  ------+----------------+--------------+------+------
    0   | base_angle     | BASE_HEIGHT  | 0    | 0
    1   | shoulder_angle | 0            | L1   | 0
    2   | elbow_angle    | 0            | L2   | 0

Because all twist angles α = 0 and all offsets d (after frame 0) = 0, the
kinematics reduce to standard 2-D planar trigonometry applied after the base
pan rotation — this is cross-verified below.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

import numpy as np


# ---------------------------------------------------------------------------
# Physical constants (centimetres throughout this module)
# ---------------------------------------------------------------------------

BASE_HEIGHT: Final[float] = 7.5    # cm — shoulder pivot above table origin
L1: Final[float] = 9.5             # cm — shoulder-to-elbow
L2: Final[float] = 12.0            # cm — elbow-to-tip
MAX_REACH: Final[float] = L1 + L2  # 21.5 cm
MIN_REACH: Final[float] = 2.5      # cm


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class FKResult:
    """
    Immutable snapshot of a forward-kinematics solution.

    Attributes
    ----------
    tip_x, tip_y, tip_z : float
        End-effector tip position in the global coordinate frame (cm).
    elbow_x, elbow_y, elbow_z : float
        Elbow joint position in the global coordinate frame (cm).
    reach_xy : float
        Horizontal distance from the base pan axis to the tip (cm).
        Used for reach-limit checking without redundant recalculation.
    in_reachable_workspace : bool
        True if MIN_REACH ≤ reach_xy ≤ MAX_REACH.
    """
    tip_x: float
    tip_y: float
    tip_z: float
    elbow_x: float
    elbow_y: float
    elbow_z: float
    reach_xy: float
    in_reachable_workspace: bool

    def tip_position(self) -> tuple[float, float, float]:
        """Return tip (x, y, z) as a plain tuple."""
        return (self.tip_x, self.tip_y, self.tip_z)

    def elbow_position(self) -> tuple[float, float, float]:
        """Return elbow (x, y, z) as a plain tuple."""
        return (self.elbow_x, self.elbow_y, self.elbow_z)


# ---------------------------------------------------------------------------
# ForwardKinematics class
# ---------------------------------------------------------------------------

class ForwardKinematics:
    """
    Forward Kinematics solver for the RoboSurge 3-DOF arm.

    The solver uses the product-of-transforms (homogeneous matrices) approach
    so that it can be audited step-by-step and later extended to 6-DOF without
    rewriting the core logic.

    Usage
    -----
    >>> fk = ForwardKinematics()
    >>> result = fk.calculate_fk(base_angle=30.0, shoulder_angle=45.0, elbow_angle=-20.0)
    >>> print(result.tip_position())
    """

    def __init__(self) -> None:
        # Expose constants as instance attributes for external inspection
        self.base_height: float = BASE_HEIGHT
        self.l1: float = L1
        self.l2: float = L2
        self.max_reach: float = MAX_REACH
        self.min_reach: float = MIN_REACH

    # ------------------------------------------------------------------
    # Private helpers: homogeneous transform primitives
    # ------------------------------------------------------------------

    @staticmethod
    def _rot_z(theta_deg: float) -> np.ndarray:
        """
        4×4 homogeneous rotation matrix about the Z-axis.

        R_z(θ) = | cos θ  -sin θ  0  0 |
                 | sin θ   cos θ  0  0 |
                 |   0       0    1  0 |
                 |   0       0    0  1 |
        """
        c = math.cos(math.radians(theta_deg))
        s = math.sin(math.radians(theta_deg))
        return np.array([
            [c, -s, 0.0, 0.0],
            [s,  c, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ], dtype=np.float64)

    @staticmethod
    def _rot_y(theta_deg: float) -> np.ndarray:
        """
        4×4 homogeneous rotation matrix about the Y-axis.

        R_y(θ) = |  cos θ  0  sin θ  0 |
                 |    0    1    0    0 |
                 | -sin θ  0  cos θ  0 |
                 |    0    0    0    1 |
        """
        c = math.cos(math.radians(theta_deg))
        s = math.sin(math.radians(theta_deg))
        return np.array([
            [c,   0.0, s,   0.0],
            [0.0, 1.0, 0.0, 0.0],
            [-s,  0.0, c,   0.0],
            [0.0, 0.0, 0.0, 1.0],
        ], dtype=np.float64)

    @staticmethod
    def _trans(dx: float, dy: float, dz: float) -> np.ndarray:
        """
        4×4 homogeneous pure-translation matrix.

        T(dx, dy, dz) = | 1  0  0  dx |
                        | 0  1  0  dy |
                        | 0  0  1  dz |
                        | 0  0  0   1 |
        """
        return np.array([
            [1.0, 0.0, 0.0, dx],
            [0.0, 1.0, 0.0, dy],
            [0.0, 0.0, 1.0, dz],
            [0.0, 0.0, 0.0, 1.0],
        ], dtype=np.float64)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def calculate_fk(
        self,
        base_angle: float,
        shoulder_angle: float,
        elbow_angle: float,
    ) -> FKResult:
        """
        Compute the forward kinematics for the RoboSurge arm.

        Parameters
        ----------
        base_angle : float
            Rotation of Joint 0 (base pan) about the global Z-axis, in degrees.
            0° → arm points along +X.  Positive → counter-clockwise from above.
        shoulder_angle : float
            Rotation of Joint 1 (shoulder pitch) about its local Y-axis, in degrees.
            0° → link L1 is horizontal.  Positive → elbow rises above table.
        elbow_angle : float
            Rotation of Joint 2 (elbow pitch) about its local Y-axis, in degrees.
            0° → link L2 continues co-linearly with L1 (full extension).
            Positive → tip bends back toward base.

        Returns
        -------
        FKResult
            Complete spatial state of the arm including tip and elbow positions.

        Math derivation
        ---------------
        We build four frames:

          T_world_base : Lifts the origin from the table to the shoulder pivot
                         (pure translation +Z by BASE_HEIGHT).

          T_base_shoulder : Applies the base pan rotation (Rz(base_angle)).

          T_shoulder_elbow : Applies shoulder pitch (Ry(shoulder_angle)) then
                             translates along the resulting local X-axis by L1.
                             This places the origin at the elbow joint.

          T_elbow_tip : Applies elbow pitch (Ry(elbow_angle)) then translates
                        along local X by L2.  This places the origin at the tip.

        The full chain is:
          T_world_tip = T_world_base @ T_base_shoulder @ T_shoulder_elbow @ T_elbow_tip

        Cross-check (scalar form for base_angle=0):
          elbow_x = L1 * cos(shoulder)
          elbow_z = BASE_HEIGHT + L1 * sin(shoulder)
          tip_x   = elbow_x + L2 * cos(shoulder + elbow)
          tip_z   = elbow_z + L2 * sin(shoulder + elbow)
        """

        # --- Frame 0→1: Elevate to shoulder pivot height ---
        # The shoulder is physically elevated; all subsequent joint transforms
        # happen relative to this elevated origin.
        T_world_base = self._trans(0.0, 0.0, BASE_HEIGHT)

        # --- Frame 1→2: Base pan (yaw) about Z ---
        # After this transform, the local +X axis points in the direction the
        # arm is panning toward.
        T_base_shoulder = self._rot_z(base_angle)

        # --- Frame 2→3: Shoulder pitch about local Y, then link L1 along local X ---
        # Ry(shoulder_angle) tilts the arm up/down.
        # The subsequent translation moves us from shoulder to elbow along the
        # rotated local X-axis (i.e., along the first rigid link).
        T_shoulder_elbow = self._rot_y(shoulder_angle) @ self._trans(L1, 0.0, 0.0)

        # --- Frame 3→4: Elbow pitch about local Y, then link L2 along local X ---
        # Same pattern: rotate at the joint, then move along the link.
        T_elbow_tip = self._rot_y(elbow_angle) @ self._trans(L2, 0.0, 0.0)

        # --- Accumulate the full transform chain ---
        T_world_elbow = T_world_base @ T_base_shoulder @ T_shoulder_elbow
        T_world_tip   = T_world_elbow @ T_elbow_tip

        # --- Extract positions from the last column of each homogeneous matrix ---
        # A homogeneous transform T has the form:
        #   | R  p |    where p = T[:3, 3] is the origin of that frame in world coords.
        #   | 0  1 |
        elbow_pos: np.ndarray = T_world_elbow[:3, 3]
        tip_pos:   np.ndarray = T_world_tip[:3, 3]

        # --- Reach check ---
        reach_xy = math.hypot(float(tip_pos[0]), float(tip_pos[1]))
        in_workspace = MIN_REACH <= reach_xy <= MAX_REACH

        return FKResult(
            tip_x=float(tip_pos[0]),
            tip_y=float(tip_pos[1]),
            tip_z=float(tip_pos[2]),
            elbow_x=float(elbow_pos[0]),
            elbow_y=float(elbow_pos[1]),
            elbow_z=float(elbow_pos[2]),
            reach_xy=reach_xy,
            in_reachable_workspace=in_workspace,
        )

    def batch_calculate_fk(
        self,
        angle_triplets: list[tuple[float, float, float]],
    ) -> list[FKResult]:
        """
        Vectorised-style convenience wrapper: compute FK for a list of
        (base, shoulder, elbow) angle triplets.

        Parameters
        ----------
        angle_triplets : list of (base_angle, shoulder_angle, elbow_angle)

        Returns
        -------
        list[FKResult]
        """
        return [self.calculate_fk(*angles) for angles in angle_triplets]

    def scalar_cross_check(
        self,
        base_angle: float,
        shoulder_angle: float,
        elbow_angle: float,
    ) -> tuple[float, float, float]:
        """
        Independent scalar derivation of tip (x, y, z) for unit-test verification.

        This uses pure trigonometry rather than matrix multiplication, so that
        the two implementations can be compared numerically to detect bugs in
        either path.

        When base_angle = 0:
          tip_x = (L1·cos(θ1) + L2·cos(θ1+θ2))
          tip_y = 0
          tip_z = BASE_HEIGHT + (L1·sin(θ1) + L2·sin(θ1+θ2))

        For arbitrary base_angle (φ), the horizontal projection is rotated:
          horizontal_reach = L1·cos(θ1) + L2·cos(θ1+θ2)
          tip_x = horizontal_reach · cos(φ)
          tip_y = horizontal_reach · sin(φ)
          tip_z = BASE_HEIGHT + L1·sin(θ1) + L2·sin(θ1+θ2)
        """
        phi   = math.radians(base_angle)
        theta1 = math.radians(shoulder_angle)
        theta2 = math.radians(elbow_angle)

        # Planar arm kinematics (in the arm's own sagittal plane before base rotation)
        horizontal_reach = L1 * math.cos(theta1) + L2 * math.cos(theta1 + theta2)
        vertical_rise    = L1 * math.sin(theta1) + L2 * math.sin(theta1 + theta2)

        tip_x = horizontal_reach * math.cos(phi)
        tip_y = horizontal_reach * math.sin(phi)
        tip_z = BASE_HEIGHT + vertical_rise

        return (tip_x, tip_y, tip_z)


# ---------------------------------------------------------------------------
# Standalone smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    fk = ForwardKinematics()

    test_cases: list[tuple[float, float, float]] = [
        (0.0,   0.0,   0.0),    # Straight out, horizontal — expect tip at (21.5, 0, 7.5)
        (0.0,  90.0,   0.0),    # Arm pointing straight up — expect tip near (0, 0, ~29)
        (90.0,  0.0,   0.0),    # Panned 90°, horizontal — expect tip at (0, 21.5, 7.5)
        (45.0, 30.0, -20.0),    # Mixed configuration
    ]

    print(f"{'Base':>6}  {'Shoulder':>8}  {'Elbow':>6}  "
          f"{'tip_x':>8}  {'tip_y':>8}  {'tip_z':>8}  "
          f"{'scalar_x':>9}  {'scalar_y':>9}  {'scalar_z':>9}  {'dmax':>8}")
    print("-" * 105)

    for base, shoulder, elbow in test_cases:
        result = fk.calculate_fk(base, shoulder, elbow)
        sx, sy, sz = fk.scalar_cross_check(base, shoulder, elbow)

        delta_max = max(
            abs(result.tip_x - sx),
            abs(result.tip_y - sy),
            abs(result.tip_z - sz),
        )

        print(f"{base:6.1f}  {shoulder:8.1f}  {elbow:6.1f}  "
              f"{result.tip_x:8.4f}  {result.tip_y:8.4f}  {result.tip_z:8.4f}  "
              f"{sx:9.4f}  {sy:9.4f}  {sz:9.4f}  {delta_max:8.2e}")
