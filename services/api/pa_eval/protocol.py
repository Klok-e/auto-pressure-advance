"""Frozen v2 image request and response validation for the PA feasibility pilot."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import mimetypes
from pathlib import Path
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[3]
PROMPT_PATH = ROOT / "fixtures/protocol/prompt-v2.txt"
SCHEMA_PATH = ROOT / "fixtures/protocol/schema-v2.json"
PROTOCOL_VERSION = "v2"
MODEL = "gpt-6-luna"
ENDPOINT = "https://api.openai.com/v1/responses"
PROMPT = PROMPT_PATH.read_text()
SCHEMA = json.loads(SCHEMA_PATH.read_text())
PROMPT_SHA256 = hashlib.sha256(PROMPT_PATH.read_bytes()).hexdigest()
SCHEMA_SHA256 = hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest()
_VALIDATOR = Draft202012Validator(SCHEMA)


def build_request(inputs: Sequence[Mapping[str, Any]], previous_response_id: str | None = None) -> dict[str, Any]:
    """Build one immutable-protocol Responses request from prepared pattern crops.

    Each input has observation_id, image_path, and sha256. Detector-derived
    source_bbox and source_size locate a crop in the oriented source image.
    Input order is the frozen bundle order; callers never pass reference data.
    """
    if not inputs:
        raise ValueError("an image bundle must contain at least one observation")
    content: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in inputs:
        observation_id = item["observation_id"]
        if not isinstance(observation_id, str) or not observation_id or observation_id in seen:
            raise ValueError("observation IDs must be nonempty and unique within a bundle")
        seen.add(observation_id)
        path = Path(item["image_path"])
        image = path.read_bytes()
        digest = hashlib.sha256(image).hexdigest()
        if digest != item["sha256"]:
            raise ValueError(f"image hash mismatch for {observation_id}")
        mime = mimetypes.guess_type(path.name)[0]
        if mime not in {"image/jpeg", "image/png", "image/webp"}:
            raise ValueError(f"unsupported image media type for {observation_id}")
        source_bbox = item.get("source_bbox")
        source_size = item.get("source_size")
        if (source_bbox is None) != (source_size is None):
            raise ValueError(f"source_bbox and source_size must be supplied together for {observation_id}")
        location = "Displayed image is the complete oriented source observation."
        bounds = (0.0, 1.0, 0.0, 1.0)
        if source_bbox is not None and source_size is not None:
            if (len(source_bbox) != 4 or len(source_size) != 2
                    or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in (*source_bbox, *source_size))):
                raise ValueError(f"invalid source geometry for {observation_id}")
            left, top, right, bottom = source_bbox
            width, height = source_size
            if not (0 <= left < right <= width and 0 <= top < bottom <= height):
                raise ValueError(f"source crop lies outside oriented image for {observation_id}")
            location = (
                f"Displayed crop rectangle in oriented source pixels: [{left}, {top}, {right}, {bottom}]. "
                f"Oriented source dimensions: width={width}, height={height}. "
                "Map any displayed crop point (u,v), normalized from 0 to 1, to oriented source normalized "
                "coordinates x=(left+u*(right-left))/width, y=(top+v*(bottom-top))/height."
            )
            scale = 1_000_000_000
            bounds = (
                math.ceil(left / width * scale) / scale,
                math.floor(right / width * scale) / scale,
                math.ceil(top / height * scale) / scale,
                math.floor(bottom / height * scale) / scale,
            )
        limits = (
            f"Normalized oriented-source crop bounds for this observation: "
            f"x_min={bounds[0]:.9f}, x_max={bounds[1]:.9f}, "
            f"y_min={bounds[2]:.9f}, y_max={bounds[3]:.9f}."
        )
        content.append({"type": "input_text", "text": f"Observation ID: {observation_id}; image SHA-256: {digest}. {location} {limits}"})
        content.append({"type": "input_image", "image_url": f"data:{mime};base64,{base64.b64encode(image).decode('ascii')}", "detail": "original"})
    request: dict[str, Any] = {
        "model": MODEL,
        "instructions": PROMPT,
        "input": [{"role": "user", "content": content}],
        "reasoning": {"effort": "medium"},
        "tools": [],
        "store": True,
        "text": {"format": {"type": "json_schema", "name": "pa_pattern_v2", "strict": True, "schema": SCHEMA}},
    }
    if previous_response_id is not None:
        if not previous_response_id:
            raise ValueError("previous_response_id cannot be empty")
        request["previous_response_id"] = previous_response_id
    return request


def _same_number(a: Any, b: Any) -> bool:
    return isinstance(a, (float, int)) and not isinstance(a, bool) and isinstance(b, (float, int)) and not isinstance(b, bool) and math.isclose(a, b, rel_tol=0, abs_tol=1e-8)


def validate_response(response: Mapping[str, Any], context: Mapping[str, Any]) -> list[str]:
    """Validate model JSON against the frozen schema and independent trial context.

    Context requires allowed_observation_ids. Optional keys are verified_identity,
    verified_metadata, known_labels, candidate_values, previous_response, and
    new_observation_ids, crop_bounds (observation ID to normalized xyxy), and
    allowed_label_values (printed PA values independent of model line IDs).
    The independent values are used only after inference.
    """
    errors = [f"schema: {error.message} at {'/'.join(map(str, error.path)) or '$'}" for error in _VALIDATOR.iter_errors(response)]
    if errors:
        return errors
    allowed = set(context.get("allowed_observation_ids", []))
    new = set(context.get("new_observation_ids", []))
    if not allowed:
        errors.append("allowed_observation_ids is empty")
    if not new.issubset(allowed):
        errors.append("new_observation_ids contains an unknown observation")
    crop_bounds = context.get("crop_bounds", {})

    def within_crop(observation_id: str, x: float, y: float) -> bool:
        bounds = crop_bounds.get(observation_id)
        return bounds is None or (len(bounds) == 4 and bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3])

    def evidence(ids: list[str], where: str, required: bool = True) -> None:
        if required and not ids:
            errors.append(f"{where}: evidence is required")
        for observation_id in ids:
            if observation_id not in allowed:
                errors.append(f"{where}: unknown evidence observation {observation_id}")

    identity = response["pattern_identity"]
    evidence(identity["evidence_ids"], "pattern_identity", bool(identity["pattern_id"]))
    verified_identity = context.get("verified_identity")
    if verified_identity is not None and identity["pattern_id"] != verified_identity:
        errors.append("changed verified pattern identity")

    metadata = response["metadata"]
    verified_metadata = context.get("verified_metadata", {})
    previous = context.get("previous_response")
    for name in ("flow", "acceleration"):
        field = metadata[name]
        value = field["value"]
        source = field["source"]
        evidence(field["evidence_ids"], f"metadata.{name}", value is not None)
        if (value is None) != (source == "unknown"):
            errors.append(f"metadata.{name}: value/source conflict")
        if value is not None and (not math.isfinite(value) or value <= 0):
            errors.append(f"metadata.{name}: invalid value")
        if source == "visible" and new and not (set(field["evidence_ids"]) & new):
            errors.append(f"metadata.{name}: visible value has no current observation evidence")
        if source == "inherited":
            old_field = previous.get("metadata", {}).get(name, {}) if previous else {}
            if not previous or not _same_number(value, old_field.get("value")):
                errors.append(f"metadata.{name}: inherited value does not match previous response")
            if not set(field["evidence_ids"]).intersection(old_field.get("evidence_ids", [])):
                errors.append(f"metadata.{name}: inherited value lacks earlier provenance")
        if name in verified_metadata and value is not None and not _same_number(value, verified_metadata[name]):
            errors.append(f"metadata.{name}: conflicts with verified value")
        if previous and value is not None:
            old_value = previous.get("metadata", {}).get(name, {}).get("value")
            if old_value is not None and not _same_number(value, old_value):
                _check_correction(response, new, errors, f"metadata.{name}")

    lines = response["candidate_lines"]
    line_by_id: dict[str, Mapping[str, Any]] = {}
    for line in lines:
        line_id = line["line_id"]
        if line_id in line_by_id:
            errors.append(f"duplicate candidate line ID {line_id}")
        line_by_id[line_id] = line
        evidence(line["evidence_ids"], f"candidate_lines.{line_id}")
        if not line_id or not line_id.startswith("l") or not line_id[1:].isdigit():
            errors.append(f"invalid candidate line ID {line_id}")
        for feature in line["features"]:
            evidence(feature["evidence_ids"], f"candidate_lines.{line_id}.feature")
            if not feature["description"].strip():
                errors.append(f"candidate_lines.{line_id}: empty feature description")
        apex = line["apex"]
        if apex is not None:
            observation_id = apex["observation_id"]
            x, y = apex["x"], apex["y"]
            if observation_id not in allowed or observation_id not in line["evidence_ids"]:
                errors.append(f"candidate {line_id}: apex has no matching evidence observation")
            if (not math.isfinite(x) or not math.isfinite(y) or not (0 <= x <= 1 and 0 <= y <= 1)
                    or not within_crop(observation_id, x, y)):
                errors.append(f"candidate {line_id}: apex is outside source observation crop")

    labels = response["labels"]
    label_by_id: dict[str, float] = {}
    for label in labels:
        line_id = label["line_id"]
        evidence(label["evidence_ids"], f"labels.{line_id}")
        if line_id in label_by_id:
            errors.append(f"duplicate label on line {line_id}")
        label_by_id[line_id] = label["pa"]
        if line_id not in line_by_id:
            errors.append(f"label refers to nonexistent line {line_id}")
        if not math.isfinite(label["pa"]) or label["pa"] < 0:
            errors.append(f"invalid PA label on {line_id}")
    known_labels = context.get("known_labels", {})
    for line_id, known_pa in known_labels.items():
        if line_id in label_by_id and not _same_number(label_by_id[line_id], known_pa):
            errors.append(f"label {line_id} conflicts with verified printed label")
    allowed_label_values = context.get("allowed_label_values")
    if allowed_label_values is not None:
        for line_id, pa in label_by_id.items():
            if not any(_same_number(pa, allowed_pa) for allowed_pa in allowed_label_values):
                errors.append(f"label {line_id} has an unsupported printed PA value")
    candidate_values = context.get("candidate_values")
    for line in lines:
        line_id, pa, basis = line["line_id"], line["pa"], line["mapping_basis"]
        anchors = line["anchor_line_ids"]
        if pa is not None and (not math.isfinite(pa) or pa < 0):
            errors.append(f"candidate {line_id}: invalid PA")
        if candidate_values is not None and pa is not None and not any(_same_number(pa, value) for value in candidate_values):
            errors.append(f"candidate {line_id}: PA outside independently verified candidate values")
        if basis == "unresolved" and pa is not None:
            errors.append(f"candidate {line_id}: unresolved mapping has a PA")
        if basis == "visible_label" and (line_id not in label_by_id or not _same_number(pa, label_by_id.get(line_id)) or anchors):
            errors.append(f"candidate {line_id}: visible-label mapping is unsupported")
        if basis == "anchor_order":
            if pa is None or len(anchors) != 2 or len(set(anchors)) != 2 or any(anchor not in label_by_id for anchor in anchors):
                errors.append(f"candidate {line_id}: anchor mapping needs two visible labels")
            else:
                a, b = anchors
                indices = (int(a[1:]), int(b[1:]), int(line_id[1:])) if all(x.startswith('l') and x[1:].isdigit() for x in (a, b, line_id)) else None
                if not indices or not min(indices[:2]) < indices[2] < max(indices[:2]):
                    errors.append(f"candidate {line_id}: physical order is outside anchors")
                else:
                    expected = label_by_id[a] + (label_by_id[b] - label_by_id[a]) * (indices[2] - indices[0]) / (indices[1] - indices[0])
                    if not _same_number(pa, expected):
                        errors.append(f"candidate {line_id}: PA is unsupported by anchors and physical order")
    if previous:
        old_lines = {line["line_id"]: line for line in previous.get("candidate_lines", [])}
        for line_id, line in line_by_id.items():
            old_pa = old_lines.get(line_id, {}).get("pa")
            if old_pa is not None and line["pa"] is not None and not _same_number(line["pa"], old_pa):
                _check_correction(response, new, errors, f"candidate {line_id}")
        old_labels = {label["line_id"]: label["pa"] for label in previous.get("labels", [])}
        for line_id, pa in label_by_id.items():
            if line_id in old_labels and not _same_number(pa, old_labels[line_id]):
                _check_correction(response, new, errors, f"label {line_id}")

    assessment = response["assessment"]
    evidence(assessment["evidence_ids"], "assessment", assessment["status"] != "unsupported")
    for line_id in assessment["plausible_line_ids"]:
        if line_id not in line_by_id:
            errors.append(f"assessment: nonexistent plausible line {line_id}")
    selected = assessment["selected_line_id"]
    selected_pa = assessment["selected_pa"]
    if assessment["status"] == "conclusive":
        if selected not in line_by_id or selected_pa is None or not _same_number(selected_pa, line_by_id[selected]["pa"]):
            errors.append("conclusive assessment has unsupported selected line or PA")
        if selected in line_by_id and line_by_id[selected]["apex"] is None:
            errors.append("conclusive assessment lacks a localized selected line apex")
        if not response["supported_pattern"]:
            errors.append("unsupported pattern cannot have a conclusive assessment")
        if assessment["contradiction"]:
            errors.append("material contradiction cannot have a conclusive assessment")
    elif selected is not None or selected_pa is not None:
        errors.append("non-conclusive assessment must not select a line or PA")
    if assessment["status"] == "inconclusive" and not assessment["uncertainty"].strip():
        errors.append("inconclusive assessment needs uncertainty")
    if assessment["contradiction"] != bool(assessment["contradiction_reason"]):
        errors.append("contradiction flag/reason conflict")
    if previous:
        old = previous.get("assessment", {})
        if old.get("selected_line_id") is not None and old["selected_line_id"] != selected:
            _check_correction(response, new, errors, "assessment")
        if previous.get("pattern_identity", {}).get("pattern_id") and identity["pattern_id"] != previous["pattern_identity"]["pattern_id"]:
            _check_correction(response, new, errors, "pattern_identity")

    target = response["inspection_target"]
    if target is not None:
        if target["observation_id"] not in allowed:
            errors.append("inspection_target: unknown source observation")
        box = target["box"]
        if len(box) != 4 or any(not math.isfinite(v) or v < 0 or v > 1 for v in box) or (len(box) == 4 and not (box[0] < box[2] and box[1] < box[3])):
            errors.append("inspection_target: invalid normalized box")
        elif target["observation_id"] in crop_bounds:
            bounds = crop_bounds[target["observation_id"]]
            if len(bounds) != 4 or not (bounds[0] <= box[0] < box[2] <= bounds[2] and bounds[1] <= box[1] < box[3] <= bounds[3]):
                errors.append("inspection_target: box lies outside supplied source crop")
        if not target["reason"].strip():
            errors.append("inspection_target: empty reason")
    return errors


def _check_correction(response: Mapping[str, Any], new: set[str], errors: list[str], where: str) -> None:
    assessment = response["assessment"]
    if not assessment["contradiction"] or not assessment["contradiction_reason"]:
        errors.append(f"{where}: changed assessment without explicit contradiction")
    if not new or not (set(assessment["evidence_ids"]) & new):
        errors.append(f"{where}: correction lacks new observation evidence")
