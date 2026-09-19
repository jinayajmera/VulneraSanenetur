"""
surgical_agent.py — RoboSurge Phase 4
=======================================
Groq LLM agent that converts a natural-language surgical command + SceneState
into a structured ProcedurePlan JSON.

Model: openai/gpt-oss-120b via Groq API.
Output: strict JSON only — no freetext, no markdown, no preamble.

Prompt architecture
-------------------
SYSTEM  — static, loaded once at init:
    • Arm roles and workspace limits
    • Tool geometry and Z depth math
    • Supported procedure types and their motion profiles
    • Incision physics constraints
    • Strict JSON schema with field definitions
    • Hard refusal rules (unsafe commands)

USER    — assembled per call:
    • SceneState.to_prompt_block()   (arms + landmarks + workspace)
    • The natural-language command

JSON mode — response_format={"type": "json_object"} forces the model to emit a
single well-formed JSON object (replaces the old "{" assistant-seed trick, which
reasoning models such as gpt-oss do not honour).

Retry logic
-----------
Groq occasionally returns malformed JSON on complex prompts.  The agent
retries up to MAX_RETRIES times, feeding the parse error back as a correction
request.  After MAX_RETRIES failures the agent raises SurgicalAgentError.

ProcedurePlan schema
--------------------
{
  "procedure": "incision" | "biopsy" | "cauterization" | "debridement" | "suturing" | "retraction" | "hold" | "home" | "abort",
  "rationale": "<one sentence — why these waypoints achieve the command>",
  "arm1": {
    "role": "cutting" | "retracting" | "holding" | "idle",
    "waypoints": [
      {"x": float, "y": float, "z": float, "label": str}
    ],
    "feed_rate_mm_s": float
  },
  "arm2": {
    "role": "...",
    "waypoints": [...],
    "feed_rate_mm_s": float
  },
  "estimated_duration_s": float,
  "safety_notes": str
}

All coordinates in the plan are in cm, physical frame.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from groq import Groq

from .scene_state import SceneState, TABLE_Z_CM, MIN_REACH, MAX_REACH, SAFE_Z_CM

logger = logging.getLogger("SurgicalAgent")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GROQ_MODEL:  str = "openai/gpt-oss-120b"
MAX_TOKENS:  int = 8192   # gpt-oss reasoning tokens count toward this budget
TEMPERATURE: float = 0.0    # deterministic — surgical planning is not creative
MAX_RETRIES: int = 3

# Feed rate limits (mm/s) the ESP32 servos can physically execute
FEED_RATE_MIN_MM_S: float = 0.5
FEED_RATE_MAX_MM_S: float = 15.0

# Default feed rates by procedure type
DEFAULT_FEED_RATES: dict[str, float] = {
    "incision":      2.0,   # slow and controlled
    "biopsy":        1.5,   # plunge + retract, single point
    "cauterization": 1.0,   # slowest — precision dwell at a single point
    "debridement":   4.0,   # sweep pattern, moderate speed
    "suturing":      1.5,   # entry/loop/exit/cinch per stitch, slow and controlled
    "retraction":    8.0,
    "hold":          1.0,
    "home":          12.0,
    "abort":         15.0,
}

# Cauterization dwell time at the target point (seconds)
CAUTERIZATION_DWELL_S: float = 3.0

# Suturing: brief dwell at the "cinch" waypoint of each stitch, simulating
# the thread being pulled tight before moving to the next stitch.
SUTURE_CINCH_DWELL_S:  float = 0.3
DEFAULT_SUTURE_STITCHES: int = 3


# ---------------------------------------------------------------------------
# System prompt (static)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = f"""
You are the surgical planning AI for RoboSurge, a dual-arm robotic surgical system.
Your ONLY output is a single valid JSON object. No markdown. No explanation. No preamble.
Begin your response with the opening brace {{ and end with }}.

