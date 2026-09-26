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
        def request_agent(self, image_path, phase, previous_response_id=None, metadata=None):
            request = build_agent_request(image_path, phase, previous_response_id, metadata)
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
            assert session["patterns"][0]["agent_phase"] == "verify"
            assert session["guidance"]["action"] == "show_full_pattern"
            assert (await client.get(f"/api/sessions/{session_id}/results", headers=headers)).json()["rows"] == []
            events = (await client.get(f"/api/sessions/{session_id}/diagnostics", headers=headers)).json()["events"]
            responses = [event for event in events if event["event"] == "model_response"]
            assert len(responses) == 3 and responses[0]["data"]["response_id"] == "recorded-camera-1"
            response_log = Path(responses[0]["data"]["response_path"]).read_text()
            assert "<image omitted" in response_log and "data:image" not in response_log
            assert all("sha" not in json.dumps(event["data"]).lower() for event in events)
            repeated = await client.post(f"/api/sessions/{session_id}/observations", headers={**upload_headers, "X-Idempotency-Key": "same-photo-again"}, content=source.read_bytes())
            assert repeated.json()["observation_id"] == observation_id
            assert len(calls) == 3 and calls[0][0] == "identify"
            model_text = calls[0][1]["instructions"] + calls[0][1]["input"][0]["content"][0]["text"] + json.dumps(calls[0][1]["text"])
            assert all(term not in model_text.lower() for term in ("sha", "hash", "evidence", "observation id"))
            saved_path = Path(session["patterns"][0]["last_image_path"])
            assert saved_path.exists()

            with Image.open(source) as image:
                oriented = ImageOps.exif_transpose(image).convert("RGB")
            expected_phases = ["candidate", "verify", "verify"]
            for index, (factor, expected_phase) in enumerate(zip((1.03, 0.97, 1.06), expected_phases), 1):
                view = tmp_path / f"view-{index}.jpg"
                ImageEnhance.Brightness(oriented).enhance(factor).save(view, quality=93)
                next_upload = await client.post(f"/api/sessions/{session_id}/observations", headers={**headers, "X-Idempotency-Key": f"view-{index}", "Content-Type": "image/jpeg"}, content=view.read_bytes())
                assert next_upload.status_code == 200, next_upload.text
                observation = await await_observation(next_upload.json()["observation_id"])
                assert observation["status"] == "complete", observation
                session = (await client.get(f"/api/sessions/{session_id}", headers=headers)).json()
                assert session["patterns"][0]["agent_phase"] == expected_phase
                rows = (await client.get(f"/api/sessions/{session_id}/results", headers=headers)).json()["rows"]
                assert rows == ([] if index < 3 else [{"pa": "0.05", "flow": "15.1", "acceleration": "4000", "pattern_id": session["patterns"][0]["id"]}])
            assert [phase for phase, _ in calls] == ["identify", "metadata", "candidate", "verify", "candidate", "verify"]
            assert "previous_response_id" not in calls[3][1] and "previous_response_id" not in calls[5][1]
            assert '"flow": 15.1' in calls[3][1]["instructions"]
            assert '"acceleration": 4000' in calls[3][1]["instructions"]
            assert '0.05' not in calls[3][1]["instructions"]
            assert (await client.delete(f"/api/sessions/{session_id}", headers=headers)).json() == {"deleted": True}
            assert not saved_path.exists()
            assert (await client.get(f"/api/sessions/{session_id}", headers=headers)).status_code == 404
    asyncio.run(exercise())


