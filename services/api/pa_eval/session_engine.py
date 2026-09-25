"""Analyze selected camera stills without using experiment answer keys."""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from pathlib import Path
from typing import Any

from PIL import Image

from . import vision
from .protocol import validate_response
from .provider import LiveProvider, ProviderError, RecordedProvider


MAX_MODEL_CALLS = 24
MAX_MODEL_COST_USD = 2.0
MAX_VIEWS_PER_PATTERN = 4


def _guidance(action: str, reason: str, target: dict | None = None) -> dict:
    return {"action": action, "reason": reason, "target": target}


def _region_match(image_path: Path, region: dict, patterns: list[dict]) -> tuple[dict | None, list[dict]]:
    matches = []
    evidence = []
    for pattern in patterns:
        old_path = pattern.get("last_image_path")
        old_box = pattern.get("last_region")
        if not old_path or not old_box or not Path(old_path).exists():
            continue
        result = vision.match_regions(old_path, tuple(old_box), image_path, tuple(region["bbox"]))
        if result["status"] == "matched":
            matches.append(pattern)
            evidence.append({"pattern_id": pattern["id"], "registration": result})
    return (matches[0] if len(matches) == 1 else None), evidence


def _crop_bounds(box: tuple[int, int, int, int], size: tuple[int, int]) -> list[float]:
    left, top, right, bottom = box
    width, height = size
    scale = 1_000_000_000
    return [
        math.ceil(left / width * scale) / scale,
        math.ceil(top / height * scale) / scale,
        math.floor(right / width * scale) / scale,
        math.floor(bottom / height * scale) / scale,
    ]


def _candidate_measurement(response: dict, previous: dict | None, observation_id: str) -> dict | None:
    assessment = response["assessment"]
    if not previous or not response["supported_pattern"] or assessment["status"] != "conclusive" or assessment["contradiction"]:
        return None
    if observation_id not in assessment["evidence_ids"]:
        return None
    flow = response["metadata"]["flow"]
    acceleration = response["metadata"]["acceleration"]
    if flow["value"] is None or acceleration["value"] is None:
        return None
    if flow["source"] not in {"visible", "inherited"} or acceleration["source"] not in {"visible", "inherited"}:
        return None
    line = next((line for line in response["candidate_lines"] if line["line_id"] == assessment["selected_line_id"]), None)
    if line is None or observation_id not in line["evidence_ids"] or not line["apex"] or line["apex"]["observation_id"] != observation_id:
        return None
    if line["mapping_basis"] not in {"visible_label", "anchor_order"} or line["pa"] is None:
        return None
    if not math.isclose(line["pa"], assessment["selected_pa"], abs_tol=1e-8):
        return None
    return {
        "pa": assessment["selected_pa"],
        "flow": flow["value"],
        "acceleration": acceleration["value"],
        "line_id": line["line_id"],
        "evidence_ids": sorted(set(assessment["evidence_ids"] + line["evidence_ids"] + flow["evidence_ids"] + acceleration["evidence_ids"])),
        "status": "confirmed",
    }