=== HARDWARE SPECIFICATION ===
- Coordinate origin: bottom-center of base tower at table surface.
- X-axis: forward (away from robot). Y-axis: left. Z-axis: up.
- Table surface Z: {TABLE_Z_CM} cm (this is also the floor — Z must never go below {TABLE_Z_CM - 0.5}).
- Safe transit height (Z for all non-cutting moves): {SAFE_Z_CM} cm.
- Workspace: horizontal reach {MIN_REACH}–{MAX_REACH} cm from base.
- arm1 = LEFT arm = CUTTING tool (scalpel). arm1 makes incisions.
- arm2 = RIGHT arm = RETRACTION tool. arm2 holds tissue out of the way.
- Both arms must maintain at least 5.0 cm clearance from each other at all times.
- arm2 hold position Y must differ from arm1 incision Y by at least 7.0 cm.
  Example: if arm1 cuts at Y=+3.5, arm2 must hold at Y ≤ -3.5 or Y ≥ +10.5.

=== TOOL GEOMETRY AND Z DEPTH ===
- Python will repair incision geometry deterministically after you return JSON.
- For ordinary 3mm incision planning, use cut_z={TABLE_Z_CM - 0.3:.2f} cm.
- Do not invent Z values from tool_z_offset_cm; the execution layer owns final Z.
- plunge Z must be less than approach Z.

=== MOTION PROFILES ===
"incision": arm1 follows this waypoint sequence:
  1. label="transit"  → move to start XY at z={SAFE_Z_CM} (safe height)
  2. label="approach" → descend to z=TABLE_Z + 0.2 (just above surface)
  3. label="plunge"   → descend to cut_z (penetrate tissue)
  4. label="drag_end" → move to end XY at same cut_z (make the cut)
  5. label="retract"  → ascend back to z={SAFE_Z_CM}
  arm2 moves to a hold position lateral to the incision site before arm1 begins.

"biopsy": arm1 follows this waypoint sequence (single point, NO drag):
  1. label="transit"  → move to target XY at z={SAFE_Z_CM}
  2. label="approach" → descend to z=TABLE_Z + 0.2
  3. label="plunge"   → descend to sample_z (slightly deeper than a 3mm incision,
                        Python computes the final number — do not invent it)
  4. label="retract"  → ascend straight back up to z={SAFE_Z_CM} at the SAME XY
  arm2 moves to a hold position lateral to the target, same as incision.

"cauterization": arm1 follows this waypoint sequence (single point, WITH dwell):
  1. label="transit"  → move to target XY at z={SAFE_Z_CM}
  2. label="approach" → descend to z=TABLE_Z + 0.2
  3. label="plunge"   → descend to cauterize_z and DWELL there
                        (Python attaches the dwell time — do not invent timing)
  4. label="retract"  → ascend straight back up to z={SAFE_Z_CM} at the SAME XY
  arm2 moves to a hold position lateral to the target, same as incision.

"debridement": arm1 sweeps a small zigzag grid over the target region at a
  shallow Z (just above TABLE_Z, gentle contact) instead of a single drag:
  1. label="transit"    → move to the first sweep corner at z={SAFE_Z_CM}
  2. label="approach"   → descend to sweep_z (shallow — Python computes this)
  3. label="sweep_1", "sweep_2", ... → traverse a zigzag covering the region
     (each row offset slightly in Y, alternating +X/-X direction)
  4. label="retract"    → ascend back to z={SAFE_Z_CM}
  arm2 holds clear of the swept region, same lateral-offset logic as incision.