def test_inspection_images_progress_and_authenticated_access(tmp_path, monkeypatch):
    import base64
    import io
    import threading

    from pa_eval import session_engine
    from pa_eval.provider import RecordedProvider

    monkeypatch.setattr(server, "DATA_DIR", tmp_path / "app")
    monkeypatch.setattr(server, "DB_PATH", tmp_path / "app" / "sessions.sqlite3")
    monkeypatch.setattr(session_engine.vision, "locate_regions", lambda _: [{"bbox": [0, 0, 100, 80]}])
    fixture = tmp_path / "responses.json"
    fixture.write_text(json.dumps([
        {"id": "mark", "status": "completed", "cost_usd": 0, "output": [
            {"type": "function_call", "call_id": "mark-call", "name": "inspect_region",
             "arguments": json.dumps({"box": [100, 200, 500, 700], "label": "Printed PA marks", "rotation": 0})}]},
        {"status": "unclear", "next_view": "closer", "reason": "Show the marked PA labels closer."},
    ]))
    continuation_entered, release = threading.Event(), threading.Event()
    requests = []

    class PausedProvider(RecordedProvider):
        def continue_inspection(self, *args, **kwargs):
            continuation_entered.set()
            if not release.wait(10):
                raise AssertionError("test did not release continuation")
            response = super().continue_inspection(*args, **kwargs)
            requests.append(response["request"])
            return response

    monkeypatch.setattr(server, "_provider", lambda _: PausedProvider(fixture))
    image = io.BytesIO()
    Image.new("RGB", (100, 80), "white").save(image, "PNG")

    async def exercise():
        async with server.lifespan(server.app), httpx2.AsyncClient(transport=httpx2.ASGITransport(app=server.app), base_url="http://test") as client:
            session = (await client.post("/api/sessions")).json()
            headers = {"X-Session-Secret": session["access_secret"]}
            base = f"/api/sessions/{session['id']}"
            upload = await client.post(f"{base}/observations", headers={**headers, "X-Idempotency-Key": "mark", "Content-Type": "image/png"}, content=image.getvalue())
            oid = upload.json()["observation_id"]
            for _ in range(300):
                if continuation_entered.is_set():
                    break
                await asyncio.sleep(0.02)
            assert continuation_entered.is_set()
            observation = (await client.get(f"{base}/observations/{oid}", headers=headers)).json()
            assert observation["status"] == "processing"
            target = observation["progress"]["target"]
            assert target == {"observation_id": oid, "inspection_index": 0, "box": [100, 200, 500, 700], "label": "Printed PA marks"}
            assert observation["progress"]["phase"] == "identify"
            assert observation["progress"]["activity"] == "inspecting"
            endpoint = f"{base}/observations/{oid}/inspection/0"
            assert (await client.get(f"{endpoint}/marked")).status_code == 404
            other = (await client.post("/api/sessions")).json()
            assert (await client.get(f"/api/sessions/{other['id']}/observations/{oid}/inspection/0/marked", headers={"X-Session-Secret": other["access_secret"]})).status_code == 404
            rendered = {}
            for kind, size in (("marked", (100, 80)), ("detail", (160, 160))):
                response = await client.get(f"{endpoint}/{kind}", headers=headers)
                assert response.status_code == 200
                assert response.headers["cache-control"] == "no-store"
                assert Image.open(io.BytesIO(response.content)).size == size
                rendered[kind] = response.content
            assert (await client.get(f"{base}/observations/{oid}/inspection/99/marked", headers=headers)).status_code == 404
            release.set()
            for _ in range(100):
                observation = (await client.get(f"{base}/observations/{oid}", headers=headers)).json()
                if observation["status"] != "processing":
                    break
                await asyncio.sleep(0.02)
            assert observation["status"] == "complete", observation
            guidance = (await client.get(base, headers=headers)).json()["guidance"]
            assert guidance["target"] == target and guidance["reason"] == "Show the marked PA labels closer."
            request = requests[0]
            assert request["previous_response_id"] == "mark" and request["tools"]
            output = request["input"][0]
            assert output["type"] == "function_call_output" and output["call_id"] == "mark-call"
            assert len(output["output"]) == 2
            assert base64.b64decode(output["output"][1]["image_url"].split(",", 1)[1]) == rendered["detail"]
            logs = list((server.DATA_DIR / session["id"]).rglob("responses/*.json"))
            assert len(logs) == 2
            assert all("data:image" not in path.read_text() for path in logs)
            image_log = json.loads(next(path for path in logs if path.name.endswith("-2.json")).read_text())["request"]["input"][0]["output"][1]
            assert image_log["image_role"] == "inspection_detail" and image_log["image_size"] == [160, 160]
            assert Path(image_log["image_file"]).read_bytes() == rendered["detail"]
    try:
        asyncio.run(exercise())
    finally:
        release.set()