def analyze_observation(
    image_path: Path,
    observation_id: str,
    patterns: list[dict],
    work_dir: Path,
    provider: LiveProvider | RecordedProvider,
) -> dict:
    """Return complete pattern state updates, guidance, and diagnostic events."""
    image_path = Path(image_path)
    image_sha256 = hashlib.sha256(image_path.read_bytes()).hexdigest()
    events: list[dict[str, Any]] = [{"event": "observation_started", "observation_id": observation_id, "image_sha256": image_sha256}]
    if any(image_sha256 in pattern.get("source_hashes", []) for pattern in patterns):
        events.append({"event": "repeated_image", "observation_id": observation_id, "image_sha256": image_sha256})
        return {"patterns": patterns, "guidance": _guidance("closer", "This view was already analyzed; change the view before another capture."), "events": events, "usage": {"calls": 0, "cost_usd": 0.0}}

    with Image.open(image_path) as image:
        size = image.size
    regions = vision.locate_regions(image_path)
    events.append({"event": "regions_detected", "observation_id": observation_id, "image_size": list(size), "count": len(regions), "boxes": [list(region["bbox"]) for region in regions]})
    if not regions:
        return {"patterns": patterns, "guidance": _guidance("show_full_pattern", "No complete PA pattern was detected."), "events": events, "usage": {"calls": 0, "cost_usd": 0.0}}

    call_count = sum(int(pattern.get("model_calls", 0)) for pattern in patterns)
    cost_total = sum(float(pattern.get("model_cost_usd", 0.0)) for pattern in patterns)
    updates: list[dict] = []
    next_guidance = _guidance("scan_next", "Look for the next PA pattern.")
    for index, region in enumerate(regions):
        matched, registrations = _region_match(image_path, region, patterns)
        events.append({"event": "region_registration", "observation_id": observation_id, "region_index": index, "matches": registrations})
        if len(registrations) > 1:
            next_guidance = _guidance("show_full_pattern", "Pattern identity could not be resolved from this view.")
            events.append({"event": "matching_uncertain", "observation_id": observation_id, "region_index": index})
            continue
        if matched and matched.get("status") == "complete":
            events.append({"event": "completed_pattern_seen", "observation_id": observation_id, "pattern_id": matched["id"]})
            continue
        if matched and image_sha256 in matched.get("source_hashes", []):
            events.append({"event": "repeated_pattern_view", "observation_id": observation_id, "pattern_id": matched["id"]})
            continue

        pattern_id = matched["id"] if matched else uuid.uuid4().hex[:12]
        attempts = int(matched.get("attempts", 0)) + 1 if matched else 1
        previous_response = matched.get("last_response") if matched else None
        previous_response_id = matched.get("last_response_id") if matched else None
        observation_ids = list(dict.fromkeys((matched.get("observation_ids", []) if matched else []) + [observation_id]))
        source_hashes = list(dict.fromkeys((matched.get("source_hashes", []) if matched else []) + [image_sha256]))
        update = dict(matched) if matched else {"id": pattern_id, "model_calls": 0, "model_cost_usd": 0.0}
        update.update({"id": pattern_id, "last_observation_id": observation_id, "last_image_path": str(image_path), "last_region": list(region["bbox"]), "source_sha256": image_sha256, "source_hashes": source_hashes, "observation_ids": observation_ids, "attempts": attempts, "status": "awaiting_detail", "measurement": None})
        if attempts > MAX_VIEWS_PER_PATTERN or call_count >= MAX_MODEL_CALLS or cost_total >= MAX_MODEL_COST_USD:
            update.update(status="inconclusive", reason="inspection_limit_reached")
            updates.append(update)
            next_guidance = _guidance("scan_next", "Inspection limit reached; this pattern remains inconclusive.")
            events.append({"event": "inspection_limit_reached", "observation_id": observation_id, "pattern_id": pattern_id, "attempts": attempts, "calls": call_count, "cost_usd": cost_total})
            continue

        crop = vision.crop_region(image_path, tuple(region["bbox"]), work_dir / "crops" / f"{observation_id}-{index}.png")
        bounds = dict(matched.get("crop_bounds", {})) if matched else {}
        bounds[observation_id] = _crop_bounds(tuple(region["bbox"]), size)
        input_image = {"observation_id": observation_id, "image_path": crop["crop_path"], "sha256": crop["crop_sha256"], "source_bbox": list(region["bbox"]), "source_size": list(size)}
        events.append({"event": "model_request", "observation_id": observation_id, "pattern_id": pattern_id, "crop_sha256": crop["crop_sha256"], "crop_bbox": list(region["bbox"]), "previous_response_id": previous_response_id})
        call_count += 1
        update["model_calls"] = int(update.get("model_calls", 0)) + 1
        try:
            envelope = provider.request([input_image], previous_response_id=previous_response_id)
        except (ProviderError, OSError, ValueError) as error:
            update.update(status="model_error", reason="model_failure")
            updates.append(update)
            next_guidance = _guidance("hold_still", "Analysis could not complete; retry after connection recovers.")
            events.append({"event": "model_error", "observation_id": observation_id, "pattern_id": pattern_id, "error_type": type(error).__name__, "http_status": getattr(error, "status_code", None)})
            continue
        response_path = work_dir / "responses" / f"{observation_id}-{index}.json"
        response_path.parent.mkdir(parents=True, exist_ok=True)
        response_path.write_text(json.dumps(envelope, indent=2) + "\n")
        cost = envelope.get("cost_usd")
        if cost is not None:
            cost_total += float(cost)
            update["model_cost_usd"] = float(update.get("model_cost_usd", 0.0)) + float(cost)
        events.append({"event": "model_response", "observation_id": observation_id, "pattern_id": pattern_id, "response_id": envelope.get("id"), "provider_status": envelope.get("status"), "usage": envelope.get("usage"), "cost_usd": cost, "latency_ms": envelope.get("latency_ms"), "response_path": str(response_path)})
        if envelope.get("status") != "completed" or cost is None:
            update.update(status="model_error", reason="incomplete_or_unaccounted_response")
            updates.append(update)
            next_guidance = _guidance("hold_still", "Analysis did not finish; wait for a retry.")
            continue
        try:
            response = json.loads(envelope["output_text"])
        except (ValueError, TypeError, KeyError) as error:
            update.update(status="inconclusive", reason="malformed_model_response")
            updates.append(update)
            events.append({"event": "validation_failure", "observation_id": observation_id, "pattern_id": pattern_id, "errors": [f"malformed JSON: {error}"]})
            next_guidance = _guidance("closer", "The visual assessment was incomplete; provide a clearer view.")
            continue
        old_metadata = previous_response.get("metadata", {}) if previous_response else {}
        verified_metadata = {name: field["value"] for name, field in old_metadata.items() if field.get("value") is not None and field.get("source") in {"visible", "inherited"}}
        context = {"allowed_observation_ids": observation_ids, "new_observation_ids": [observation_id], "previous_response": previous_response, "verified_identity": (previous_response or {}).get("pattern_identity", {}).get("pattern_id"), "verified_metadata": verified_metadata, "crop_bounds": bounds}
        errors = validate_response(response, context)
        if errors:
            update.update(status="inconclusive", reason="validation_failure", validation_errors=errors)
            updates.append(update)
            next_guidance = _guidance("closer", "A clearer view is needed before accepting visual evidence.")
            events.append({"event": "validation_failure", "observation_id": observation_id, "pattern_id": pattern_id, "errors": errors, "response_id": envelope.get("id")})
            continue
        update.update(last_response=response, last_response_id=envelope.get("id"), crop_bounds=bounds, validation_errors=[])
        measurement = _candidate_measurement(response, matched, observation_id)
        target = response.get("inspection_target")
        update["target"] = target
        if measurement:
            update.update(status="complete", measurement=measurement, reason=None)
            events.append({"event": "measurement_confirmed", "observation_id": observation_id, "pattern_id": pattern_id, "measurement": measurement, "response_id": envelope.get("id")})
            next_guidance = _guidance("scan_next", "This pattern is complete. Find the next one.")
        elif response["assessment"]["status"] == "unsupported" or not response["supported_pattern"]:
            update.update(status="unsupported", reason="unsupported_pattern")
            events.append({"event": "unsupported_pattern", "observation_id": observation_id, "pattern_id": pattern_id})
            next_guidance = _guidance("scan_next", "This is not a supported PA pattern.")
        else:
            reason = "contradiction" if response["assessment"]["contradiction"] else "more_evidence_needed"
            update.update(status="awaiting_detail" if attempts < MAX_VIEWS_PER_PATTERN else "inconclusive", reason=reason)
            next_guidance = _guidance("closer" if target else "show_full_pattern", response["assessment"]["uncertainty"] or "Show a clearer view of the same pattern.", target)
            events.append({"event": "additional_view_needed", "observation_id": observation_id, "pattern_id": pattern_id, "reason": reason, "target": target, "response_id": envelope.get("id")})
        updates.append(update)
    merged = {pattern["id"]: pattern for pattern in patterns}
    merged.update({pattern["id"]: pattern for pattern in updates})
    return {"patterns": list(merged.values()), "guidance": next_guidance, "events": events, "usage": {"calls": call_count - sum(int(pattern.get("model_calls", 0)) for pattern in patterns), "cost_usd": cost_total - sum(float(pattern.get("model_cost_usd", 0.0)) for pattern in patterns)}}
