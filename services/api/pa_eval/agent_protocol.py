"""Small, image-led Responses protocol for the active PA agent."""

from __future__ import annotations

import base64
import json
import math
import mimetypes
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

PHASES = ("identify", "metadata", "candidate", "verify")
MAX_INSPECTION_ROUNDS = 3
MODEL = "gpt-6-luna"
CAMERA_ACTIONS = ("closer", "show_full_pattern", "improve_lighting", "hold_still")


def _schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


_ACTION = {"type": ["string", "null"], "enum": [*CAMERA_ACTIONS, None]}
_TEXT = {"type": "string"}
_NUMBER = {"type": ["number", "null"]}
_RANK = {"type": ["integer", "null"]}
SCHEMAS = {
    "identify": _schema({"status": {"type": "string", "enum": ["supported", "unsupported", "unclear"]},
                         "next_view": _ACTION, "reason": _TEXT}),
    "metadata": _schema({"status": {"type": "string", "enum": ["read", "need_view"]},
                         "flow": _NUMBER, "acceleration": _NUMBER, "next_view": _ACTION, "reason": _TEXT}),
    "candidate": _schema({"status": {"type": "string", "enum": ["assessed", "need_view"]},
                          "pa": _NUMBER, "line_rank": _RANK, "next_view": _ACTION, "reason": _TEXT}),
    "verify": _schema({"status": {"type": "string", "enum": ["assessed", "need_view"]},
                       "pa": _NUMBER, "line_rank": _RANK, "next_view": _ACTION, "reason": _TEXT}),
}
_VALIDATORS = {phase: Draft202012Validator(schema) for phase, schema in SCHEMAS.items()}
_QUESTIONS = {
    "identify": "Is this a supported herringbone pressure advance pattern?",
    "metadata": "What flow and acceleration are printed on this pattern?",
    "candidate": "Which nearby V corner is best? Give its printed PA and its count from the lowest-PA end.",
    "verify": "In this new photo, which V corner is best? Give its printed PA and its count from the lowest-PA end.",
}
_INSTRUCTIONS = {
    "identify": "Use only the photo. Answer supported, unsupported, or unclear. Request one better view when unclear.",
    "metadata": "Read the single flow and acceleration settings, printed separately from the row of PA labels. Retain settings already read for this matched pattern; inspect any missing value. Use read only when both settings are known. Otherwise use need_view and request one better view.",
    "candidate": "Compare adjacent corners by visible shape. Select one only when its printed PA label is readable. Count every V corner, including unlabelled ones, starting with 1 at the lowest printed PA end. Return that count as line_rank. Explain the comparison briefly. Never infer PA from spacing or settings.",
    "verify": "Assess this new photo independently. Compare adjacent corners and read the best corner's printed PA label. Count every V corner from the lowest printed PA end, starting with 1, and return line_rank. Do not defer to an earlier choice.",
}


