import hashlib
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image


COMMAND = Path(__file__).resolve().parents[1] / "services/api/scripts/evaluate_vlm.py"


def test_unlocatable_pattern_is_reported_without_model_assessment(tmp_path):
    image_path = tmp_path / "blank.jpg"
    Image.new("RGB", (640, 480), "white").save(image_path)
    image_hash = hashlib.sha256(image_path.read_bytes()).hexdigest()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "version": 1,
                "observations": {
                    "overview": {
                        "path": str(image_path),
                        "sha256": image_hash,
                        "role": "overview",
                    },
                    "detail": {
                        "path": str(image_path),
                        "sha256": image_hash,
                        "role": "detail",
                    },
                },
                "patterns": {"pattern-a": {"split": "development", "observation_ids": ["overview", "detail"]}},
                "bundles": [{"pattern_id": "pattern-a", "step": "overview", "observation_ids": ["overview"]}],
            }
        )
    )
    output_dir = tmp_path / "output"

    process = subprocess.run(
        [sys.executable, str(COMMAND), "--manifest", str(manifest_path), "--output-dir", str(output_dir), "--provider", "recorded"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert process.returncode == 2, process.stderr
    trials = json.loads((output_dir / "trials.json").read_text())
    assert trials[0]["status"] == "localization_failure"
    assert trials[0]["response_id"] is None
    report = json.loads((output_dir / "report.json").read_text())
    assert report["counts"]["localization_failure"] == 1
    assert report["counts"]["confirmed"] == 0


def test_recorded_inconclusive_target_is_traced_to_oriented_source(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    source = repo / "fixtures/images/20260924_191535.jpg"
    detail = repo / "fixtures/images/20260924_191604.jpg"
    manifest = {
        "version": 1,
        "observations": {
            "overview": {"path": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "role": "overview", "oriented_size": [4000, 3000]},
            "detail": {"path": str(detail), "sha256": hashlib.sha256(detail.read_bytes()).hexdigest(), "role": "detail", "oriented_size": [3000, 4000]},
        },
        "patterns": {"p07": {"split": "development", "observation_ids": ["overview", "detail"]}},
        "bundles": [{"pattern_id": "p07", "step": "overview", "observation_ids": ["overview"]}],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    response = {
        "supported_pattern": True,
        "pattern_identity": {"pattern_id": None, "evidence_ids": []},
        "metadata": {
            "flow": {"value": None, "source": "unknown", "evidence_ids": []},
            "acceleration": {"value": None, "source": "unknown", "evidence_ids": []},
        },
        "labels": [],
        "candidate_lines": [],
        "assessment": {"status": "inconclusive", "selected_line_id": None, "selected_pa": None, "plausible_line_ids": [], "uncertainty": "Need a clearer view of two adjacent corners", "evidence_ids": ["overview"], "contradiction": False, "contradiction_reason": None},
        "inspection_target": {"observation_id": "overview", "box": [0.15, 0.65, 0.25, 0.75], "reason": "Separate adjacent corners"},
    }
    responses_path = tmp_path / "responses.json"
    responses_path.write_text(json.dumps([{"id": "recorded-1", "status": "completed", "output_text": json.dumps(response), "usage": {"input_tokens": 100, "output_tokens": 30}}]))
    output_dir = tmp_path / "output"

    process = subprocess.run(
        [sys.executable, str(COMMAND), "--manifest", str(manifest_path), "--output-dir", str(output_dir), "--provider", "recorded", "--responses", str(responses_path)],
        text=True, capture_output=True, check=False,
    )

    assert process.returncode == 2, process.stderr
    trials = json.loads((output_dir / "trials.json").read_text())
    assert trials[0]["status"] == "inconclusive"
    assert trials[0]["response_id"] == "recorded-1"
    assert trials[0]["crops"]["overview"]["source_sha256"] == manifest["observations"]["overview"]["sha256"]
    targets = json.loads((output_dir / "target_ratings.json").read_text())
    assert targets[0]["observation_id"] == "overview"
    assert targets[0]["box"] == [0.15, 0.65, 0.25, 0.75]
    assert Image.open(output_dir / "review_images/overview.jpg").size == (4000, 3000)
    assert "left:15.0000%;top:65.0000%" in (output_dir / "review.html").read_text()

    rating_path = tmp_path / "ratings.json"
    rating_path.write_text(json.dumps([{**targets[0], "rating": "useful"}]))
    response_path = output_dir / "responses/01-p07-overview.json"
    response_hash = hashlib.sha256(response_path.read_bytes()).hexdigest()
    rerating = subprocess.run(
        [sys.executable, str(COMMAND), "--output-dir", str(output_dir), "--ratings-only", "--ratings", str(rating_path)],
        text=True, capture_output=True, check=False,
    )
    assert rerating.returncode == 2, rerating.stderr
    assert json.loads((output_dir / "report.json").read_text())["target_ratings"]["useful"] == 1
    assert hashlib.sha256(response_path.read_bytes()).hexdigest() == response_hash

    invalid = json.loads(json.dumps(response))
    invalid["labels"] = [{"line_id": "l0", "pa": 0.12, "evidence_ids": ["overview"]}]
    invalid["candidate_lines"] = [{"line_id": "l0", "pa": 0.12, "mapping_basis": "visible_label", "anchor_line_ids": [], "evidence_ids": ["overview"], "features": [], "apex": {"observation_id": "overview", "x": 0.2, "y": 0.7}}]
    invalid["inspection_target"]["box"] = [1.1, 0.65, 1.2, 0.75]
    invalid_responses = tmp_path / "invalid-responses.json"
    invalid_responses.write_text(json.dumps([{"id": "invalid-1", "status": "completed", "output_text": json.dumps(invalid)}]))
    invalid_output = tmp_path / "invalid-output"
    invalid_run = subprocess.run(
        [sys.executable, str(COMMAND), "--manifest", str(manifest_path), "--output-dir", str(invalid_output), "--provider", "recorded", "--responses", str(invalid_responses)],
        text=True, capture_output=True, check=False,
    )
    assert invalid_run.returncode == 2, invalid_run.stderr
    rejected = json.loads((invalid_output / "trials.json").read_text())[0]
    assert rejected["status"] == "validation_failure"
    assert any("printed" in error or "candidate" in error for error in rejected["validation_errors"])
    assert any("inspection_target" in error for error in rejected["validation_errors"])
    assert json.loads((invalid_output / "target_ratings.json").read_text()) == []


def test_development_detector_isolates_patterns_without_held_out_exposure(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    responses = tmp_path / "responses.json"
    responses.write_text("[]")
    output_dir = tmp_path / "output"

    process = subprocess.run(
        [
            sys.executable, str(COMMAND),
            "--manifest", str(repo / "fixtures/manifest.json"),
            "--reference", str(repo / "fixtures/reference.json"),
            "--split", "development",
            "--provider", "recorded", "--responses", str(responses),
            "--output-dir", str(output_dir),
        ],
        text=True, capture_output=True, check=False,
    )

    assert process.returncode == 2, process.stderr
    report = json.loads((output_dir / "report.json").read_text())
    assert report["overview_localization"]["correct"] == 6
    assert report["overview_localization"]["denominator"] == 6
    assert report["counts"].get("held_out_leakage", 0) == 0
    assert report["counts"].get("wrong_match", 0) == 0
    assert report["counts"].get("matching_uncertain", 0) == 0
    trials = json.loads((output_dir / "trials.json").read_text())
    overview_only = next(trial for trial in trials if trial["pattern_id"] == "p09")
    assert overview_only["status"] == "provider_error"
    assert overview_only["call_attempted"] is True
    assert set(overview_only["crops"]) == {"20260924_191535"}
    assert report["counts"].get("missing_view", 0) == 0


def test_ratings_only_excludes_repeated_and_conclusive_targets_and_stale_scores(tmp_path):
    output_dir = tmp_path / "saved-run"
    output_dir.mkdir()
    score = {key: True for key in ("supported_pattern", "flow_exact", "acceleration_exact", "preferred_pa_exact", "preferred_pa_within_one_line", "physical_line_correct", "label_line_correct")}
    trials = []
    targets = []
    for index in range(3):
        pattern_id = f"p{index + 1:02d}"
        response_id = f"overview-{index}"
        trials.append({"pattern_id": pattern_id, "split": "held_out", "step": "overview", "status": "confirmed" if index == 2 else "inconclusive", "response_id": response_id, "score": score, "has_reference": True, "physical_line_scorable": True, "label_line_scorable": True, "call_attempted": True})
        trials.append({"pattern_id": pattern_id, "split": "held_out", "step": "overview_plus_detail", "status": "provider_error" if index == 0 else "confirmed", "response_id": f"detail-{index}", "score": None if index == 0 else score, "has_reference": True, "physical_line_scorable": True, "label_line_scorable": True, "call_attempted": True})
        targets.append({"target_id": f"target-{index}", "pattern_id": pattern_id, "step": "overview", "observation_id": "plate", "source_sha256": "same-image", "response_id": response_id, "box": [0.1, 0.1, 0.2, 0.2], "reason": "clarify corners", "rating": "unrated"})
    (output_dir / "trials.json").write_text(json.dumps(trials))
    (output_dir / "target_ratings.json").write_text(json.dumps(targets))
    (output_dir / "report.json").write_text(json.dumps({"split": "held_out", "protocol": {"version": "v2"}, "input_provenance": {"reference_sha256": "original"}}))
    rating_path = tmp_path / "ratings.json"
    rating_path.write_text(json.dumps([{**target, "rating": "useful"} for target in targets]))

    process = subprocess.run([sys.executable, str(COMMAND), "--output-dir", str(output_dir), "--ratings-only", "--ratings", str(rating_path)], text=True, capture_output=True, check=False)
    assert process.returncode == 2, process.stderr
    report = json.loads((output_dir / "report.json").read_text())
    assert report["held_out_incomplete_targets"] == {"useful": 1, "denominator": 1}
    assert report["metrics"]["preferred_pa_exact"] == {"correct": 2, "denominator": 3}
    assert report["within_job_pilot_pass"] is False

    changed_reference = tmp_path / "changed-reference.json"
    changed_reference.write_text("{}")
    rejected = subprocess.run([sys.executable, str(COMMAND), "--output-dir", str(output_dir), "--ratings-only", "--ratings", str(rating_path), "--reference", str(changed_reference)], text=True, capture_output=True, check=False)
    assert rejected.returncode == 1
    assert "saved reference hash" in rejected.stderr


def test_identical_source_images_do_not_establish_cross_view_identity(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    source = repo / "fixtures/images/20260924_191535.jpg"
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = {
        "version": 1,
        "observations": {
            "overview": {"path": str(source), "sha256": digest, "role": "overview", "oriented_size": [4000, 3000]},
            "detail": {"path": str(source), "sha256": digest, "role": "detail", "oriented_size": [4000, 3000]},
        },
        "patterns": {"p07": {"split": "development", "observation_ids": ["overview", "detail"]}},
        "bundles": [{"pattern_id": "p07", "step": "overview", "observation_ids": ["overview"]}],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    output_dir = tmp_path / "output"
    process = subprocess.run([sys.executable, str(COMMAND), "--manifest", str(manifest_path), "--output-dir", str(output_dir), "--provider", "recorded"], text=True, capture_output=True, check=False)
    assert process.returncode == 2, process.stderr
    trial = json.loads((output_dir / "trials.json").read_text())[0]
    assert trial["status"] == "matching_uncertain"
    assert trial["response_id"] is None
    assert trial.get("call_attempted") is None


def test_detail_inherits_verified_overview_metadata_with_provenance(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    source = repo / "fixtures/images/20260924_191535.jpg"
    detail = repo / "fixtures/images/20260924_191604.jpg"
    manifest = {
        "version": 1,
        "observations": {
            "overview": {"path": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "role": "overview", "oriented_size": [4000, 3000]},
            "detail": {"path": str(detail), "sha256": hashlib.sha256(detail.read_bytes()).hexdigest(), "role": "detail", "oriented_size": [3000, 4000]},
        },
        "patterns": {"p07": {"split": "development", "observation_ids": ["overview", "detail"]}},
        "bundles": [
            {"pattern_id": "p07", "step": "overview", "observation_ids": ["overview"]},
            {"pattern_id": "p07", "step": "overview_plus_detail", "observation_ids": ["overview", "detail"]},
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    overview_response = {
        "supported_pattern": True,
        "pattern_identity": {"pattern_id": "p07", "evidence_ids": ["overview"]},
        "metadata": {
            "flow": {"value": 15.1, "source": "visible", "evidence_ids": ["overview"]},
            "acceleration": {"value": 4000, "source": "visible", "evidence_ids": ["overview"]},
        },
        "labels": [], "candidate_lines": [],
        "assessment": {"status": "inconclusive", "selected_line_id": None, "selected_pa": None, "plausible_line_ids": [], "uncertainty": "Corners are unclear", "evidence_ids": ["overview"], "contradiction": False, "contradiction_reason": None},
        "inspection_target": None,
    }
    detail_response = json.loads(json.dumps(overview_response))
    detail_response["metadata"] = {
        "flow": {"value": 15.1, "source": "inherited", "evidence_ids": ["overview"]},
        "acceleration": {"value": 4000, "source": "inherited", "evidence_ids": ["overview"]},
    }
    detail_response["assessment"]["evidence_ids"] = ["detail"]
    responses_path = tmp_path / "responses.json"
    responses_path.write_text(json.dumps([
        {"id": "first", "status": "completed", "output_text": json.dumps(overview_response), "usage": {"input_tokens": 100, "output_tokens": 30}},
        {"id": "second", "status": "completed", "output_text": json.dumps(detail_response), "usage": {"input_tokens": 100, "output_tokens": 30}},
    ]))
    output_dir = tmp_path / "output"
    process = subprocess.run([sys.executable, str(COMMAND), "--manifest", str(manifest_path), "--output-dir", str(output_dir), "--provider", "recorded", "--responses", str(responses_path)], text=True, capture_output=True, check=False)
    assert process.returncode == 2, process.stderr
    trials = json.loads((output_dir / "trials.json").read_text())
    assert [trial["status"] for trial in trials] == ["inconclusive", "inconclusive"]
    assert trials[1]["registration"]["status"] == "matched"
    assert trials[1]["response"]["metadata"]["flow"]["evidence_ids"] == ["overview"]
    saved = json.loads((output_dir / "responses/02-p07-overview_plus_detail.json").read_text())
    assert saved["request"]["previous_response_id"] == "first"

    invalid_response = json.loads(json.dumps(detail_response))
    invalid_response["metadata"]["flow"]["evidence_ids"] = ["detail"]
    invalid_response["pattern_identity"]["pattern_id"] = "p08"
    invalid_path = tmp_path / "invalid-responses.json"
    invalid_path.write_text(json.dumps([
        {"id": "first", "status": "completed", "output_text": json.dumps(overview_response), "usage": {"input_tokens": 100, "output_tokens": 30}},
        {"id": "invalid", "status": "completed", "output_text": json.dumps(invalid_response), "usage": {"input_tokens": 100, "output_tokens": 30}},
    ]))
    invalid_output = tmp_path / "invalid-output"
    rejected = subprocess.run([sys.executable, str(COMMAND), "--manifest", str(manifest_path), "--output-dir", str(invalid_output), "--provider", "recorded", "--responses", str(invalid_path)], text=True, capture_output=True, check=False)
    assert rejected.returncode == 2, rejected.stderr
    invalid_trial = json.loads((invalid_output / "trials.json").read_text())[1]
    assert invalid_trial["status"] == "validation_failure"
    assert any("inherited value lacks earlier provenance" in error for error in invalid_trial["validation_errors"])
    assert any("changed verified pattern identity" in error for error in invalid_trial["validation_errors"])
