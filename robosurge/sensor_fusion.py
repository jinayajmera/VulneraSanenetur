"""
sensor_fusion.py — RoboSurge Phase 3
======================================
Vision-to-Hardware bridge: converts YOLOv8-pose tip detections into physical
(X, Y, Z) coordinates via a planar homography, then streams IK commands to
the ESP32 over serial at ~10 Hz.

Data-flow (Phase 3 — inverted from Phase 2)
--------------------------------------------

  Camera
    │
    ▼
  PoseTracker.process_frame()
    │  list[ArmPoseResult]  — raw pixel detections, 0-N arms
    ▼
  filter_and_sort_arms()
    │  drop tip_pixel=None; sort L→R by pixel-X; cap at 2 arms
    ▼
  HomographyMapper.pixel_to_physical()
    │  (u, v)  →  (X_cm, Y_cm),  Z hardcoded to BASE_HEIGHT
    ▼
  build_serial_command()
    │  "arm1 X Y Z\n"  /  "arm2 X Y Z\n"
    ▼
  serial.Serial.write()  →  ESP32 (IK runs on-chip)

Serial command format (Python → ESP32)
----------------------------------------
  "arm<id> <X> <Y> <Z>\n"
  where <id> ∈ {1, 2}, X/Y in cm (2 d.p.), Z = 7.50 (fixed)

  Example:
    "arm1 +12.34 -3.21 7.50\n"
    "arm2 +8.10 +5.67 7.50\n"

Left/Right assignment
----------------------
  Arms are sorted by their tip_pixel X-coordinate (ascending = left-to-right
  in image space).  Leftmost detection → arm1, next → arm2.
  If the camera is mounted with a mirrored orientation, flip the sort to
  reverse=True in filter_and_sort_arms().

Homography
----------
  A 3×3 cv2.findHomography matrix maps pixel space → centimetre space on the
  table plane.  Computed once at startup from CALIBRATION_PIXEL_PTS and
  CALIBRATION_PHYSICAL_PTS.  Replace the hardcoded constants with measured
  values once the camera mount is fixed.
"""

from __future__ import annotations

import logging
import math
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import serial

from .vision_pipeline import ArmPoseResult, PoseTracker

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("SensorFusion")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SERIAL_PORT:    str   = "COM5"   # CP210x USB-UART; COM6/COM7 are Bluetooth here
SERIAL_BAUD:    int   = 115200
SERIAL_TIMEOUT: float = 0.02     # 20 ms write timeout — keeps the loop non-blocking
LOOP_RATE_HZ:   float = 10.0
# Was previously a local hardcoded copy (7.5, "Table surface = BASE_HEIGHT")
# that was never validated against the real firmware and silently drifted
# out of sync with scene_state.py. Now imports the single source of truth.
from .scene_state import TABLE_Z_CM as FIXED_Z_CM
MAX_ARMS:       int   = 2

# ---------------------------------------------------------------------------
# Calibration  ← REPLACE WITH MEASURED VALUES BEFORE DEPLOYMENT
# ---------------------------------------------------------------------------
# Procedure:
#   1. Place a visible marker at each (X, Y) position on the table.
#   2. Open a single camera frame and record the pixel centroid of each marker.
#   3. Replace the values below and restart.
#
# Physical frame: origin = base-tower bottom-centre, X=forward, Y=left (cm).
# Pixel frame:    top-left = (0,0), u=column, v=row  (1280×720).
#
# The 4 corners below span a 16 cm × 12 cm rectangle ~10 cm in front of
# the robot.  All values are APPROXIMATE for initial wiring validation.

CALIBRATION_PHYSICAL_PTS = [(5.0, 0.0), (8.0, 6.0), (11.0, -6.0), (11.0, 0.0), (11.0, 3.0), (11.0, 6.0), (14.0, -6.0), (14.0, -3.0), (14.0, 0.0), (14.0, 3.0), (14.0, 6.0), (17.0, -6.0), (17.0, -3.0), (17.0, 0.0), (17.0, 3.0)]
CALIBRATION_PIXEL_PTS    = [(435.0, 477.0), (545.0, 401.0), (506.0, 528.0), (532.5, 446.0), (574.0, 439.5), (564.0, 400.0), (561.0, 493.0), (571.0, 476.0), (599.0, 455.0), (611.0, 436.0), (590.0, 378.0), (606.0, 409.0), (618.0, 411.0), (632.0, 415.0), (633.0, 390.0)]