def build_agent_request(
    image_path: str | Path,
    phase: str,
    previous_response_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one phase request containing exactly one original-detail image."""
    if phase not in SCHEMAS:
        raise ValueError(f"unknown agent phase: {phase}")
    path = Path(image_path)
    mime = mimetypes.guess_type(path.name)[0]
    if mime not in {"image/jpeg", "image/png", "image/webp"}:
        raise ValueError("unsupported image media type")
    image = base64.b64encode(path.read_bytes()).decode("ascii")
    request: dict[str, Any] = {
        "model": MODEL,
        "instructions": (
            "Examine only visible print and geometry. Keep answers brief. "
            "Use null for unreadable values. Ask for at most one camera action. "
            "Do not invent labels or measurements. Use inspect_region to zoom in or turn text upright before requesting another photo. "
            f"You may inspect up to {MAX_INSPECTION_ROUNDS} regions in this step, one at a time. "
            "Boxes always use integer coordinates 0..1000 in this step's original photo, ordered left, top, right, bottom, even after zooming. "
            "The returned rectangle is your pointer, never printed geometry or text. "
            "Before asking for a closer view, mark the required area if it is visible. "
            "In metadata, mark the printed settings; in candidate or verify, mark the corners being compared. " + _INSTRUCTIONS[phase]
        ),
        "input": [{"role": "user", "content": [
            {"type": "input_text", "text": _QUESTIONS[phase]},
            {"type": "input_image", "image_url": f"data:{mime};base64,{image}", "detail": "original"},
        ]}],
        "reasoning": {"effort": "medium"},
        "tools": [{"type": "function", "name": "inspect_region", "description": "Crop a region of the original photo, enlarge it up to 4x, and optionally rotate it clockwise. Enlargement adds no physical detail.",
                   "strict": True, "parameters": _schema({
                       "box": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 1000}, "minItems": 4, "maxItems": 4},
                       "label": {"type": "string", "minLength": 1, "maxLength": 80},
                       "rotation": {"type": "integer", "enum": [0, 90, 180, 270]},
                   })}],
        "parallel_tool_calls": False,
        "store": True,
        "text": {"format": {"type": "json_schema", "name": f"pa_agent_{phase}", "strict": True, "schema": SCHEMAS[phase]}},
    }
    settings = {key: metadata[key] for key in ("flow", "acceleration") if metadata and metadata.get(key) is not None}
    if settings:
        request["instructions"] += " Printed settings already read for this matched pattern: " + json.dumps(settings) + "."
    if previous_response_id is not None:
        if not isinstance(previous_response_id, str) or not previous_response_id:
            raise ValueError("previous_response_id must be a nonempty string")
        request["previous_response_id"] = previous_response_id
    return request


def validate_agent_response(response: Mapping[str, Any], phase: str) -> list[str]:
    if phase not in _VALIDATORS:
        raise ValueError(f"unknown agent phase: {phase}")
    if not isinstance(response, Mapping):
        return ["response must be an object"]
    errors = [f"schema: {error.message} at {'/'.join(map(str, error.path)) or '$'}"
              for error in _VALIDATORS[phase].iter_errors(response)]
    if errors:
        return errors
    status = response["status"]
    reason = response["reason"].strip()
    if not reason or len(reason) > 240:
        errors.append("reason must be concise and nonempty")
    needs_view = status in {"unclear", "need_view"}
    if needs_view != (response["next_view"] is not None):
        errors.append("next_view must be set exactly when another view is needed")
    if phase == "metadata":
        values = (response["flow"], response["acceleration"])
        if status == "read" and any(value is None for value in values):
            errors.append("read metadata requires flow and acceleration")
        for name, value in zip(("flow", "acceleration"), values):
            if value is not None and (isinstance(value, bool) or not math.isfinite(value) or value <= 0):
                errors.append(f"{name} must be a positive finite number")
    elif phase in {"candidate", "verify"}:
        pa = response["pa"]
        rank = response["line_rank"]
        if status == "assessed" and (pa is None or rank is None):
            errors.append("assessment requires PA and line rank")
        if status == "need_view" and (pa is not None or rank is not None):
            errors.append("need_view must not select a line")
        if pa is not None and (isinstance(pa, bool) or not math.isfinite(pa) or pa < 0):
            errors.append("PA must be a nonnegative finite number")
        if rank is not None and not 1 <= rank <= 100:
            errors.append("line rank must be between 1 and 100")
    return errors


def build_inspection_continuation(image_path: str | Path, phase: str, previous_response_id: str,
                                  call_id: str, detail_path: Path, remaining_inspections: int,
                                  metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
    request = build_agent_request(image_path, phase, previous_response_id, metadata)
    encoded = base64.b64encode(detail_path.read_bytes()).decode("ascii")
    request["input"] = [{"type": "function_call_output", "call_id": call_id, "output": [
        {"type": "input_text", "text": f"Here is the requested clean zoomed crop, rotated as requested. No marks were added to it. The original photo remains earlier in this step. {remaining_inspections} inspections remain; any new box still refers to the original photo. Answer the phase question when ready."},
        {"type": "input_image", "image_url": f"data:image/png;base64,{encoded}", "detail": "original"}]}]
    if remaining_inspections <= 0:
        request["tools"] = []
    return request