def test_invalid_inspection_and_continuation_budget(tmp_path, monkeypatch):
    from pa_eval import session_engine
    from pa_eval.provider import RecordedProvider

    monkeypatch.setattr(session_engine.vision, "locate_regions", lambda _: [{"bbox": [0, 0, 100, 80]}])
    photo = tmp_path / "photo.png"
    Image.new("RGB", (100, 80), "white").save(photo)
    fixture = tmp_path / "responses.json"
    for index, box in enumerate(([500, 0, 200, 100], [0, 0, 1001, 100], [0, 0, True, 100], [0, 0, 0, 100])):
        fixture.write_text(json.dumps([{"id": "bad", "cost_usd": 0, "output": [{"type": "function_call", "name": "inspect_region", "call_id": "bad", "arguments": json.dumps({"box": box, "label": "label", "rotation": 0})}]}]))
        result = session_engine.analyze_observation(photo, f"bad-{index}", [], tmp_path / str(index), RecordedProvider(fixture))
        assert result["patterns"][0]["status"] == "model_error"
        assert result["guidance"]["target"] is None
        assert result["inspections"] == []
    fixture.write_text(json.dumps([{"id": "mark", "cost_usd": 0, "output": [{"type": "function_call", "name": "inspect_region", "call_id": "mark", "arguments": json.dumps({"box": [0, 0, 500, 500], "label": "label", "rotation": 0})}]}]))
    monkeypatch.setattr(session_engine, "MAX_MODEL_CALLS", 1)
    result = session_engine.analyze_observation(photo, "bounded", [], tmp_path / "bounded", RecordedProvider(fixture))
    assert result["usage"]["calls"] == 1
    assert result["patterns"][0]["reason"] == "inspection_limit_reached"
    assert result["patterns"][0]["status"] == "inconclusive"


def test_inspection_sdk_sends_changed_crop_each_round(tmp_path, monkeypatch):
    import base64
    import io

    from openai import OpenAI
    from pa_eval import session_engine
    from pa_eval.provider import LiveProvider

    photo = tmp_path / "photo.png"
    source = Image.new("RGB", (100, 80), "white")
    source.paste("red", (0, 0, 50, 40))
    source.paste("blue", (50, 0, 100, 40))
    source.paste("green", (0, 40, 50, 80))
    source.save(photo)
    monkeypatch.setattr(session_engine.vision, "locate_regions", lambda _: [{"bbox": [0, 0, 100, 80]}])
    requests = []
    boxes = [[0, 0, 500, 500], [500, 0, 1000, 500], [0, 500, 500, 1000]]

    def handle(request):
        requests.append(json.loads(request.content))
        index = len(requests) - 1
        if index < 3:
            output = [{"type": "function_call", "name": "inspect_region", "call_id": f"crop-{index}",
                       "arguments": json.dumps({"box": boxes[index], "label": "Printed mark", "rotation": 90})}]
        else:
            output = [{"type": "message", "content": [{"type": "output_text", "text": json.dumps({
                "status": "unclear", "next_view": "closer", "reason": "Need a sharper view."})}]}]
        return httpx2.Response(200, json={"id": f"response-{index}", "status": "completed", "cost_usd": 0, "output": output})

    with OpenAI(api_key="test-only", max_retries=0, http_client=httpx2.Client(transport=httpx2.MockTransport(handle))) as client:
        result = session_engine.analyze_observation(photo, "zoom", [], tmp_path / "work", LiveProvider(api_key="test-only", client=client))
    assert result["patterns"][0]["status"] == "awaiting_detail", result
    assert len(requests) == 4 and result["usage"]["calls"] == 4
    assert all(request["tools"] for request in requests[:-1]) and requests[-1]["tools"] == []
    for index, (request, color) in enumerate(zip(requests[1:], ((255, 0, 0), (0, 0, 255), (0, 128, 0)))):
        assert request["previous_response_id"] == f"response-{index}"
        output = request["input"][0]
        assert output["call_id"] == f"crop-{index}"
        images = [part for part in output["output"] if part["type"] == "input_image"]
        assert len(images) == 1
        raw = base64.b64decode(images[0]["image_url"].split(",", 1)[1])
        assert raw == (tmp_path / "work" / "inspections" / f"{index}-detail.png").read_bytes()
        detail = Image.open(io.BytesIO(raw))
        assert detail.size == (160, 200)
        assert detail.getpixel((80, 100)) == color


