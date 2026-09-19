"""
landmark_detector.py — RoboSurge Phase 4 (Option B1)
======================================================
Detects colored fiducial dots placed on the surgical field and returns their
physical (X, Y, Z) positions using the same LocalAffineMapper from sensor_fusion.py.

Fiducial protocol (B1)
-----------------------
Place one or more small (~8mm dia.) high-saturation dots on the tissue/phantom
before the procedure.  Recommended colors (easy to separate in HSV):

  Landmark A  →  MAGENTA / PINK   (primary incision target)
  Landmark B  →  CYAN / TEAL      (secondary reference / retraction target)
  Landmark C  →  YELLOW           (optional third reference)

Color is the only signal used — no ML inference, no extra model weights.
Detection is ~0.3 ms per frame on CPU, well within the 10 Hz loop budget.

HSV thresholds
--------------
All thresholds are tunable via LandmarkConfig.  Run ``python landmark_detector.py``
with a live camera to open the interactive tuner and find values for your
lighting conditions before deployment.

Physical Z
----------
All landmarks are assumed to lie on the table surface: Z = TABLE_Z_CM (7.5).
If a landmark is elevated (e.g. on a raised tissue pad), adjust
LandmarkConfig.z_offset_cm accordingly.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np


import dotenv
dotenv.load_dotenv()  # load .env file if present
logger = logging.getLogger("LandmarkDetector")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Was previously a local hardcoded copy (7.5) that silently drifted out of
# sync with scene_state.py's value. Now imports the single source of truth
# so a future recalibration only has to change one number.
from .scene_state import TABLE_Z_CM, MIN_REACH, MAX_REACH  # physical Z of table surface (same as FIXED_Z_CM)

# Minimum/maximum dot area in pixels to filter noise and large blobs
MIN_DOT_AREA_PX: int = 50
MAX_DOT_AREA_PX: int = 5000

# Calibrated pixel bounding box — detections outside this region are rejected
# as false positives from background / servo hardware.
PIXEL_BOUND_V_MIN: int = 250
PIXEL_BOUND_U_MIN: int = 100
PIXEL_BOUND_U_MAX: int = 1200
PIXEL_BOUND_V_MAX: int = 720

# Max reach allowed for landmark detection before hard rejection (with clamping)
MAX_LANDMARK_REACH: float = 50.0

# A dot parked outside the calibrated region is rejected on every frame, so at
# the vision thread's ~10 Hz the warning scrolled the interactive prompt off
# screen faster than it could be read. Log the first rejection per landmark
# immediately, then at most one line per interval carrying the suppressed count
# — the condition is static, so repeating it 10x/second adds nothing.
REJECT_LOG_INTERVAL_S: float = 5.0


# ---------------------------------------------------------------------------
# Config per landmark color
# ---------------------------------------------------------------------------

@dataclass
class LandmarkConfig:
    """
    HSV detection parameters for one fiducial color.

    OpenCV HSV ranges: H ∈ [0,179], S ∈ [0,255], V ∈ [0,255].
    Hue wraps at 180 — magenta/red requires two ranges (see LANDMARK_CONFIGS).

    Attributes
    ----------
    name : str
        Human-readable label ("landmark_A", "landmark_B", …).
    hsv_lower, hsv_upper : np.ndarray
        Primary HSV bounds.
    hsv_lower2, hsv_upper2 : optional second range for hues that wrap.
    z_offset_cm : float
        Physical Z offset above the table (0 for flat markers).
    color_bgr : tuple
        Display color for draw_landmarks().
    """
    name:         str
    hsv_lower:    np.ndarray
    hsv_upper:    np.ndarray
    hsv_lower2:   Optional[np.ndarray] = None
    hsv_upper2:   Optional[np.ndarray] = None
    z_offset_cm:  float = 0.0
    color_bgr:    tuple[int, int, int] = (255, 255, 255)


# Default configs — tune S/V for your lighting with the interactive tuner
LANDMARK_CONFIGS: list[LandmarkConfig] = [

    # Bounds below are centred on measured dot statistics rather than guessed
    # (see tools/diag_clutter.py). Previously the yellow dot sat at H=34.9
    # against an upper bound of 35 and cyan at H=97.3 against 100 — both were
    # one lighting shift away from dropping out of their own mask.
    LandmarkConfig(
        name="landmark_A",
        # Yellow — measured H=34.9±0.5, S=128.8±6.7, V=212.6±1.8.
        # H floor of 28 also rejects the H=23 clutter blob on the arm base.
        hsv_lower=np.array([28,  90, 170], dtype=np.uint8),
        hsv_upper=np.array([42, 255, 255], dtype=np.uint8),
        color_bgr=(0, 220, 220),
    ),

    LandmarkConfig(
        name="landmark_B",
        # Cyan/teal — measured H=97.3±0.8, S=154.8±22.4, V=214.3±3.1.
        # Upper bound stops at 103 rather than 108: there is background
        # clutter at H=105.8 in the top-left of the frame, and 103 is still
        # 6 sigma above the dot's own hue.
        hsv_lower=np.array([86, 100, 150], dtype=np.uint8),
        hsv_upper=np.array([103, 255, 255], dtype=np.uint8),
        color_bgr=(255, 200, 0),
    ),

    LandmarkConfig(
        name="landmark_C",
        # Purple — measured H=122.8±2.4, S=108.9±17.9, V=204.2±10.2.
        # The old S>=40, V>=40 floors let in a V=65 shadow blob; the real dot
        # is three times brighter, so the V floor does the separating.
        hsv_lower=np.array([112,  80, 130], dtype=np.uint8),
        hsv_upper=np.array([138, 255, 255], dtype=np.uint8),
        color_bgr=(200, 0, 200),
    ),

]


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class LandmarkDetection:
    """
    One detected fiducial dot.

    Attributes
    ----------
    name : str
        Landmark label from LandmarkConfig.
    pixel_u, pixel_v : float
        Centroid pixel coordinates (subpixel from moments).
    physical_x, physical_y, physical_z : float
        Table-frame coordinates in cm (Z = TABLE_Z_CM + z_offset_cm).
    area_px : float
        Contour area in pixels (useful for size sanity checks).
    confidence : float
        Heuristic in [0, 1] based on area and circularity.
    """
    name:        str
    pixel_u:     float
    pixel_v:     float
    physical_x:  float
    physical_y:  float
    physical_z:  float
    area_px:     float
    confidence:  float


@dataclass
class LandmarkFrame:
    """All landmark detections from one camera frame."""
    detections:  list[LandmarkDetection] = field(default_factory=list)
    timestamp:   float = field(default_factory=time.monotonic)
    frame_id:    int = 0

    def get(self, name: str) -> Optional[LandmarkDetection]:
        """Return the first detection matching name, or None."""
        return next((d for d in self.detections if d.name == name), None)

    @property
    def physical_positions(self) -> dict[str, tuple[float, float, float]]:
        """Dict of name → (x, y, z) for all detected landmarks."""
        return {d.name: (d.physical_x, d.physical_y, d.physical_z)
                for d in self.detections}


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------

class LandmarkDetector:
    """
    Detects colored fiducial dots and projects them to physical coordinates.

    Parameters
    ----------
    mapper : LocalAffineMapper (from sensor_fusion.py)
        Must already be calibrated.  The detector calls mapper.pixel_to_physical()
        for each detected centroid.
    configs : list[LandmarkConfig]
        Which colors to look for.  Defaults to LANDMARK_CONFIGS (A, B, C).
    blur_ksize : int
        Gaussian blur kernel size (odd).  Larger = more noise rejection but
        less spatial precision.  5 is a good starting point.
    morph_ksize : int
        Morphological open/close kernel size for cleaning the binary mask.
    """

    def __init__(
        self,
        mapper,                                         # LocalAffineMapper
        configs: list[LandmarkConfig] = LANDMARK_CONFIGS,
        blur_ksize:  int = 5,
        morph_ksize: int = 5,
    ) -> None:
        self._mapper  = mapper
        self._configs = configs
        self._blur_k  = blur_ksize | 1        # ensure odd
        self._morph_k = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (morph_ksize, morph_ksize)
        )
        self._frame_id: int = 0

        # Per-landmark throttle state for the out-of-workspace warning:
        # name -> monotonic timestamp of last emitted line, and the number of
        # rejections swallowed since then.
        self._reject_last_log:   dict[str, float] = {}
        self._reject_suppressed: dict[str, int]   = {}

        logger.info(
            "LandmarkDetector ready.  Tracking %d colors: %s",
            len(configs), [c.name for c in configs],
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_frame(self, frame: Optional[np.ndarray]) -> LandmarkFrame:
        """
        Detect all configured fiducials in one BGR camera frame.

        Parameters
        ----------
        frame : np.ndarray (H×W×3 BGR) or None.

        Returns
        -------
        LandmarkFrame  — contains 0–N LandmarkDetection objects.
        """
        self._frame_id += 1
        result = LandmarkFrame(frame_id=self._frame_id)

        if frame is None or frame.size == 0:
            return result

        # Pre-process once for all color masks
        blurred = cv2.GaussianBlur(frame, (self._blur_k, self._blur_k), 0)
        hsv     = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)

        for cfg in self._configs:
            det = self._detect_one_color(hsv, cfg)
            if det is not None:
                result.detections.append(det)

        return result

    def draw_landmarks(
        self,
        frame:      np.ndarray,
        lf:         LandmarkFrame,
        *,
        show_area:  bool = False,
    ) -> np.ndarray:
        """
        Overlay detected landmarks on a copy of frame.

        Draws: filled circle at centroid, label with physical coords,
        optional area text.
        """
        out = frame.copy()
        for d in lf.detections:
            cfg = next((c for c in self._configs if c.name == d.name), None)
            col = cfg.color_bgr if cfg else (255, 255, 255)
            cx, cy = int(d.pixel_u), int(d.pixel_v)

            cv2.circle(out, (cx, cy), 10, col, -1)
            cv2.circle(out, (cx, cy), 12, (255, 255, 255), 1)

            label = (
                f"{d.name}  "
                f"({d.physical_x:+.1f},{d.physical_y:+.1f}) cm  "
                f"conf={d.confidence:.2f}"
            )
            if show_area:
                label += f"  area={d.area_px:.0f}px"

            cv2.putText(out, label, (cx + 14, cy - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 1, cv2.LINE_AA)
        return out

    # ------------------------------------------------------------------
    # Private detection logic
    # ------------------------------------------------------------------

    def _detect_one_color(
        self,
        hsv: np.ndarray,
        cfg: LandmarkConfig,
    ) -> Optional[LandmarkDetection]:
        """
        Build a binary mask for cfg's HSV range, find the largest contour
        that passes area + circularity filters, and return its centroid.

        Algorithm
        ---------
        1. Threshold HSV → binary mask (union of two ranges if hue wraps).
        2. Morphological open (remove specks) then close (fill gaps).
        3. Find external contours.
        4. For each contour: compute area, circularity = 4π·A / P².
           Keep only contours with MIN_DOT_AREA < A < MAX_DOT_AREA
           and circularity > 0.4 (dots are roughly circular).
        5. Pick the contour with the largest area (most prominent dot).
        6. Compute centroid via image moments (subpixel accuracy).
        7. Project centroid pixel → physical cm via homography.
        8. Confidence = 0.5·(area_score) + 0.5·circularity, clamped to [0,1].
        """
        # Step 1: mask
        mask = cv2.inRange(hsv, cfg.hsv_lower, cfg.hsv_upper)
        if cfg.hsv_lower2 is not None and cfg.hsv_upper2 is not None:
            mask2 = cv2.inRange(hsv, cfg.hsv_lower2, cfg.hsv_upper2)
            mask  = cv2.bitwise_or(mask, mask2)

        # Step 2: clean
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  self._morph_k)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self._morph_k)

        # Step 3: contours
        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        if not contours:
            return None

        # Step 4: filter by area and circularity
        candidates: list[tuple[float, float, np.ndarray]] = []  # (area, circ, cnt)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if not (MIN_DOT_AREA_PX <= area <= MAX_DOT_AREA_PX):
                continue
            perimeter = cv2.arcLength(cnt, True)
            if perimeter < 1e-6:
                continue
            circularity = (4.0 * np.pi * area) / (perimeter ** 2)
            if circularity < 0.25:
                continue
            candidates.append((area, circularity, cnt))

        if not candidates:
            return None

        # Step 5: pick largest
        candidates.sort(key=lambda t: t[0], reverse=True)
        best_area, best_circ, best_cnt = candidates[0]

        # Step 6: subpixel centroid via moments
        M = cv2.moments(best_cnt)
        if M["m00"] < 1e-6:
            return None
        cx = M["m10"] / M["m00"]
        cy = M["m01"] / M["m00"]

        # Step 6.5: reject centroids outside calibrated pixel region
        # Catches false detections on servo hardware, background, curtains.
        if not (PIXEL_BOUND_U_MIN <= cx <= PIXEL_BOUND_U_MAX and
                PIXEL_BOUND_V_MIN <= cy <= PIXEL_BOUND_V_MAX):
            return None

        # Step 7: pixel -> physical
        phys_x, phys_y = self._mapper.pixel_to_physical(cx, cy)
        phys_z = TABLE_Z_CM + cfg.z_offset_cm

        # Step 7.5: validate and soft-clamp physical reach
        reach = math.hypot(phys_x, phys_y)
        if not (0.5 <= reach <= MAX_LANDMARK_REACH):
            self._log_reject_throttled(cfg.name, cx, cy, phys_x, phys_y, reach)
            return None

        # Soft-clamp if slightly beyond max robot reach to keep within reachable envelope
        if reach > MAX_REACH:
            scale = (MAX_REACH - 0.5) / reach
            phys_x *= scale
            phys_y *= scale

        # Step 8: confidence
        norm_area  = min(best_area / 600.0, 1.0)   # 600px = expected dot size at this distance
        confidence = float(np.clip(
            0.75 * min(best_circ, 1.0) + 0.25 * norm_area,
            0.0, 1.0
        ))

        return LandmarkDetection(
            name=cfg.name,
            pixel_u=cx,
            pixel_v=cy,
            physical_x=phys_x,
            physical_y=phys_y,
            physical_z=phys_z,
            area_px=best_area,
            confidence=confidence,
        )

    def _log_reject_throttled(
        self,
        name:   str,
        cx:     float,
        cy:     float,
        phys_x: float,
        phys_y: float,
        reach:  float,
    ) -> None:
        """
        Emit the out-of-workspace rejection at most once per
        REJECT_LOG_INTERVAL_S per landmark, folding the suppressed count into
        the next line so nothing is silently lost.
        """
        now  = time.monotonic()
        last = self._reject_last_log.get(name)

        if last is not None and (now - last) < REJECT_LOG_INTERVAL_S:
            self._reject_suppressed[name] = self._reject_suppressed.get(name, 0) + 1
            return

        skipped = self._reject_suppressed.get(name, 0)
        suffix  = f" ({skipped} more since last message)" if skipped else ""

        logger.warning(
            "%s at pixel (%.0f,%.0f) maps to (%.1f, %.1f) cm — reach "
            "%.1f cm is outside [%.1f, %.1f]. Rejecting: the dot is "
            "outside the calibrated workspace, so move it closer to the "
            "arm or recalibrate to cover it.%s",
            name, cx, cy, phys_x, phys_y, reach, MIN_REACH, MAX_REACH, suffix,
        )

        self._reject_last_log[name]   = now
        self._reject_suppressed[name] = 0

    # ------------------------------------------------------------------
    # Interactive HSV tuner (run standalone)
    # ------------------------------------------------------------------

    @staticmethod
    def run_tuner(camera_index: int = 1) -> None:
        """
        Open a live window with HSV trackbars to find the right thresholds
        for your lighting.  Press 'q' to quit.  Print the values you find
        and hard-code them into LANDMARK_CONFIGS.
        """
        cap = cv2.VideoCapture(camera_index)
        cv2.namedWindow("HSV Tuner", cv2.WINDOW_NORMAL)

        for name, val in [("H_lo",0),("H_hi",179),("S_lo",0),("S_hi",255),
                           ("V_lo",0),("V_hi",255)]:
            cv2.createTrackbar(name, "HSV Tuner", val, 255 if name!="H_hi" else 179, lambda _: None)
        cv2.setTrackbarMax("H_hi", "HSV Tuner", 179)
        cv2.setTrackbarMax("H_lo", "HSV Tuner", 179)

        print("HSV Tuner running.  Press 'q' to quit and print values.")
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            hsv = cv2.cvtColor(cv2.GaussianBlur(frame, (5,5), 0), cv2.COLOR_BGR2HSV)

            lo = np.array([cv2.getTrackbarPos("H_lo","HSV Tuner"),
                           cv2.getTrackbarPos("S_lo","HSV Tuner"),
                           cv2.getTrackbarPos("V_lo","HSV Tuner")], dtype=np.uint8)
            hi = np.array([cv2.getTrackbarPos("H_hi","HSV Tuner"),
                           cv2.getTrackbarPos("S_hi","HSV Tuner"),
                           cv2.getTrackbarPos("V_hi","HSV Tuner")], dtype=np.uint8)

            mask = cv2.inRange(hsv, lo, hi)
            result = cv2.bitwise_and(frame, frame, mask=mask)
            cv2.imshow("HSV Tuner", np.hstack([frame, result]))

            if cv2.waitKey(1) & 0xFF == ord('q'):
                print(f"\nHSV lower: {lo.tolist()}")
                print(f"HSV upper: {hi.tolist()}")
                break

        cap.release()
        cv2.destroyAllWindows()


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    if "--tune" in sys.argv:
        cam = int(sys.argv[sys.argv.index("--tune") + 1]) if len(sys.argv) > 2 else 1
        LandmarkDetector.run_tuner(cam)
        sys.exit(0)

    # Use real LocalAffineMapper with your calibrated values
    try:
        from .sensor_fusion import (
            LocalAffineMapper, CALIBRATION_PHYSICAL_PTS, CALIBRATION_PIXEL_PTS
        )
        _mapper = LocalAffineMapper(CALIBRATION_PHYSICAL_PTS, CALIBRATION_PIXEL_PTS)
        print("Using calibrated LocalAffineMapper from sensor_fusion.py")
    except Exception as e:
        print(f"Could not load LocalAffineMapper ({e}) — using identity mapper")
        class _IdentityMapper:
            def pixel_to_physical(self, u, v):
                return (u / 60.0, v / 60.0)
        _mapper = _IdentityMapper()

    detector = LandmarkDetector(mapper=_mapper)
    cap = cv2.VideoCapture(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    print("Landmark detector live.  Press 'q' to quit.")
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        lf  = detector.process_frame(frame)
        out = detector.draw_landmarks(frame, lf, show_area=True)

        for d in lf.detections:
            print(f"  {d.name}: pixel=({d.pixel_u:.0f},{d.pixel_v:.0f})  "
                  f"phys=({d.physical_x:.2f},{d.physical_y:.2f})  "
                  f"conf={d.confidence:.2f}")

        cv2.imshow("Landmark Detector", out)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()