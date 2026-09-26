"""Advance one physical pattern through focused camera and model turns."""

from __future__ import annotations

import json
import math
import uuid
import time
from pathlib import Path
from typing import Any, Callable

from . import vision
from .agent_protocol import PHASES, validate_agent_response
from .inspection import inspection_call, render_inspection
from .provider import LiveProvider, ProviderError, RecordedProvider


MAX_MODEL_CALLS = 24
MAX_MODEL_COST_USD = 2.0
MAX_VIEWS_PER_PATTERN = 8


def _guidance(action: str, reason: str, phase: str | None = None, target: dict | None = None) -> dict:
    return {"action": action, "reason": reason, "phase": phase, "target": target}


def _logged_envelope(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: "<image omitted; crop stored separately>" if key == "image_url" else _logged_envelope(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [_logged_envelope(item) for item in value]
    return value


def _region_match(image_path: Path, region: dict, patterns: list[dict]) -> tuple[dict | None, list[dict]]:
    matches = []
    registrations = []
    for pattern in patterns:
        old_path = pattern.get("last_image_path")
        old_box = pattern.get("last_region")
        if not old_path or not old_box or not Path(old_path).exists():
            continue
        result = vision.match_regions(old_path, tuple(old_box), image_path, tuple(region["bbox"]))
        if result["status"] == "matched":
            matches.append(pattern)
            registrations.append({"pattern_id": pattern["id"], "registration": result})
    return (matches[0] if len(matches) == 1 else None), registrations


def _advance(update: dict, response: dict, observation_id: str) -> tuple[dict, str]:
    phase = update["agent_phase"]
    status = response["status"]
    if phase == "identify":
        if status == "unsupported":
            update.update(status="unsupported", reason="unsupported_pattern")
            return _guidance("scan_next", "Find another pattern."), "unsupported_pattern"
        if status == "supported":
            update.update(agent_phase="metadata", reason=None)
            return _guidance("closer", "Show the printed flow and acceleration."), "metadata"
    elif phase == "metadata" and status == "read":
        update.update(metadata={"flow": response["flow"], "acceleration": response["acceleration"]},
                      agent_phase="candidate", reason=None)
        return _guidance("closer", "Show the corners and their PA marks."), "candidate"
    elif phase == "candidate" and status == "assessed":
        update.update(candidate={"pa": response["pa"], "line_rank": response["line_rank"],
                                 "observation_id": observation_id}, agent_phase="verify", reason=None)
        return _guidance("show_full_pattern", "Show the same pattern from a different angle for an independent check."), "verify"
    elif phase == "verify" and status == "assessed":
        candidate = update.get("candidate") or {}
        prior_pa = candidate.get("pa")
        same_line = candidate.get("line_rank") == response["line_rank"]
        if (candidate.get("observation_id") != observation_id and same_line
                and isinstance(prior_pa, (int, float))
                and math.isclose(prior_pa, response["pa"], rel_tol=0, abs_tol=1e-8)):
            metadata = update.get("metadata") or {}
            if metadata.get("flow") is not None and metadata.get("acceleration") is not None:
                update.update(status="complete", reason=None, measurement={
                    "pa": response["pa"], "flow": metadata["flow"], "acceleration": metadata["acceleration"],
                    "status": "confirmed",
                })
                return _guidance("scan_next", "This pattern is complete. Find another."), "confirmed"
        update.update(agent_phase="candidate", candidate=None, last_response_id=None,
                      reason="line_identity_disagreed" if not same_line else "independent_view_disagreed")
        return _guidance("closer", "The line choice changed. Show the corners again."), "candidate"
    update["reason"] = response["reason"]
    return _guidance(response["next_view"], response["reason"]), phase


def analyze_observation(
    image_path: Path,
    observation_id: str,
    patterns: list[dict],
    work_dir: Path,
    provider: LiveProvider | RecordedProvider,
    progress_callback: Callable[[dict], None] | None = None,
) -> dict:
    """Inspect a still until another camera view is actually needed."""
    image_path = Path(image_path)
    events: list[dict[str, Any]] = [{"event": "observation_started", "observation_id": observation_id}]
    progress = None
    inspections = []

    def report(phase: str, activity: str = "analyzing", target: dict | None = None) -> None:
        nonlocal progress
        progress = {"phase": phase, "activity": activity, "target": target, "started_at": time.time()}
        if progress_callback:
            progress_callback({"progress": progress, "inspections": list(inspections)})

    report("locate")
    regions = vision.locate_regions(image_path)
    events.append({"event": "regions_detected", "observation_id": observation_id,
                   "count": len(regions), "boxes": [list(region["bbox"]) for region in regions]})
    if not regions:
        return {"patterns": patterns, "guidance": _guidance("show_full_pattern", "Show one complete PA pattern."),
                "events": events, "usage": {"calls": 0, "cost_usd": 0.0}, "progress": progress, "inspections": inspections}

    prior_calls = sum(int(pattern.get("model_calls", 0)) for pattern in patterns)
    prior_cost = sum(float(pattern.get("model_cost_usd", 0.0)) for pattern in patterns)
    call_count, cost_total = prior_calls, prior_cost
    updates = []
    next_guidance = _guidance("scan_next", "Find another PA pattern.")
    for index, region in enumerate(regions):
        matched, registrations = _region_match(image_path, region, patterns)
        events.append({"event": "region_registration", "observation_id": observation_id,
                       "region_index": index, "matches": registrations})
        if len(registrations) > 1:
            next_guidance = _guidance("show_full_pattern", "Show one complete pattern separately.")
            continue
        if matched and matched.get("status") in {"complete", "unsupported"}:
            continue
        pattern_id = matched["id"] if matched else uuid.uuid4().hex[:12]
        attempts = int(matched.get("attempts", 0)) + 1 if matched else 1
        update = dict(matched) if matched else {"id": pattern_id, "model_calls": 0, "model_cost_usd": 0.0}
        phase = update.get("agent_phase") if update.get("agent_phase") in PHASES else "identify"
        previous_response_id = update.get("last_response_id") if phase != "verify" else None
        update.update(id=pattern_id, agent_phase=phase, attempts=attempts, status="awaiting_detail",
                      last_observation_id=observation_id, last_image_path=str(image_path),
                      last_region=list(region["bbox"]), measurement=None)
        target = None
        crop = vision.crop_region(image_path, tuple(region["bbox"]), work_dir / "crops" / f"{index}.png")

        def over_budget() -> bool:
            return attempts > MAX_VIEWS_PER_PATTERN or call_count >= MAX_MODEL_CALLS or cost_total >= MAX_MODEL_COST_USD

        def request(continuation: dict | None = None) -> dict:
            nonlocal call_count, cost_total
            if over_budget():
                raise ValueError("inspection_limit_reached")
            call_count += 1
            update["model_calls"] += 1
            if continuation:
                envelope = provider.continue_inspection(crop["crop_path"], phase, **continuation)
            else:
                envelope = provider.request_agent(crop["crop_path"], phase, previous_response_id=previous_response_id)
            response_path = work_dir / "responses" / f"{index}-{phase}-{call_count}.json"
            response_path.parent.mkdir(parents=True, exist_ok=True)
            response_path.write_text(json.dumps(_logged_envelope(envelope), indent=2) + "\n")
            cost = envelope.get("cost_usd")
            if isinstance(cost, (int, float)) and not isinstance(cost, bool) and math.isfinite(cost) and cost >= 0:
                cost_total += cost
                update["model_cost_usd"] += cost
            else:
                cost = None
            events.append({"event": "model_response", "observation_id": observation_id, "pattern_id": pattern_id,
                           "phase": phase, "response_id": envelope.get("id"), "provider_status": envelope.get("status"),
                           "usage": envelope.get("usage"), "cost_usd": cost, "latency_ms": envelope.get("latency_ms"),
                           "response_path": str(response_path)})
            if envelope.get("status") != "completed" or cost is None:
                raise ValueError("incomplete_or_unaccounted_response")
            return envelope

        while True:
            report(phase, target=target)
            events.append({"event": "agent_step_started", "observation_id": observation_id, "pattern_id": pattern_id,
                           "phase": phase, "attempts": attempts, "crop_bbox": list(region["bbox"]),
                           "crop_path": crop["crop_path"], "previous_response_id": previous_response_id})
            validation_failure = False
            try:
                envelope = request()
                call = inspection_call(envelope)
                if call:
                    inspection_index = len(inspections)
                    marked_path, detail_path = render_inspection(crop["crop_path"], call, work_dir / "inspections", inspection_index)
                    target = {"observation_id": observation_id, "inspection_index": inspection_index,
                              "box": call["box"], "label": call["label"]}
                    inspections.append(target)
                    report(phase, "inspecting", target)
                    events.append({"event": "region_inspected", "phase": phase, "target": target})
                    envelope = request({"previous_response_id": envelope["id"], "call_id": call["call_id"],
                                        "marked_path": marked_path, "detail_path": detail_path})
                    if inspection_call(envelope):
                        raise ValueError("inspection tool limit exceeded")
                response = json.loads(envelope["output_text"])
                errors = validate_agent_response(response, phase)
                if errors:
                    validation_failure = True
                    raise ValueError("; ".join(errors))
            except (ProviderError, OSError, ValueError, TypeError, KeyError) as error:
                limited = str(error) == "inspection_limit_reached"
                update.update(status="inconclusive" if limited else "model_error",
                              reason="inspection_limit_reached" if limited else "validation_failure" if validation_failure else "model_failure")
                next_guidance = _guidance("scan_next" if limited else "hold_still",
                                         "Inspection limit reached. Find another pattern." if limited else
                                         "Analysis failed. Try another view.", phase, target)
                events.append({"event": "inspection_limit_reached" if limited else "validation_failure" if validation_failure else "model_error", "phase": phase,
                               "error_type": type(error).__name__, "errors": [str(error)],
                               "http_status": getattr(error, "status_code", None)})
                break

            prior_candidate = update.get("candidate") if phase == "verify" else None
            update.update(last_response=response, last_response_id=envelope.get("id"), validation_errors=[])
            next_guidance, next_phase = _advance(update, response, observation_id)
            next_guidance.update(phase=update["agent_phase"], target=target)
            events.append({"event": "agent_step_completed", "observation_id": observation_id, "pattern_id": pattern_id,
                           "phase": phase, "step_status": response["status"], "next_phase": next_phase,
                           "next_view": next_guidance["action"], "reason": update.get("reason"),
                           "candidate_pa": (prior_candidate or update.get("candidate") or {}).get("pa"),
                           "candidate_line_rank": (prior_candidate or update.get("candidate") or {}).get("line_rank"),
                           "verified_pa": response.get("pa") if phase == "verify" else None,
                           "verified_line_rank": response.get("line_rank") if phase == "verify" else None,
                           "response_id": envelope.get("id")})
            if update["status"] == "complete":
                events.append({"event": "measurement_confirmed", "observation_id": observation_id,
                               "pattern_id": pattern_id, "measurement": update["measurement"], "response_id": envelope.get("id")})
            if phase in {"identify", "metadata"} and response["status"] in {"supported", "read"}:
                phase = update["agent_phase"]
                target = None
                previous_response_id = envelope.get("id")
                continue
            if update["status"] == "awaiting_detail" and attempts >= MAX_VIEWS_PER_PATTERN:
                update.update(status="inconclusive", reason="inspection_limit_reached")
                next_guidance = _guidance("scan_next", "Inspection limit reached. Find another pattern.", phase, target)
            break
        updates.append(update)
    merged = {pattern["id"]: pattern for pattern in patterns}
    merged.update({pattern["id"]: pattern for pattern in updates})
    return {"patterns": list(merged.values()), "guidance": next_guidance, "events": events,
            "usage": {"calls": call_count - prior_calls, "cost_usd": cost_total - prior_cost},
            "progress": progress, "inspections": inspections}