"suturing": demo closure pattern — arm1 places a short row of simple
  stitches across the incision line. This is a SIMPLIFIED VISUAL DEMO of
  suturing (not a real needle-and-thread mechanism); the tool tip itself
  traces the stitch motion. For each stitch, in order, left to right:
  1. label="transit"  → move above the entry point at z={SAFE_Z_CM}
  2. label="approach" → descend to z=TABLE_Z + 0.2 above entry
  3. label="entry"    → plunge at the entry point (Python computes depth)
  4. label="loop"     → rise to a shallow arc above the table, roughly
     midway between entry and exit (simulates the needle passing under
     the tissue and back up)
  5. label="exit"     → descend at the exit point, same depth as entry
  6. label="cinch"    → rise slightly and DWELL briefly (Python attaches
     the dwell time — do not invent it), simulating the thread being
     pulled tight
  Repeat this 6-step pattern for each stitch (label each stitch's steps
  "stitch1_transit", "stitch1_approach", ... "stitch2_transit", etc.),
  then a final label="retract" back to z={SAFE_Z_CM}.
  arm2 moves to a hold position lateral to the stitch row, same as incision.
  Default to 3 stitches evenly spaced along the incision line unless the
  command specifies a different count.

"retraction": arm2 moves to a tissue-hold position. arm1 idles or assists.

"hold": both arms hold current positions. Output current positions as single waypoints.

"home": both arms move to home position (x=10.0, y=0.0, z={SAFE_Z_CM}).

"abort": both arms move immediately to safe height z={SAFE_Z_CM}, then home.

=== LANDMARK SEMANTICS ===
- landmark_A = PRIMARY incision target (where the incision begins or is centered).
- landmark_B = SECONDARY reference (retraction target, second incision end, or reference).
- landmark_C = TERTIARY reference (optional additional reference point).
- If the command references "the target site", "the mark", or "there" → use landmark_A.
- CRITICAL: Use the EXACT x,y coordinates from the scene state for all waypoints.
  Do NOT round, approximate, or recompute landmark positions.
  If landmark_A is at x=-5.22, y=+3.68 in the scene state, ALL arm1 waypoints
  must use x=-5.22, y=+3.68. Never substitute different coordinates.
- If the command says "between A and B" → compute midpoint; incision vector = A→B direction.
- Incision length is ALWAYS computed from landmark positions or stated explicitly.
  Never guess. If the length is ambiguous, use 3mm as default and note it in safety_notes.

=== FEED RATES ===
- Incision drag: 1.0–3.0 mm/s (default 2.0)
- Approach/plunge: 0.5–1.5 mm/s (default 1.0)
- Transit/retraction: 5.0–15.0 mm/s (default 10.0)
- NEVER exceed 15.0 mm/s for any arm.

=== JSON SCHEMA (output EXACTLY this structure) ===
{{
  "procedure": "<incision|biopsy|cauterization|debridement|retraction|hold|home|abort>",
  "rationale": "<one sentence explaining the plan>",
  "arm1": {{
    "role": "<cutting|retracting|holding|idle>",
    "waypoints": [
      {{"x": <float_cm>, "y": <float_cm>, "z": <float_cm>, "label": "<label>"}}
    ],
    "feed_rate_mm_s": <float>
  }},
  "arm2": {{
    "role": "<cutting|retracting|holding|idle>",
    "waypoints": [
      {{"x": <float_cm>, "y": <float_cm>, "z": <float_cm>, "label": "<label>"}}
    ],
    "feed_rate_mm_s": <float>
  }},
  "estimated_duration_s": <float>,
  "safety_notes": "<any flags, assumptions, or warnings>"
}}

=== HARD RULES (never violate) ===
1. ALWAYS use landmark coordinates EXACTLY as given in the scene state JSON.\n
   Never compute or estimate landmark positions yourself.\n
2. Z < {TABLE_Z_CM - 0.5} is forbidden. Refuse and set procedure="abort".
3. Reach outside [{MIN_REACH}, {MAX_REACH}] cm is forbidden. Clamp or abort.
4. If the command is ambiguous and could cause tissue damage, set procedure="abort"
   and explain in safety_notes.
5. Never output any text outside the JSON object.
6. All numeric values must be pre-computed floats rounded to 2 decimal places.
   No expressions like "TABLE_Z - 0.3" — compute the actual number.
