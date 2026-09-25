"""One public API path through an uploaded still and the provider boundary."""

import asyncio
import hashlib
import json
import sys
from pathlib import Path

import httpx2


API_DIR = Path(__file__).resolve().parents[1] / "services/api"
sys.path.insert(0, str(API_DIR))

from pa_app import server  # noqa: E402
from pa_eval.protocol import build_request  # noqa: E402


def test_session_upload_progress_diagnostics_and_deletion(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA_DIR", tmp_path / "app")
    monkeypatch.setattr(server, "DB_PATH", tmp_path / "app" / "sessions.sqlite3")
    calls = []

    class RecordedBoundary:
        def request(self, inputs, previous_response_id=None):
            calls.append(inputs[0]["observation_id"])
            observation_id = inputs[0]["observation_id"]
            response = {
                "supported_pattern": True,
                "pattern_identity": {"pattern_id": "OrcaSlicer herringbone PA", "evidence_ids": [observation_id]},
                "metadata": {
                    "flow": {"value": None, "source": "unknown", "evidence_ids": []},
                    "acceleration": {"value": None, "source": "unknown", "evidence_ids": []},
                },
                "labels": [], "candidate_lines": [],
                "assessment": {"status": "inconclusive", "selected_line_id": None, "selected_pa": None, "plausible_line_ids": [], "uncertainty": "Need a closer view of the printed marks", "evidence_ids": [observation_id], "contradiction": False, "contradiction_reason": None},
                "inspection_target": None,
            }
            return {"id": "recorded-camera-1", "status": "completed", "output_text": json.dumps(response), "usage": {"input_tokens": 100, "output_tokens": 30}, "cost_usd": 0.0, "latency_ms": 0.0, "request": build_request(inputs, previous_response_id), "raw": response}

    monkeypatch.setattr(server, "_provider", lambda: RecordedBoundary())
    source = Path(__file__).resolve().parents[1] / "fixtures/images/20260924_191604.jpg"

    async def exercise():
        async with server.lifespan(server.app), httpx2.AsyncClient(transport=httpx2.ASGITransport(app=server.app), base_url="http://test") as client:
            created = (await client.post("/api/sessions")).json()
            session_id = created["id"]
            headers = {"X-Session-Secret": created["access_secret"]}
            assert (await client.get(f"/api/sessions/{session_id}")).status_code == 404
            upload_headers = {**headers, "X-Idempotency-Key": "first-view", "Content-Type": "image/jpeg"}
            upload = await client.post(f"/api/sessions/{session_id}/observations", headers=upload_headers, content=source.read_bytes())
            assert upload.status_code == 200, upload.text
            observation_id = upload.json()["observation_id"]
            assert upload.json()["status"] == "queued"
            for _ in range(200):
                observation = (await client.get(f"/api/sessions/{session_id}/observations/{observation_id}", headers=headers)).json()
                if observation["status"] in {"complete", "failed"}:
                    break
                await asyncio.sleep(0.1)
            assert observation["status"] == "complete", observation
            session = (await client.get(f"/api/sessions/{session_id}", headers=headers)).json()
            assert session["patterns"] and session["patterns"][0]["status"] != "complete"
            assert session["guidance"]["action"] in {"closer", "show_full_pattern"}
            assert (await client.get(f"/api/sessions/{session_id}/results", headers=headers)).json()["rows"] == []
            events = (await client.get(f"/api/sessions/{session_id}/diagnostics", headers=headers)).json()["events"]
            assert any(event["event"] == "model_response" and event["data"]["response_id"] == "recorded-camera-1" for event in events)
            repeated = await client.post(f"/api/sessions/{session_id}/observations", headers=upload_headers, content=source.read_bytes())
            assert repeated.json()["observation_id"] == observation_id
            assert calls == [observation_id]
            saved_path = Path(session["patterns"][0]["last_image_path"])
            assert hashlib.sha256(saved_path.read_bytes()).hexdigest() == session["patterns"][0]["source_sha256"]
            assert (await client.delete(f"/api/sessions/{session_id}", headers=headers)).json() == {"deleted": True}
            assert not saved_path.exists()
            assert (await client.get(f"/api/sessions/{session_id}", headers=headers)).status_code == 404
    asyncio.run(exercise())