# ---------------------------------------------------------------------------
# ANSI colour helpers
# ---------------------------------------------------------------------------

_R    = "\033[0m"
_BOLD = "\033[1m"
_DIM  = "\033[2m"
_GRN  = "\033[92m"
_YLW  = "\033[93m"
_RED  = "\033[91m"
_CYN  = "\033[96m"
_MAG  = "\033[95m"

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

def _visible_len(s: str) -> int:
    """Length of string excluding ANSI escape codes."""
    return len(_ANSI_RE.sub("", s))

def _pad(s: str, width: int = 76) -> str:
    """Right-pad with spaces to fixed visible width, clearing stale characters."""
    return s + " " * max(0, width - _visible_len(s))


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class AssignedArm:
    """
    One arm after L/R assignment and pixel→physical conversion.

    Attributes
    ----------
    arm_id : int
        1 = left arm, 2 = right arm (as expected by ESP32 firmware).
    tip_pixel : tuple[int, int]
        Raw pixel coordinate of the surgical tip.
    physical_x, physical_y, physical_z : float
        Homography-projected table coordinates in cm.
        Z is always FIXED_Z_CM (7.5 cm).
    serial_command : str
        Fully-formatted string ready to write to the serial port,
        e.g. ``"arm1 +12.34 -3.21 7.50\n"``.
    """
    arm_id:         int
    tip_pixel:      tuple[int, int]
    physical_x:     float
    physical_y:     float
    physical_z:     float
    serial_command: str


# ---------------------------------------------------------------------------
# HomographyMapper
# ---------------------------------------------------------------------------

class HomographyMapper:
    """
    Wraps a single cv2.findHomography call and exposes pixel_to_physical().

    The homography H satisfies:
        [X', Y', w]ᵀ = H · [u, v, 1]ᵀ
        X_cm = X'/w,  Y_cm = Y'/w

    Source (src) = pixel coords, destination (dst) = physical cm coords.
    RANSAC is used with reprojThreshold=0.5 px so a single mis-clicked
    calibration point does not corrupt the matrix.

    Parameters
    ----------
    physical_pts : list of (X, Y) in cm — where each marker physically sits.
    pixel_pts    : list of (u, v)       — observed pixel centroid of each marker.
    """

    def __init__(
        self,
        physical_pts: list[tuple[float, float]],
        pixel_pts:    list[tuple[float, float]],
    ) -> None:
        self._H: np.ndarray = self._compute(physical_pts, pixel_pts)
        logger.info("Homography ready:\n%s", np.array2string(self._H, precision=5))

    # ------------------------------------------------------------------

    @staticmethod
    def _compute(
        physical_pts: list[tuple[float, float]],
        pixel_pts:    list[tuple[float, float]],
    ) -> np.ndarray:
        if len(physical_pts) < 4 or len(pixel_pts) < 4:
            raise ValueError(
                f"findHomography requires ≥4 point pairs; "
                f"got {len(physical_pts)} physical and {len(pixel_pts)} pixel."
            )
        if len(physical_pts) != len(pixel_pts):
            raise ValueError("physical_pts and pixel_pts must be the same length.")

        src = np.array(pixel_pts,    dtype=np.float64).reshape(-1, 1, 2)
        dst = np.array(physical_pts, dtype=np.float64).reshape(-1, 1, 2)

        H, mask = cv2.findHomography(src, dst, cv2.RANSAC, ransacReprojThreshold=0.5)
        if H is None:
            raise RuntimeError(
                "cv2.findHomography returned None.  "
                "Verify that calibration points are non-collinear and "
                "that pixel coordinates are accurate."
            )
        n_in = int(np.sum(mask)) if mask is not None else len(pixel_pts)
        logger.info("Homography RANSAC: %d / %d inliers.", n_in, len(pixel_pts))
        return H

    def recalibrate(
        self,
        physical_pts: list[tuple[float, float]],
        pixel_pts:    list[tuple[float, float]],
    ) -> None:
        """Hot-swap the homography without restarting the loop."""
        self._H = self._compute(physical_pts, pixel_pts)
        logger.info("Homography recalibrated.")

    def pixel_to_physical(self, u: float, v: float) -> tuple[float, float]:
        """
        Project one pixel observation into physical table-plane coordinates.

        Parameters
        ----------
        u : float — pixel column.
        v : float — pixel row.

        Returns
        -------
        (X_cm, Y_cm) : tuple[float, float]
        """
        pt     = np.array([[[u, v]]], dtype=np.float64)   # (1, 1, 2)
        warped = cv2.perspectiveTransform(pt, self._H)     # (1, 1, 2)
        return (float(warped[0, 0, 0]), float(warped[0, 0, 1]))


