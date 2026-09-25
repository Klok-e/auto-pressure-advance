"""One public API path through an uploaded still and the provider boundary."""

import asyncio
import json
import sys
from pathlib import Path

import httpx2
from PIL import Image, ImageEnhance, ImageOps


API_DIR = Path(__file__).resolve().parents[1] / "services/api"
sys.path.insert(0, str(API_DIR))

from pa_app import server  # noqa: E402
from pa_eval.agent_protocol import build_agent_request  # noqa: E402


def test_session_upload_progress_diagnostics_and_deletion(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA_DIR", tmp_path / "app")
    monkeypatch.setattr(server, "DB_PATH", tmp_path / "app" / "sessions.sqlite3")
    calls = []

    class RecordedBoundary:
        def request_agent(self, image_path, phase, previous_response_id=None):
            request = build_agent_request(image_path, phase, previous_response_id)
            calls.append((phase, request))
            responses = [
                {"status": "supported", "next_view": None, "reason": "Herringbone pattern visible"},
                {"status": "read", "flow": 15.1, "acceleration": 4000, "next_view": None, "reason": "Printed settings visible"},
                {"status": "assessed", "pa": 0.05, "line_rank": 5, "next_view": None, "reason": "Best corner"},
                {"status": "assessed", "pa": 0.05, "line_rank": 6, "next_view": None, "reason": "Best corner"},
                {"status": "assessed", "pa": 0.05, "line_rank": 5, "next_view": None, "reason": "Best corner"},
                {"status": "assessed", "pa": 0.05, "line_rank": 5, "next_view": None, "reason": "Best corner"},
            ]
            response = responses[len(calls) - 1]
            return {"id": f"recorded-camera-{len(calls)}", "status": "completed", "output_text": json.dumps(response), "usage": {"input_tokens": 100, "output_tokens": 30}, "cost_usd": 0.0, "latency_ms": 0.0, "request": request, "raw": response}

    monkeypatch.setattr(server, "_provider", lambda patterns: RecordedBoundary())
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
            async def await_observation(current_id):
                for _ in range(200):
                    observation = (await client.get(f"/api/sessions/{session_id}/observations/{current_id}", headers=headers)).json()
                    if observation["status"] in {"complete", "failed"}:
                        return observation
                    await asyncio.sleep(0.1)
                raise AssertionError("observation processing timed out")

            observation = await await_observation(observation_id)
            assert observation["status"] == "complete", observation
            session = (await client.get(f"/api/sessions/{session_id}", headers=headers)).json()
            assert session["patterns"] and session["patterns"][0]["status"] != "complete"
            assert session["patterns"][0]["agent_phase"] == "metadata"
            assert session["guidance"]["action"] == "closer"
            assert (await client.get(f"/api/sessions/{session_id}/results", headers=headers)).json()["rows"] == []
            events = (await client.get(f"/api/sessions/{session_id}/diagnostics", headers=headers)).json()["events"]
            responses = [event for event in events if event["event"] == "model_response"]
            assert len(responses) == 1 and responses[0]["data"]["response_id"] == "recorded-camera-1"
            response_log = Path(responses[0]["data"]["response_path"]).read_text()
            assert "<image omitted" in response_log and "data:image" not in response_log
            assert all("sha" not in json.dumps(event["data"]).lower() for event in events)
            repeated = await client.post(f"/api/sessions/{session_id}/observations", headers={**upload_headers, "X-Idempotency-Key": "same-photo-again"}, content=source.read_bytes())
            assert repeated.json()["observation_id"] == observation_id
            assert len(calls) == 1 and calls[0][0] == "identify"
            model_text = calls[0][1]["instructions"] + calls[0][1]["input"][0]["content"][0]["text"] + json.dumps(calls[0][1]["text"])
            assert all(term not in model_text.lower() for term in ("sha", "hash", "evidence", "observation id"))
            saved_path = Path(session["patterns"][0]["last_image_path"])
            assert saved_path.exists()

            with Image.open(source) as image:
                oriented = ImageOps.exif_transpose(image).convert("RGB")
            expected_phases = ["candidate", "verify", "candidate", "verify", "verify"]
            for index, (factor, expected_phase) in enumerate(zip((1.03, 0.97, 1.06, 0.94, 1.09), expected_phases), 1):
                view = tmp_path / f"view-{index}.jpg"
                ImageEnhance.Brightness(oriented).enhance(factor).save(view, quality=93)
                next_upload = await client.post(f"/api/sessions/{session_id}/observations", headers={**headers, "X-Idempotency-Key": f"view-{index}", "Content-Type": "image/jpeg"}, content=view.read_bytes())
                assert next_upload.status_code == 200, next_upload.text
                observation = await await_observation(next_upload.json()["observation_id"])
                assert observation["status"] == "complete", observation
                session = (await client.get(f"/api/sessions/{session_id}", headers=headers)).json()
                assert session["patterns"][0]["agent_phase"] == expected_phase
                rows = (await client.get(f"/api/sessions/{session_id}/results", headers=headers)).json()["rows"]
                assert rows == ([] if index < 5 else [{"pa": "0.05", "flow": "15.1", "acceleration": "4000", "pattern_id": session["patterns"][0]["id"]}])
            assert [phase for phase, _ in calls] == ["identify", "metadata", "candidate", "verify", "candidate", "verify"]
            assert "previous_response_id" not in calls[3][1] and "previous_response_id" not in calls[5][1]
            assert (await client.delete(f"/api/sessions/{session_id}", headers=headers)).json() == {"deleted": True}
            assert not saved_path.exists()
            assert (await client.get(f"/api/sessions/{session_id}", headers=headers)).status_code == 404
    asyncio.run(exercise())