def test_unmatched_followup_keeps_printed_settings_and_candidate(tmp_path, monkeypatch):
    from pa_eval import session_engine

    photo = tmp_path / "photo.png"
    Image.new("RGB", (100, 80), "white").save(photo)
    monkeypatch.setattr(session_engine.vision, "locate_regions", lambda _: [{"bbox": [0, 0, 100, 80]}])
    monkeypatch.setattr(session_engine.vision, "match_regions", lambda *args: {"status": "weak_registration"})
    known = {"id": "known", "agent_phase": "verify", "status": "awaiting_detail",
             "metadata": {"flow": 3.79, "acceleration": 2000},
             "candidate": {"pa": 0.07, "line_rank": 9, "observation_id": "first"},
             "last_image_path": str(photo), "last_region": [0, 0, 100, 80]}
    result = session_engine.analyze_observation(photo, "rotated", [known], tmp_path / "work", object())
    assert len(result["patterns"]) == 1
    assert result["patterns"][0]["metadata"] == known["metadata"]
    assert result["patterns"][0]["candidate"] == known["candidate"]
    assert result["patterns"][0]["agent_phase"] == "verify"
    assert result["guidance"]["action"] == "show_full_pattern" and result["usage"]["calls"] == 0
    monkeypatch.setattr(session_engine, "MAX_VIEWS_PER_PATTERN", 2)
    limited = session_engine.analyze_observation(photo, "still-unmatched", result["patterns"], tmp_path / "work", object())
    assert limited["patterns"][0]["status"] == "inconclusive"
    assert limited["guidance"]["action"] == "scan_next"


def test_cancel_suppresses_late_progress_and_result(tmp_path, monkeypatch):
    import io
    import threading

    from pa_eval import session_engine

    monkeypatch.setattr(server, "DATA_DIR", tmp_path / "app")
    monkeypatch.setattr(server, "DB_PATH", tmp_path / "app" / "sessions.sqlite3")
    monkeypatch.setattr(server, "_provider", lambda _: object())
    waiting, release = threading.Event(), threading.Event()

    def analyze(_image, _oid, patterns, _work, _provider, callback):
        callback({"progress": {"phase": "identify", "activity": "analyzing", "target": None, "started_at": 1}, "inspections": []})
        waiting.set()
        if not release.wait(10):
            raise AssertionError("test did not release analysis")
        callback({"progress": {"phase": "metadata", "activity": "analyzing", "target": None, "started_at": 2}, "inspections": []})
        return {"patterns": patterns, "guidance": {"action": "closer"}, "progress": None}

    monkeypatch.setattr(session_engine, "analyze_observation", analyze)
    picture = io.BytesIO()
    Image.new("RGB", (10, 10)).save(picture, "PNG")

    async def exercise():
        async with server.lifespan(server.app), httpx2.AsyncClient(transport=httpx2.ASGITransport(app=server.app), base_url="http://test") as client:
            session = (await client.post("/api/sessions")).json()
            base = f"/api/sessions/{session['id']}"
            headers = {"X-Session-Secret": session["access_secret"]}
            upload = await client.post(f"{base}/observations", headers={**headers, "X-Idempotency-Key": "cancel", "Content-Type": "image/png"}, content=picture.getvalue())
            oid = upload.json()["observation_id"]
            for _ in range(300):
                if waiting.is_set():
                    break
                await asyncio.sleep(0.02)
            assert waiting.is_set()
            cancelled = (await client.post(f"{base}/cancel", headers=headers)).json()
            release.set()
            for _ in range(300):
                if oid not in server.app.state.observation_tasks:
                    break
                await asyncio.sleep(0.02)
            assert oid not in server.app.state.observation_tasks
            observation = (await client.get(f"{base}/observations/{oid}", headers=headers)).json()
            current = (await client.get(base, headers=headers)).json()
            assert observation["progress"]["phase"] == "identify"
            assert observation["status"] != "complete"
            assert current["revision"] == cancelled["revision"]
            assert current["status"] == "cancelled" and current["guidance"]["action"] == "stop"
    try:
        asyncio.run(exercise())
    finally:
        release.set()