# ---------------------------------------------------------------------------
# LocalAffineMapper — piecewise-local replacement for HomographyMapper
# ---------------------------------------------------------------------------
#
# Why this exists: a single global homography assumes the pixel→physical
# relationship is one consistent planar transform everywhere in the
# workspace. That assumption breaks if the underlying IK doesn't move the
# arm by a uniform/linear amount across the workspace (confirmed here —
# firmware L1=12.0 vs. the physical arm's real link length means error is
# pose-dependent: some calibration points reprojected at 0.00cm, others at
# 6cm+, with no global plane reconciling both). A global fit can't average
# that away; it just gets dragged toward whichever points RANSAC favors.
#
# LocalAffineMapper instead fits a FRESH small affine transform from the K
# nearest calibration points every time pixel_to_physical() is called. Each
# neighborhood of the workspace effectively gets its own local correction,
# so it can absorb pose-dependent IK error that varies by region — at the
# cost of needing denser, well-spread calibration coverage (sparse areas
# fall back on a less-local, less-accurate fit).
# ---------------------------------------------------------------------------

class LocalAffineMapper:
    """
    Piecewise-local pixel -> physical mapper.

    Same public interface as HomographyMapper (pixel_to_physical, recalibrate)
    so it's a drop-in replacement everywhere HomographyMapper was used.

    Parameters
    ----------
    physical_pts : list of (X, Y) in cm.
    pixel_pts    : list of (u, v) pixel centroids, same order/length.
    k : int
        Number of nearest calibration points used to fit each local affine
        transform. More k = smoother but less local; fewer k = more local
        but noisier if points are sparse. 5-6 is a reasonable default for
        a grid with 16-25 calibration points.
    """

    def __init__(
        self,
        physical_pts: list[tuple[float, float]],
        pixel_pts:    list[tuple[float, float]],
        k: int = 6,
    ) -> None:
        self._k = k
        self.recalibrate(physical_pts, pixel_pts)

    def recalibrate(
        self,
        physical_pts: list[tuple[float, float]],
        pixel_pts:    list[tuple[float, float]],
    ) -> None:
        """Hot-swap the calibration point set without restarting the loop."""
        if len(physical_pts) != len(pixel_pts):
            raise ValueError("physical_pts and pixel_pts must be the same length.")
        if len(physical_pts) < self._k + 1:
            raise ValueError(
                f"LocalAffineMapper needs at least k+1={self._k + 1} calibration "
                f"points (k={self._k} neighbors + the query itself when doing "
                f"leave-one-out validation); got {len(physical_pts)}. Either "
                "collect more calibration points or lower k."
            )
        self._phys = np.asarray(physical_pts, dtype=np.float64)  # (N, 2)
        self._pix  = np.asarray(pixel_pts,    dtype=np.float64)  # (N, 2)
        design_all = np.hstack([self._pix, np.ones((len(self._pix), 1))])
        self._A_global, *_ = np.linalg.lstsq(design_all, self._phys, rcond=None)
        logger.info(
            "LocalAffineMapper ready: %d calibration points, k=%d neighbors.",
            len(self._pix), self._k,
        )

    def _fit_local_affine(
        self,
        u: float,
        v: float,
        exclude_idx: Optional[int] = None,
    ) -> np.ndarray:
        """
        Fit [x, y] = [u, v, 1] @ A using the k nearest calibration points to
        (u, v), inverse-distance weighted. Returns A, shape (3, 2).

        exclude_idx lets leave_one_out_errors() ask "what would this point's
        own prediction look like using only the OTHER points" — i.e. a fair
        out-of-sample check, not the trivially-near-zero in-sample fit a
        local model would otherwise report.
        """
        query = np.array([u, v], dtype=np.float64)
        dist = np.linalg.norm(self._pix - query, axis=1)
        if exclude_idx is not None:
            dist = dist.copy()
            dist[exclude_idx] = np.inf

        k = min(self._k, np.sum(np.isfinite(dist)) - 0 if exclude_idx is None else len(dist) - 1)
        idx = np.argsort(dist)[:k]

        pix_local  = self._pix[idx]
        phys_local = self._phys[idx]
        weights    = 1.0 / np.maximum(dist[idx], 1e-6)
        weights    = weights / weights.sum()

        design = np.hstack([pix_local, np.ones((len(idx), 1))])   # (k, 3)
        Wd     = design * weights[:, None]
        Wt     = phys_local * weights[:, None]

        try:
            A, *_ = np.linalg.lstsq(Wd, Wt, rcond=None)
        except np.linalg.LinAlgError:
            # Degenerate neighborhood (e.g. collinear points) — fall back to
            # an unweighted fit over the same neighbors rather than crashing.
            A, *_ = np.linalg.lstsq(design, phys_local, rcond=None)
        return A   # (3, 2)

    def pixel_to_physical(self, u: float, v: float) -> tuple[float, float]:
        """Project one pixel observation into physical table-plane cm."""
        query = np.array([u, v], dtype=np.float64)
        min_dist = float(np.min(np.linalg.norm(self._pix - query, axis=1)))
        
        A_local = self._fit_local_affine(u, v)
        vec     = np.array([u, v, 1.0], dtype=np.float64)
        local_xy = vec @ A_local
        global_xy = vec @ self._A_global
        
        # Smoothly blend local fit with global affine if outside nearest cluster
        blend = float(np.clip((min_dist - 60.0) / 120.0, 0.0, 1.0))
        out = (1.0 - blend) * local_xy + blend * global_xy
        return (float(out[0]), float(out[1]))

    def leave_one_out_errors(self) -> list[float]:
        """
        For each calibration point, predict its physical position using
        only the OTHER calibration points, and return the resulting error
        (cm) per point. This is the honest accuracy metric for a local
        model — reprojecting training points against themselves would
        look near-perfect and tell you nothing about how it behaves on a
        landmark that wasn't a calibration point.
        """
        errors = []
        for i in range(len(self._pix)):
            u, v = self._pix[i]
            A    = self._fit_local_affine(float(u), float(v), exclude_idx=i)
            pred = np.array([u, v, 1.0], dtype=np.float64) @ A
            errors.append(float(np.linalg.norm(pred - self._phys[i])))
        return errors



