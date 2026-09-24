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
    assert report["counts"]["missing_view"] == 1
