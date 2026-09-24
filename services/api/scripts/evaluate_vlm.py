#!/usr/bin/env python3
"""Evaluate one physical PA pattern at a time from frozen still observations."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
from pathlib import Path
from typing import Any

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))

from pa_eval import vision  # noqa: E402
from pa_eval.protocol import ENDPOINT, MODEL, PROMPT_SHA256, PROTOCOL_VERSION, SCHEMA_SHA256, validate_response  # noqa: E402
from pa_eval.provider import LiveProvider, ProviderError, RecordedProvider, cost_usd_from_usage  # noqa: E402
from pa_eval.review import write_review_page  # noqa: E402


def read_manifest(path: Path) -> dict:
    manifest = json.loads(path.read_text())
    if manifest.get("version") != 1:
        raise ValueError("unsupported manifest version")
    for observation_id, observation in manifest["observations"].items():
        image = Path(observation["path"])
        if not image.is_absolute():
            image = (path.parent / image).resolve()
        if hashlib.sha256(image.read_bytes()).hexdigest() != observation["sha256"]:
            raise ValueError(f"observation {observation_id} hash mismatch")
        observation["resolved_path"] = str(image)
    for bundle in manifest["bundles"]:
        if bundle["pattern_id"] not in manifest["patterns"] or any(o not in manifest["observations"] for o in bundle["observation_ids"]):
            raise ValueError("bundle references an unknown pattern or observation")
    return manifest


def is_overview(observation: dict) -> bool:
    return observation["role"] in {"overview", "plate_overview"}


def covered_fraction(box: tuple[int, int, int, int], target: list[int]) -> float:
    intersection = max(0, min(box[2], target[2]) - max(box[0], target[0])) * max(0, min(box[3], target[3]) - max(box[1], target[1]))
    return intersection / ((target[2] - target[0]) * (target[3] - target[1]))


def select_pair(pattern_id: str, detail_id: str, manifest: dict, detections: dict) -> dict:
    observations = manifest["observations"]
    overview_id = next((o for o in manifest["patterns"][pattern_id]["observation_ids"] if is_overview(observations[o])), None)
    if overview_id is None:
        return {"status": "missing_view", "reason": "no overview"}
    if not detections[overview_id] or not detections[detail_id]:
        return {"status": "localization_failure", "reason": "no complete pattern region", "requested_view": "show the full pattern"}
    matches = []
    for overview in detections[overview_id]:
        for detail in detections[detail_id]:
            result = vision.match_regions(observations[overview_id]["resolved_path"], overview["bbox"], observations[detail_id]["resolved_path"], detail["bbox"])
            if result["status"] == "matched":
                matches.append((overview, detail, result))
    if len(matches) != 1:
        return {"status": "matching_uncertain", "reason": f"{len(matches)} unique matches", "requested_view": "show the full pattern with readable metadata"}
    overview, detail, registration = matches[0]
    return {"status": "matched", "overview_id": overview_id, "detail_id": detail_id, "overview": overview, "detail": detail, "registration": registration}


def check_reference(pattern_id: str, pair: dict, reference: dict | None, manifest: dict) -> str | None:
    if reference is None:
        return None
    pattern = reference["patterns"].get(pattern_id)
    if pattern is None:
        return "unresolved_reference"
    box = pair["overview"]["bbox"]
    if covered_fraction(box, pattern["overview_region_xyxy"]) < 0.6:
        return "wrong_match"
    if manifest["patterns"][pattern_id]["split"] == "development":
        for other_id, other in reference["patterns"].items():
            if other_id != pattern_id and manifest["patterns"][other_id]["split"] == "held_out" and covered_fraction(box, other["overview_region_xyxy"]) > 0.01:
                return "held_out_leakage"
    return None


def score(response: dict, reference_pattern: dict | None, observations: dict) -> dict | None:
    if reference_pattern is None:
        return None
    metadata = response["metadata"]
    assessment = response["assessment"]
    selected_pa = assessment["selected_pa"]
    preferred = reference_pattern["preferred_pa"]
    line_anchor = reference_pattern["preferred_line"].get("pixel_anchor")
    physical_correct = None
    label_correct = None
    if line_anchor is not None and assessment["selected_line_id"] is not None:
        selected_line = next((line for line in response["candidate_lines"] if line["line_id"] == assessment["selected_line_id"]), None)
        apex = selected_line.get("apex") if selected_line else None
        if apex is not None:
            source = observations[apex["observation_id"]]
            width, height = source["oriented_size"]
            physical_correct = apex["observation_id"] == line_anchor["observation_id"] and math.dist((apex["x"] * width, apex["y"] * height), line_anchor["xy"]) <= line_anchor["tolerance_px"]
        else:
            physical_correct = False
        if selected_line and reference_pattern["preferred_line"]["mapping"] == "numbered_anchor":
            label_correct = physical_correct and selected_line["mapping_basis"] == "visible_label" and any(label["line_id"] == selected_line["line_id"] and math.isclose(label["pa"], preferred, abs_tol=1e-8) for label in response["labels"])
    return {
        "supported_pattern": response["supported_pattern"],
        "flow_exact": metadata["flow"]["value"] == reference_pattern["printed_flow"],
        "acceleration_exact": metadata["acceleration"]["value"] == reference_pattern["printed_acceleration"],
        "preferred_pa_exact": selected_pa is not None and math.isclose(selected_pa, preferred, abs_tol=1e-8),
        "preferred_pa_within_one_line": selected_pa is not None and abs(selected_pa - preferred) <= 0.00500001,
        "physical_line_correct": physical_correct,
        "label_line_correct": label_correct,
    }


def aggregate(trials: list[dict], split: str, ratings: list[dict]) -> dict:
    counts = {"confirmed": 0, "localization_failure": 0}
    final = {}
    attempted = set()
    latest_score = {}
    for trial in trials:
        counts[trial["status"]] = counts.get(trial["status"], 0) + 1
        final[trial["pattern_id"]] = trial
        if trial.get("call_attempted"):
            attempted.add(trial["pattern_id"])
        if trial.get("score") is not None:
            latest_score[trial["pattern_id"]] = trial["score"]
    metrics = {}
    for key in ("supported_pattern", "flow_exact", "acceleration_exact", "preferred_pa_exact", "preferred_pa_within_one_line", "physical_line_correct", "label_line_correct"):
        values = []
        for pattern_id in attempted:
            trial = final[pattern_id]
            if not trial.get("has_reference"):
                continue
            if key == "physical_line_correct" and not trial.get("physical_line_scorable"):
                continue
            if key == "label_line_correct" and not trial.get("label_line_scorable"):
                continue
            values.append((latest_score.get(pattern_id) or {}).get(key) is True)
        metrics[key] = {"correct": sum(value is True for value in values), "denominator": len(values)}
    usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "cost_complete": True, "latency_ms": 0.0}
    for trial in trials:
        if trial.get("call_attempted"):
            usage["calls"] += 1
        if trial.get("unaccounted_cost"):
            usage["cost_complete"] = False
        provider = trial.get("provider_record")
        if provider is None:
            continue
        tokens = provider.get("usage") or {}
        usage["input_tokens"] += tokens.get("input_tokens", 0)
        usage["output_tokens"] += tokens.get("output_tokens", 0)
        usage["latency_ms"] += provider.get("latency_ms") or 0.0
        cost = cost_usd_from_usage(tokens)
        if cost is None:
            cost = provider.get("cost_usd")
        if cost is None:
            usage["cost_complete"] = False
        else:
            usage["cost_usd"] += cost
    rating_counts = {label: sum(item["rating"] == label for item in ratings) for label in ("useful", "unhelpful", "uncertain", "unrated")}
    held_out_targets = [item for item in ratings if item["pattern_id"] in final and final[item["pattern_id"]]["split"] == "held_out" and item["step"] == "overview"]
    useful_held_out = sum(item["rating"] == "useful" and not item.get("repeated", False) for item in held_out_targets)
    held_out = [trial for trial in final.values() if trial["split"] == "held_out"]
    pilot_pass = None
    if split in {"all", "held_out"} and len(held_out) == 3:
        pilot_pass = all(trial["status"] == "confirmed" and all(trial.get("score", {}).get(key) is True for key in ("flow_exact", "acceleration_exact", "preferred_pa_exact", "physical_line_correct")) for trial in held_out) and len(held_out_targets) == 3 and useful_held_out >= 2
    return {
        "protocol": {"version": PROTOCOL_VERSION, "model": MODEL, "endpoint": ENDPOINT, "prompt_sha256": PROMPT_SHA256, "schema_sha256": SCHEMA_SHA256},
        "split": split, "trial_count": len(trials), "pattern_count": len(final), "counts": counts, "metrics": metrics,
        "usage": usage, "target_ratings": rating_counts, "held_out_incomplete_targets": {"useful": useful_held_out, "denominator": len(held_out_targets)}, "within_job_pilot_pass": pilot_pass,
        "untested": ["acceptable PA range accuracy", "unsupported-pattern specificity", "live camera guidance", "cross-job performance"],
    }


def verified_ratings(targets: list[dict], submitted: list[dict]) -> list[dict]:
    submitted_by_id = {(item["target_id"], item["observation_id"]): item["rating"] for item in submitted}
    if len(submitted_by_id) != len(submitted) or set(submitted_by_id) != {(item["target_id"], item["observation_id"]) for item in targets} or any(value not in {"useful", "unhelpful", "uncertain", "unrated"} for value in submitted_by_id.values()):
        raise ValueError("ratings do not match valid target and observation IDs")
    return [{**target, "rating": submitted_by_id[(target["target_id"], target["observation_id"])]} for target in targets]


def saved_protocol(output_dir: Path, original: dict) -> dict:
    versions = []
    for response_file in sorted((output_dir / "responses").glob("*.json")):
        request = json.loads(response_file.read_text())["request"]
        match = None
        for version in ("v1", "v2"):
            prompt = API_DIR.parents[1] / "fixtures/protocol" / f"prompt-{version}.txt"
            schema = API_DIR.parents[1] / "fixtures/protocol" / f"schema-{version}.json"
            if prompt.exists() and schema.exists() and request["instructions"] == prompt.read_text() and request["text"]["format"]["schema"] == json.loads(schema.read_text()):
                match = {"version": version, "model": request["model"], "endpoint": ENDPOINT, "prompt_sha256": hashlib.sha256(prompt.read_bytes()).hexdigest(), "schema_sha256": hashlib.sha256(schema.read_bytes()).hexdigest()}
                break
        if match is None:
            raise ValueError(f"saved response {response_file.name} has an unknown protocol")
        versions.append(match)
    if versions and any(item != versions[0] for item in versions):
        raise ValueError("saved run mixes protocol versions")
    return versions[0] if versions else original


def rate_existing(output_dir: Path, rating_path: Path, reference_path: Path | None) -> int:
    trials = json.loads((output_dir / "trials.json").read_text())
    if reference_path:
        reference = json.loads(reference_path.read_text())
        for trial in trials:
            pattern = reference["patterns"].get(trial["pattern_id"])
            anchor = pattern["preferred_line"].get("pixel_anchor") if pattern else None
            trial["has_reference"] = pattern is not None
            trial["physical_line_scorable"] = anchor is not None
            trial["label_line_scorable"] = anchor is not None and pattern["preferred_line"]["mapping"] == "numbered_anchor"
    report_path = output_dir / "report.json"
    original = json.loads(report_path.read_text())
    targets = json.loads((output_dir / "target_ratings.json").read_text())
    ratings = verified_ratings(targets, json.loads(rating_path.read_text()))
    updated = {**original, **aggregate(trials, original["split"], ratings)}
    updated["protocol"] = saved_protocol(output_dir, original["protocol"])
    (output_dir / "ratings.json").write_text(json.dumps(ratings, indent=2) + "\n")
    (output_dir / "trials.json").write_text(json.dumps(trials, indent=2) + "\n")
    report_path.write_text(json.dumps(updated, indent=2) + "\n")
    return 0 if updated["within_job_pilot_pass"] is True else 2


def run(args: argparse.Namespace) -> int:
    manifest = read_manifest(args.manifest)
    reference = json.loads(args.reference.read_text()) if args.reference else None
    if reference is None and any(pattern["split"] == "held_out" for pattern in manifest["patterns"].values()):
        raise ValueError("reference is required to guard held-out regions")
    bundles = [bundle for bundle in manifest["bundles"] if args.split == "all" or manifest["patterns"][bundle["pattern_id"]]["split"] == args.split]
    needed = {item for bundle in bundles for item in manifest["patterns"][bundle["pattern_id"]]["observation_ids"]}
    detections = {item: vision.locate_regions(manifest["observations"][item]["resolved_path"]) for item in needed}
    provider: LiveProvider | RecordedProvider | None = None
    prior: dict[str, dict[str, Any]] = {}
    trials: list[dict[str, Any]] = []
    spent = 0.0
    calls = 0
    for bundle in bundles:
        pattern_id = bundle["pattern_id"]
        pattern = manifest["patterns"][pattern_id]
        reference_pattern = reference["patterns"].get(pattern_id) if reference else None
        anchor = reference_pattern["preferred_line"].get("pixel_anchor") if reference_pattern else None
        record: dict[str, Any] = {"pattern_id": pattern_id, "split": pattern["split"], "step": bundle["step"], "observation_ids": bundle["observation_ids"], "source_hashes": {o: manifest["observations"][o]["sha256"] for o in bundle["observation_ids"]}, "status": "unresolved", "response_id": None, "has_reference": reference_pattern is not None, "physical_line_scorable": anchor is not None, "label_line_scorable": anchor is not None and reference_pattern is not None and reference_pattern["preferred_line"]["mapping"] == "numbered_anchor"}
        trials.append(record)
        details = [o for o in bundle["observation_ids"] if not is_overview(manifest["observations"][o])]
        if not details:
            details = [o for o in pattern["observation_ids"] if not is_overview(manifest["observations"][o])]
        if not details:
            record.update(status="missing_view", reason="no dedicated detail to establish overview identity")
            continue
        detail_id = details[0]
        pair = select_pair(pattern_id, detail_id, manifest, detections)
        if pair["status"] != "matched":
            record.update(pair)
            continue
        record["registration"] = pair["registration"]
        record["regions"] = {pair["overview_id"]: pair["overview"]["bbox"], detail_id: pair["detail"]["bbox"]}
        problem = check_reference(pattern_id, pair, reference, manifest)
        if problem:
            record.update(status=problem, reason="automatic match failed independent scoring or split guard")
            continue
        if bundle["step"] != "overview" and pattern_id not in prior:
            record.update(status="prerequisite_failure", reason="no validated overview response")
            continue
        if calls >= 30 or spent >= 5.0:
            record.update(status="budget_exhausted", reason="30-call or US$5 cap reached")
            continue
        selected_ids = [pair["overview_id"]] if bundle["step"] == "overview" else [detail_id]
        inputs = []
        for observation_id in selected_ids:
            region = pair["overview"] if observation_id == pair["overview_id"] else pair["detail"]
            crop = vision.crop_region(manifest["observations"][observation_id]["resolved_path"], region["bbox"], args.output_dir / "crops" / f"{pattern_id}-{observation_id}.png")
            record.setdefault("crops", {})[observation_id] = crop
            inputs.append({"observation_id": observation_id, "image_path": crop["crop_path"], "sha256": crop["crop_sha256"], "source_bbox": list(region["bbox"]), "source_size": manifest["observations"][observation_id]["oriented_size"]})
        if provider is None:
            try:
                provider = LiveProvider() if args.provider == "live" else RecordedProvider(args.responses) if args.responses else None
                if provider is None:
                    raise ProviderError("--responses is required for recorded trials that reach the model")
            except (ProviderError, ValueError, OSError) as error:
                record.update(status="provider_error", error=str(error))
                continue
        previous = prior.get(pattern_id)
        record["call_attempted"] = True
        calls += 1
        if provider is None:
            raise ValueError("provider initialization did not complete")
        try:
            envelope = provider.request(inputs, previous_response_id=previous["id"] if previous else None)
        except (ProviderError, ValueError, OSError) as error:
            record.update(status="provider_error", error=str(error), unaccounted_cost=args.provider == "live")
            continue
        record["response_id"] = envelope["id"]
        record["provider_record"] = {key: envelope.get(key) for key in ("usage", "cost_usd", "latency_ms", "status")}
        raw_path = args.output_dir / "responses" / f"{len(trials):02d}-{pattern_id}-{bundle['step']}.json"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(json.dumps(envelope, indent=2) + "\n")
        record["response_path"] = str(raw_path)
        if envelope.get("cost_usd") is None and args.provider == "live":
            record.update(status="budget_exhausted", reason="cost could not be accounted from provider usage")
            continue
        spent += envelope.get("cost_usd") or 0.0
        if envelope["status"] != "completed":
            record.update(status="provider_error", error=f"provider status {envelope['status']}")
            continue
        try:
            response = json.loads(envelope["output_text"])
        except (TypeError, ValueError) as error:
            record.update(status="validation_failure", validation_errors=[f"malformed JSON: {error}"])
            continue
        crop_bounds = dict(previous["crop_bounds"]) if previous else {}
        for item in inputs:
            left, top, right, bottom = item["source_bbox"]
            width, height = item["source_size"]
            crop_bounds[item["observation_id"]] = [left / width, top / height, right / width, bottom / height]
        context = {"allowed_observation_ids": bundle["observation_ids"], "new_observation_ids": selected_ids, "previous_response": previous["response"] if previous else None, "verified_identity": previous["response"]["pattern_identity"]["pattern_id"] if previous else None, "candidate_values": [round(0.03 + i * 0.005, 3) for i in range(13)], "allowed_label_values": [round(0.03 + i * 0.01, 2) for i in range(7)], "known_labels": {}, "crop_bounds": crop_bounds}
        if reference_pattern:
            context["verified_metadata"] = {"flow": reference_pattern["printed_flow"], "acceleration": reference_pattern["printed_acceleration"]}
        errors = validate_response(response, context)
        record.update(response=response, validation_errors=errors)
        if errors:
            record["status"] = "validation_failure"
            continue
        record["score"] = score(response, reference_pattern, manifest["observations"])
        assessment = response["assessment"]
        if assessment["contradiction"]:
            record["status"] = "contradiction"
        elif assessment["status"] == "inconclusive":
            record["status"] = "inconclusive"
        elif assessment["status"] == "unsupported":
            record["status"] = "unsupported"
        elif record["score"] is None:
            record["status"] = "unresolved_reference"
        elif bundle["step"] == "overview":
            record["status"] = "provisional"
        elif record["score"]["physical_line_correct"] is None:
            record["status"] = "unresolved_reference"
        else:
            record["status"] = "confirmed" if all(record["score"][key] is True for key in ("supported_pattern", "flow_exact", "acceleration_exact", "preferred_pa_exact", "physical_line_correct")) else "incorrect"
        prior[pattern_id] = {"id": envelope["id"], "response": response, "crop_bounds": crop_bounds}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    targets = write_review_page(trials, manifest["observations"], args.output_dir)
    ratings = verified_ratings(targets, json.loads(args.ratings.read_text()) if args.ratings else targets)
    report = aggregate(trials, args.split, ratings)
    report["input_provenance"] = {
        "manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        "reference_sha256": hashlib.sha256(args.reference.read_bytes()).hexdigest() if args.reference else None,
        "detector_sha256": hashlib.sha256(Path(vision.__file__).read_bytes()).hexdigest(),
    }
    if reference:
        localization = {}
        for pattern_id, pattern in manifest["patterns"].items():
            if args.split != "all" and pattern["split"] != args.split:
                continue
            overview_id = next((item for item in pattern["observation_ids"] if is_overview(manifest["observations"][item])), None)
            boxes = detections.get(overview_id, [])
            expected = reference["patterns"][pattern_id]["overview_region_xyxy"]
            hits = [item for item in boxes if covered_fraction(item["bbox"], expected) >= 0.6]
            localization[pattern_id] = {"observation_id": overview_id, "detected": len(hits) == 1, "matching_region_count": len(hits)}
        report["overview_localization"] = {"correct": sum(1 for item in localization.values() if item["detected"] is True), "denominator": len(localization), "patterns": localization}
    (args.output_dir / "trials.json").write_text(json.dumps(trials, indent=2) + "\n")
    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    if args.delete_crops:
        shutil.rmtree(args.output_dir / "crops", ignore_errors=True)
    return 0 if report["within_job_pilot_pass"] is True else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--provider", choices=("recorded", "live"), default="recorded")
    parser.add_argument("--responses", type=Path)
    parser.add_argument("--ratings", type=Path)
    parser.add_argument("--ratings-only", action="store_true", help="score downloaded ratings against an existing run without new model calls")
    parser.add_argument("--split", choices=("development", "held_out", "all"), default="all")
    parser.add_argument("--delete-crops", action="store_true")
    args = parser.parse_args()
    try:
        if args.ratings_only:
            if args.ratings is None:
                raise ValueError("--ratings-only requires --ratings")
            return rate_existing(args.output_dir, args.ratings, args.reference)
        if args.manifest is None:
            raise ValueError("--manifest is required for an experiment run")
        return run(args)
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"Evaluator error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