# ---------------------------------------------------------------------------
# Arm assignment helpers  (pure functions — easy to unit-test)
# ---------------------------------------------------------------------------

def filter_and_sort_arms(detections: list[ArmPoseResult]) -> list[ArmPoseResult]:
    """
    Prepare raw detections for assignment.

    Steps
    -----
    1. Drop entries with tip_pixel=None (arm occluded or below conf threshold).
    2. Sort survivors left-to-right by pixel-X (ascending).
    3. Truncate to MAX_ARMS (2) — if 3+ arms are spuriously detected, discard
       lower-confidence rightmost extras.

    Parameters
    ----------
    detections : list[ArmPoseResult]
        Direct output of PoseTracker.process_frame().

    Returns
    -------
    list[ArmPoseResult] — 0–2 elements, sorted left-to-right.
    """
    visible = [d for d in detections if d.tip_pixel is not None]
    sorted_arms = sorted(visible, key=lambda d: d.tip_pixel[0])  # type: ignore[index]
    return sorted_arms[:MAX_ARMS]


def build_serial_command(arm_id: int, x: float, y: float, z: float) -> str:
    """
    Format the command string the ESP32 IK firmware expects.

    Output  →  ``"arm<id> <X> <Y> <Z>\n"``
    Values are 2 d.p.; X and Y carry an explicit sign for unambiguous parsing.

    Examples
    --------
    >>> build_serial_command(1, 12.3456, -3.211, 7.5)
    'arm1 +12.35 -3.21 7.50\n'
    """
    return f"arm{arm_id} {x:+.2f} {y:+.2f} {z:.2f}\n"


