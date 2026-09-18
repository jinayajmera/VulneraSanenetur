"""
scene_state.py — RoboSurge Phase 4
====================================
Aggregates the current perception snapshot (arm tip positions + landmark
positions) into a single SceneState dataclass that is serialised to JSON
and injected into the LLM system prompt on every SurgicalAgent call.

The SceneState is the "world model" the LLM reasons over.  It must be:
  - Compact  (fits comfortably in the Groq context window)
  - Complete (everything the LLM needs to plan a procedure)
  - Validated (no None positions reach the LLM — caller must check)

Design contract
---------------
scene_state.py has ZERO external imports beyond stdlib + numpy.
It does not import from vision_pipeline, landmark_detector, or sensor_fusion
directly — the caller (robosurge_cli.py) assembles the SceneState from data
those modules return.  This keeps scene_state.py unit-testable in isolation.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Physical workspace constants (duplicated here to keep this file standalone)
# ---------------------------------------------------------------------------

# TABLE_Z_CM was previously hardcoded to +7.5 (an unvalidated guess based on
# kinematics_engine.py's BASE_HEIGHT). Physical calibration on 2026-06-19
# proved this wrong: the command "arm1 +12.95 +3.47 -7.66" physically touches
# landmark_A on the table surface. -7.66 is therefore the real table-touch Z
# in the ESP32's command frame (its Z=0 sits ~7.66cm above the table, near
# shoulder-pivot height, not at the table itself as the old code assumed).
# This is the SINGLE SOURCE OF TRUTH for table Z — every other module
# (landmark_detector.py, sensor_fusion.py, surgical_agent.py,
# procedure_validator.py, motion_executor.py, robosurge_cli.py) imports this
# constant rather than re-declaring its own copy.
TABLE_Z_CM:  float = -7.66
MIN_REACH:   float = 2.5
MAX_REACH:   float = 21.5
# Original design intent was a 2.5cm hover clearance above the table
# (10.0 - 7.5 = 2.5, under the old wrong origin). Preserved here under the
# corrected origin rather than reusing the old absolute number, which meant
# nothing once TABLE_Z_CM moved.
SAFE_Z_CM:   float = TABLE_Z_CM + 2.5   # = -5.16, hover height above table for transit moves


# ---------------------------------------------------------------------------
# Sub-objects
# ---------------------------------------------------------------------------

@dataclass
class ArmState:
    """
    Current physical state of one surgical arm.

    Attributes
    ----------
    arm_id : int
        1 = left/cutting arm, 2 = right/retracting arm.
    x, y, z : float
        Tip position in cm (physical frame).
    source : str
        "FUSED", "FK", or "VISION" — which estimate was used.
    """
    arm_id: int
    x:      float
    y:      float
    z:      float
    source: str = "FUSED"

    def as_dict(self) -> dict:
        return {"arm_id": self.arm_id, "x": round(self.x, 3),
                "y": round(self.y, 3), "z": round(self.z, 3),
                "source": self.source}


@dataclass
class LandmarkState:
    """
    Physical position of one detected fiducial landmark.

    Attributes
    ----------
    name : str
        "landmark_A", "landmark_B", or "landmark_C".
    x, y, z : float
        Physical coordinates in cm.
    confidence : float
        Detector confidence in [0, 1].
    """
    name:       str
    x:          float
    y:          float
    z:          float
    confidence: float = 1.0

    def as_dict(self) -> dict:
        return {"name": self.name, "x": round(self.x, 3),
                "y": round(self.y, 3), "z": round(self.z, 3),
                "confidence": round(self.confidence, 3)}


# ---------------------------------------------------------------------------
# SceneState — the full world model
# ---------------------------------------------------------------------------

@dataclass
class SceneState:
    """
    Complete perception snapshot fed to the SurgicalAgent.

    Attributes
    ----------
    arms : list[ArmState]
        Current tip positions for arm1 and arm2.
    landmarks : list[LandmarkState]
        All detected fiducial landmarks.
    timestamp : float
        Monotonic time of snapshot creation.
    tool_z_offset_cm : float
        Calibrated offset between FK Z datum and the actual cutting tip when
        the arm is at rest.  Set during tool-offset calibration.
        The LLM uses this to compute the correct Z for a given incision depth:
            cut_z = TABLE_Z_CM - incision_depth_cm + tool_z_offset_cm
    notes : str
        Optional free-text notes injected into the LLM context
        (e.g. "Patient tissue is phantom gel, stiffness ≈ 20 kPa").
    """
    arms:              list[ArmState]
    landmarks:         list[LandmarkState]
    timestamp:         float = field(default_factory=time.monotonic)
    tool_z_offset_cm:  float = 0.0
    notes:             str   = ""

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get_arm(self, arm_id: int) -> Optional[ArmState]:
        return next((a for a in self.arms if a.arm_id == arm_id), None)

    def get_landmark(self, name: str) -> Optional[LandmarkState]:
        return next((l for l in self.landmarks if l.name == name), None)

    @property
    def landmark_names(self) -> list[str]:
        return [l.name for l in self.landmarks]

    # ------------------------------------------------------------------
    # Serialisation — used to build the LLM user message
    # ------------------------------------------------------------------

    def to_json(self, indent: int = 2) -> str:
        """
        Serialise to a compact JSON string for injection into the LLM prompt.

        The LLM receives this as the "current world state" section of its
        user message.  Coordinates are rounded to 3 d.p. (0.1 mm resolution)
        to avoid token waste from floating-point noise.
        """
        payload = {
            "workspace": {
                "table_z_cm":      TABLE_Z_CM,
                "min_reach_cm":    MIN_REACH,
                "max_reach_cm":    MAX_REACH,
                "safe_transit_z":  SAFE_Z_CM,
                "tool_z_offset_cm": round(self.tool_z_offset_cm, 3),
            },
            "arms": [a.as_dict() for a in self.arms],
            "landmarks": [l.as_dict() for l in self.landmarks],
            "notes": self.notes,
        }
        return json.dumps(payload, indent=indent)

    def to_prompt_block(self) -> str:
        """
        Human-readable summary block for the LLM user message header.
        Sits above the JSON so the model gets both a quick summary and the
        full structured data.
        """
        arm_lines = "\n".join(
            f"  arm{a.arm_id}: ({a.x:+.2f}, {a.y:+.2f}, {a.z:.2f}) cm  [{a.source}]"
            for a in self.arms
        )
        lm_lines = "\n".join(
            f"  {l.name}: ({l.x:+.2f}, {l.y:+.2f}, {l.z:.2f}) cm  conf={l.confidence:.2f}"
            for l in self.landmarks
        ) or "  (none detected)"

        return (
            "=== CURRENT SCENE STATE ===\n"
            f"ARM POSITIONS:\n{arm_lines}\n"
            f"LANDMARKS:\n{lm_lines}\n"
            f"TOOL Z OFFSET: {self.tool_z_offset_cm:.3f} cm\n"
            f"NOTES: {self.notes or 'none'}\n"
            "=== END SCENE STATE ===\n\n"
            "FULL JSON:\n"
            f"{self.to_json()}"
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> list[str]:
        """
        Return a list of warning strings for any suspicious state values.
        An empty list means the state is clean.
        Called before handing the state to the SurgicalAgent.
        """
        warnings: list[str] = []

        for arm in self.arms:
            reach = (arm.x ** 2 + arm.y ** 2) ** 0.5
            if reach < MIN_REACH:
                warnings.append(
                    f"arm{arm.arm_id} reach={reach:.2f} cm is inside blind spot "
                    f"(min={MIN_REACH} cm)."
                )
            if reach > MAX_REACH:
                warnings.append(
                    f"arm{arm.arm_id} reach={reach:.2f} cm exceeds MAX_REACH "
                    f"({MAX_REACH} cm)."
                )
            if arm.z < TABLE_Z_CM - 1.0:
                warnings.append(
                    f"arm{arm.arm_id} z={arm.z:.2f} cm is below the table surface."
                )

        for lm in self.landmarks:
            if lm.confidence < 0.30:
                warnings.append(
                    f"{lm.name} confidence={lm.confidence:.2f} is very low — "
                    "landmark position may be unreliable."
                )

        return warnings


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    state = SceneState(
        arms=[
            ArmState(arm_id=1, x=10.0, y= 2.0, z=7.5, source="FUSED"),
            ArmState(arm_id=2, x=12.0, y=-2.0, z=7.5, source="FUSED"),
        ],
        landmarks=[
            LandmarkState(name="landmark_A", x=11.0, y=0.5, z=7.5, confidence=0.92),
            LandmarkState(name="landmark_B", x= 9.5, y=3.0, z=7.5, confidence=0.85),
        ],
        tool_z_offset_cm=0.15,
        notes="Phantom gel block, 3-layer silicone.",
    )

    print(state.to_prompt_block())
    print("\nValidation:", state.validate() or "OK")