""".strip()


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class Waypoint:
    x:       float
    y:       float
    z:       float
    label:   str = ""
    dwell_s: float = 0.0   # extra dwell time at this waypoint beyond the standard pause
                            # (used by cauterization to hold contact for a burn)

    def as_tuple(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)

    def as_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "z": self.z,
                "label": self.label, "dwell_s": self.dwell_s}


@dataclass
class ArmPlan:
    arm_id:         int
    role:           str
    waypoints:      list[Waypoint]
    feed_rate_mm_s: float


@dataclass
class ProcedurePlan:
    """
    Parsed and lightly validated output of one SurgicalAgent call.

    This is what the ProcedureValidator receives.
    The raw JSON string is preserved for audit logging.
    """
    procedure:          str
    rationale:          str
    arm1:               ArmPlan
    arm2:               ArmPlan
    estimated_duration_s: float
    safety_notes:       str
    raw_json:           str = ""
    timestamp:          float = field(default_factory=time.monotonic)

    def all_waypoints(self) -> dict[int, list[Waypoint]]:
        return {1: self.arm1.waypoints, 2: self.arm2.waypoints}


class SurgicalAgentError(Exception):
    """Raised when the LLM returns unrecoverable output."""


# ---------------------------------------------------------------------------
# SurgicalAgent
# ---------------------------------------------------------------------------

class SurgicalAgent:
    """
    Groq-powered NL → ProcedurePlan translator.

    Parameters
    ----------
    api_key : str, optional
        Groq API key.  If None, reads from GROQ_API_KEY env var.
    model : str
        Groq model name.
    """

    def __init__(
        self,
        api_key:  Optional[str] = None,
        model:    str = GROQ_MODEL,
    ) -> None:
        key = api_key or os.environ.get("GROQ_API_KEY")
        if not key:
            raise EnvironmentError(
                "GROQ_API_KEY not set.  Export it or pass api_key= to SurgicalAgent()."
            )
        self._client = Groq(api_key=key)
        self._model  = model
        logger.info("SurgicalAgent ready.  Model=%s", self._model)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def plan(
        self,
        command:     str,
        scene_state: SceneState,
    ) -> ProcedurePlan:
        """
        Translate a natural-language surgical command into a ProcedurePlan.

        Parameters
        ----------
        command : str
            E.g. "make a 3mm incision at landmark A".
        scene_state : SceneState
            Current perception snapshot (arms + landmarks).

        Returns
        -------
        ProcedurePlan

        Raises
        ------
        SurgicalAgentError
            If the LLM fails to produce valid JSON after MAX_RETRIES attempts.
        """
        warnings = scene_state.validate()
        if warnings:
            logger.warning("SceneState warnings before planning: %s", warnings)

        user_msg = self._build_user_message(command, scene_state)
        logger.info("Planning command: %r", command)

        messages: list[dict] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ]

        last_error: Optional[Exception] = None
        raw = ""

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                raw = self._call_groq(messages)
                plan = self._parse_response(raw)
                logger.info(
                    "Plan ready: procedure=%s  duration=%.1fs  (attempt %d)",
                    plan.procedure, plan.estimated_duration_s, attempt,
                )
                return plan

            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                last_error = exc
                logger.warning("Attempt %d parse failure: %s", attempt, exc)
                if attempt < MAX_RETRIES:
                    # Feed the error back for self-correction
                    messages.append({"role": "assistant", "content": raw})
                    messages.append({
                        "role": "user",
                        "content": (
                            f"Your response was not valid JSON.  Error: {exc}\n"
                            "Output ONLY the corrected JSON object."
                        ),
                    })

        raise SurgicalAgentError(
            f"LLM failed to produce valid ProcedurePlan JSON after "
            f"{MAX_RETRIES} attempts.  Last error: {last_error}"
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_user_message(self, command: str, state: SceneState) -> str:
        return (
            f"COMMAND: {command}\n\n"
            f"{state.to_prompt_block()}"
        )

    def _call_groq(self, messages: list[dict]) -> str:
        """
        Call the Groq API and return the raw text content of the response.

        JSON mode guarantees the content is a single well-formed JSON object,
        so no seeding or fence-stripping is needed on the happy path.
        """
        t0 = time.monotonic()
        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            response_format={"type": "json_object"},
        )
        elapsed = (time.monotonic() - t0) * 1000
        logger.debug("Groq API call: %.0f ms", elapsed)

        content = response.choices[0].message.content or ""
        return content.strip()

    def _parse_response(self, raw: str) -> ProcedurePlan:
        """
        Parse the raw JSON string from the LLM into a ProcedurePlan.

        Strips any accidental markdown fences before parsing.
        Raises ValueError on schema violations.
        """
        # Strip markdown code fences if the model added them despite instructions
        clean = raw.strip()
        if clean.startswith("```"):
            lines = clean.splitlines()
            clean = "\n".join(
                l for l in lines
                if not l.strip().startswith("```")
            ).strip()

        data: dict[str, Any] = json.loads(clean)

        # Validate top-level required fields
        for key in ("procedure", "rationale", "arm1", "arm2",
                    "estimated_duration_s", "safety_notes"):
            if key not in data:
                raise ValueError(f"Missing required key: '{key}'")

        def _parse_arm(arm_data: dict, arm_id: int) -> ArmPlan:
            wps = []
            for wp in arm_data.get("waypoints", []):
                wps.append(Waypoint(
                    x=float(wp["x"]),
                    y=float(wp["y"]),
                    z=float(wp["z"]),
                    label=str(wp.get("label", "")),
                    dwell_s=float(wp.get("dwell_s", 0.0)),
                ))
            feed = float(arm_data.get("feed_rate_mm_s", DEFAULT_FEED_RATES.get(
                data["procedure"], 5.0
            )))
            feed = max(FEED_RATE_MIN_MM_S, min(feed, FEED_RATE_MAX_MM_S))
            return ArmPlan(
                arm_id=arm_id,
                role=str(arm_data.get("role", "idle")),
                waypoints=wps,
                feed_rate_mm_s=feed,
            )

        return ProcedurePlan(
            procedure=str(data["procedure"]),
            rationale=str(data["rationale"]),
            arm1=_parse_arm(data["arm1"], arm_id=1),
            arm2=_parse_arm(data["arm2"], arm_id=2),
            estimated_duration_s=float(data.get("estimated_duration_s", 0.0)),
            safety_notes=str(data.get("safety_notes", "")),
            raw_json=raw,
        )


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    from .scene_state import ArmState, LandmarkState

    state = SceneState(
        arms=[
            ArmState(arm_id=1, x=8.0,  y=2.0, z=10.0),
            ArmState(arm_id=2, x=14.0, y=2.0, z=10.0),
        ],
        landmarks=[
            LandmarkState(name="landmark_A", x=11.0, y=1.0, z=7.5, confidence=0.91),
        ],
        tool_z_offset_cm=0.15,
    )

    agent = SurgicalAgent()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "make a 3mm incision at landmark A"
    plan = agent.plan(cmd, state)

    print(f"\nProcedure : {plan.procedure}")
    print(f"Rationale : {plan.rationale}")
    print(f"Duration  : {plan.estimated_duration_s:.1f}s")
    print(f"Safety    : {plan.safety_notes}")
    print(f"\nArm1 ({plan.arm1.role}) @ {plan.arm1.feed_rate_mm_s} mm/s:")
    for wp in plan.arm1.waypoints:
        print(f"  [{wp.label}]  ({wp.x:+.2f}, {wp.y:+.2f}, {wp.z:.2f})")
    print(f"\nArm2 ({plan.arm2.role}) @ {plan.arm2.feed_rate_mm_s} mm/s:")
    for wp in plan.arm2.waypoints:
        print(f"  [{wp.label}]  ({wp.x:+.2f}, {wp.y:+.2f}, {wp.z:.2f})")