def assign_arms(
    detections: list[ArmPoseResult],
    mapper:     "LocalAffineMapper | HomographyMapper",
) -> list[AssignedArm]:
    """
    Full pipeline: raw detections → AssignedArm objects with serial commands.

    arm_id assignment:
        sorted_index 0  →  arm_id = 1  (leftmost  = left  surgical arm)
        sorted_index 1  →  arm_id = 2  (next left = right surgical arm)

    Parameters
    ----------
    detections : list[ArmPoseResult]  — from PoseTracker.process_frame()
    mapper     : LocalAffineMapper (default) or HomographyMapper — calibrated,
                 anything exposing pixel_to_physical(u, v) -> (x, y) works.

    Returns
    -------
    list[AssignedArm] — up to 2 elements.
    """
    sorted_arms = filter_and_sort_arms(detections)
    result: list[AssignedArm] = []

    for idx, pose in enumerate(sorted_arms):
        arm_id     = idx + 1
        u, v       = pose.tip_pixel  # type: ignore[misc]  — None filtered above
        x_cm, y_cm = mapper.pixel_to_physical(float(u), float(v))
        cmd        = build_serial_command(arm_id, x_cm, y_cm, FIXED_Z_CM)

        result.append(AssignedArm(
            arm_id=arm_id,
            tip_pixel=(u, v),
            physical_x=x_cm,
            physical_y=y_cm,
            physical_z=FIXED_Z_CM,
            serial_command=cmd,
        ))

    return result


# ---------------------------------------------------------------------------
# Terminal renderer  (fixed-height overwrite block)
# ---------------------------------------------------------------------------

_ARM_COL = {1: _CYN, 2: _MAG}
_BLOCK_LINES = 6   # number of lines _render_frame writes; must stay constant


def _render_frame(
    assigned:         list[AssignedArm],
    total_detections: int,
    serial_ok:        bool,
    loop_ms:          float,
    *,
    first_frame:      bool = False,
) -> None:
    """
    Overwrite a fixed 6-line terminal block with the current fusion state.

    Block layout
    ------------
      ── Arm 1 ────────────────────────────────────────────────────
        pixel=(  640,  360)   X=+10.12 cm   Y= +2.34 cm   → "arm1 +10.12 +2.34 7.50"
      ── Arm 2 ────────────────────────────────────────────────────
        pixel=( 1020,  360)   X= +8.55 cm   Y= -1.10 cm   → "arm2 +8.55 -1.10 7.50"
      ─────────────────────────────────────────────────────────────
        detections=2  visible=2  serial=OK  loop=11.2 ms

    On the first call we do NOT move the cursor up (the block doesn't exist yet).
    """
    if not first_frame:
        print(f"\033[{_BLOCK_LINES}A", end="")  # move cursor up to overwrite

    def _arm_line(arm_id: int) -> str:
        col   = _ARM_COL.get(arm_id, _CYN)
        match = next((a for a in assigned if a.arm_id == arm_id), None)
        if match:
            cmd_preview = match.serial_command.rstrip("\n")
            return _pad(
                f"{col}{_BOLD}  Arm {arm_id}{_R}  "
                f"pixel=({match.tip_pixel[0]:4d},{match.tip_pixel[1]:4d})  "
                f"X={match.physical_x:+7.2f} cm  "
                f"Y={match.physical_y:+7.2f} cm  "
                f"{_DIM}→{_R}  {_GRN}\"{cmd_preview}\"{_R}"
            )
        return _pad(
            f"{_YLW}  Arm {arm_id}{_R}  "
            f"{_DIM}--- not detected ---                                       {_R}"
        )

    serial_tag = f"{_GRN}OK{_R}" if serial_ok else f"{_RED}DISCONNECTED (dry-run){_R}"
    status = _pad(
        f"  {_DIM}detections={total_detections}  visible={len(assigned)}  "
        f"serial={_R}{serial_tag}  "
        f"{_DIM}loop={loop_ms:.1f} ms{_R}"
    )

    print(_pad(f"  {_DIM}{'─' * 72}{_R}"))
    print(_arm_line(1))
    print(_pad(f"  {_DIM}{'─' * 72}{_R}"))
    print(_arm_line(2))
    print(_pad(f"  {_DIM}{'─' * 72}{_R}"))
    print(status)


# ---------------------------------------------------------------------------
# FusionBridge  — top-level controller
# ---------------------------------------------------------------------------

class FusionBridge:
    """
    Owns the PoseTracker, serial connection, and pixel->physical mapper
    (LocalAffineMapper by default; HomographyMapper still works, same
    pixel_to_physical interface).
    Runs the main 10 Hz loop.

    Parameters
    ----------
    tracker     : Initialised PoseTracker (camera not yet opened by caller).
    mapper      : Calibrated LocalAffineMapper (or HomographyMapper).
    serial_port : e.g. "COM6".
    baud        : Must match the ESP32 firmware (115200).
    """

    def __init__(
        self,
        tracker:     PoseTracker,
        mapper:      "LocalAffineMapper | HomographyMapper",
        serial_port: str = SERIAL_PORT,
        baud:        int = SERIAL_BAUD,
    ) -> None:
        self._tracker      = tracker
        self._mapper       = mapper
        self._port_name    = serial_port
        self._baud         = baud
        self._serial:      Optional[serial.Serial] = None
        self._serial_ok:   bool = False
        self._frame_count: int  = 0
        self._cmd_count:   int  = 0

    # ------------------------------------------------------------------
    # Serial helpers
    # ------------------------------------------------------------------

    def _open_serial(self) -> None:
        """
        Attempt to open the serial port.  On failure, set dry-run mode so
        the rest of the pipeline continues unaffected (useful for bench testing
        when the ESP32 is not connected).
        """
        try:
            self._serial = serial.Serial(
                port=self._port_name,
                baudrate=self._baud,
                timeout=SERIAL_TIMEOUT,
                write_timeout=SERIAL_TIMEOUT,
            )
            self._serial_ok = True
            logger.info("Serial %s opened @ %d baud.", self._port_name, self._baud)
        except serial.SerialException as exc:
            self._serial    = None
            self._serial_ok = False
            logger.warning(
                "Cannot open '%s': %s — running in DRY-RUN mode "
                "(commands printed, not sent).",
                self._port_name, exc,
            )

    def _write(self, cmd: str) -> bool:
        """
        Write one ASCII command to the serial port.

        Returns True on success.  On any serial error the port is marked as
        disconnected so the status line updates accordingly.
        """
        if self._serial is None or not self._serial.is_open:
            return False
        try:
            self._serial.write(cmd.encode("ascii"))
            self._serial.flush()
            return True
        except serial.SerialTimeoutException:
            logger.debug("Serial write timeout: %r", cmd.strip())
            return False
        except serial.SerialException as exc:
            logger.error("Serial write error: %s", exc)
            self._serial_ok = False
            return False

    def _close_serial(self) -> None:
        if self._serial and self._serial.is_open:
            self._serial.close()
            logger.info("Serial %s closed.", self._port_name)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        """
        Open hardware resources and spin the 10 Hz fusion loop.
        Releases camera and serial cleanly on KeyboardInterrupt.
        """
        self._tracker.open_camera()
        self._open_serial()

        # Print static banner then blank lines that _render_frame will overwrite
        print(
            f"\n{_BOLD}{'─'*76}\n"
            f"  RoboSurge Phase 3 — Vision → ESP32 IK Bridge   "
            f"@ {LOOP_RATE_HZ:.0f} Hz   port={self._port_name}\n"
            f"{'─'*76}{_R}\n"
        )
        print("\n" * _BLOCK_LINES, end="")

        interval    = 1.0 / LOOP_RATE_HZ
        first_frame = True

        try:
            while True:
                t0 = time.monotonic()

                # 1. Acquire frame from Camo Studio USB (index 1)
                frame = self._tracker.grab_frame()
                self._frame_count += 1

                # 2. YOLOv8-pose inference  →  list[ArmPoseResult]
                detections: list[ArmPoseResult] = self._tracker.process_frame(frame)

                # 3. Filter (drop occluded) + sort L→R + cap at 2 + map to cm
                assigned = assign_arms(detections, self._mapper)

                # 4. Transmit IK commands to ESP32
                for arm in assigned:
                    sent = self._write(arm.serial_command)
                    if sent:
                        self._cmd_count += 1

                # 5. Terminal output
                elapsed_ms = (time.monotonic() - t0) * 1000.0
                _render_frame(
                    assigned=assigned,
                    total_detections=len(detections),
                    serial_ok=self._serial_ok,
                    loop_ms=elapsed_ms,
                    first_frame=first_frame,
                )
                first_frame = False

                # ========================================================
                # NEW: Live UI Rendering Block
                # ========================================================
                if frame is not None:
                    annotated_frame = self._tracker.draw_pose(frame, detections)
                    cv2.imshow("RoboSurge Live Target Tracking", annotated_frame)
                    cv2.waitKey(1)  # Required to process window events
                # ========================================================

                # 6. Sleep to maintain ~10 Hz
                sleep_for = max(0.0, interval - (time.monotonic() - t0))
                time.sleep(sleep_for)

        except KeyboardInterrupt:
            print(f"\n\n{_BOLD}Interrupt received — shutting down…{_R}")

        finally:
            self._tracker.release_camera()
            self._close_serial()
            cv2.destroyAllWindows()  # Ensure the UI window closes cleanly
            self._summary()

    def _summary(self) -> None:
        print(
            f"\n{_BOLD}Session summary{_R}\n"
            f"  Frames processed : {self._frame_count}\n"
            f"  Commands sent    : {self._cmd_count}\n"
            f"  Serial port      : {self._port_name} "
            f"({'connected' if self._serial_ok else 'dry-run'})\n"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _parse_cli() -> tuple[str, str | int, str]:
    """
    Minimal CLI arg parser (no argparse dependency).

    Flags
    -----
    --port    <port>    serial port       (default: COM6)
    --weights <path>    YOLO weights file (default: robosurge_pose_best.pt)
    --cam     <n|url>   camera index or RTSP URL (default: 1 = Camo Studio USB)
    """
    port    = SERIAL_PORT
    weights = "robosurge_pose_best.pt"
    cam: str | int = 1

    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        nxt = sys.argv[i + 1] if i + 1 < len(sys.argv) else ""
        if   arg == "--port"    and nxt: port = nxt;                           i += 2
        elif arg == "--weights" and nxt: weights = nxt;                        i += 2
        elif arg == "--cam"     and nxt: cam = int(nxt) if nxt.isdigit() else nxt; i += 2
        else: i += 1

    return port, cam, weights


if __name__ == "__main__":
    port, cam_index, weights = _parse_cli()

    # Graceful fallback: if custom weights are missing, use stock yolov8n-pose
    # so the full pipeline can be validated without trained weights.
    if not Path(weights).exists():
        logger.warning(
            "Weights file '%s' not found — falling back to yolov8n-pose.pt. "
            "Keypoint indices will not match RoboSurge labels.", weights,
        )
        weights = "yolov8n-pose.pt"

    logger.info("Config → port=%s  cam=%s  weights=%s", port, cam_index, weights)

    mapper  = LocalAffineMapper(CALIBRATION_PHYSICAL_PTS, CALIBRATION_PIXEL_PTS)
    tracker = PoseTracker(weights_path=weights, camera_index=cam_index)

    FusionBridge(
        tracker=tracker,
        mapper=mapper,
        serial_port=port,
        baud=SERIAL_BAUD,
    ).run()