"""Authenticated session API with persisted, bounded observation processing."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import io
import json
import mimetypes
import os
import secrets
import shutil
import sqlite3
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager, suppress
from decimal import Decimal, InvalidOperation
from functools import partial
from pathlib import Path
from typing import Any, Iterator, Literal

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel

from pa_eval.provider import LiveProvider, RecordedProvider


DATA_DIR = Path(os.getenv("PA_DATA_DIR", "results/app"))
DB_PATH = DATA_DIR / "sessions.sqlite3"
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_STATIC_BYTES = 25 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
TTL_SECONDS = 14 * 24 * 3600
WORKERS = 2


class CreatedSession(BaseModel):
    id: str
    access_secret: str
    revision: int
    stage: str


class GuidanceTarget(BaseModel):
    observation_id: str
    box: list[float]
    reason: str | None = None


class Guidance(BaseModel):
    action: Literal[
        "move_left", "move_right", "move_up", "move_down", "closer", "farther",
        "tilt_left", "tilt_right", "hold_still", "improve_lighting",
        "show_full_pattern", "scan_next", "complete", "inconclusive", "stop",
    ]
    reason: str | None = None
    target: GuidanceTarget | None = None


class SessionState(BaseModel):
    id: str
    revision: int
    stage: str
    status: str
    patterns: list[dict[str, Any]]
    observation_count: int
    guidance: Guidance
    created_at: float
    updated_at: float


class QueuedObservation(BaseModel):
    observation_id: str
    revision: int
    status: str


class ObservationState(QueuedObservation):
    session_id: str
    result: dict[str, Any] | None
    error: dict[str, Any] | None


class GuidanceState(BaseModel):
    revision: int
    guidance: Guidance


class ResultRow(BaseModel):
    pa: str
    flow: str
    acceleration: str
    pattern_id: str | None
    evidence: list[str]


class ResultsState(BaseModel):
    revision: int
    rows: list[ResultRow]
    unresolved: list[dict[str, Any]]
    conflicts: list[dict[str, Any]]


class ExportState(ResultsState):
    text: str


class DiagnosticEvent(BaseModel):
    id: int
    observation_id: str | None
    event: str
    data: dict[str, Any]
    created_at: float


class DiagnosticsState(BaseModel):
    revision: int
    events: list[DiagnosticEvent]


class DeleteResult(BaseModel):
    deleted: bool


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        with conn:
            yield conn
    finally:
        conn.close()


def _init_db() -> None:
    with _db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, secret_hash TEXT NOT NULL, revision INTEGER NOT NULL,
                stage TEXT NOT NULL, status TEXT NOT NULL, patterns TEXT NOT NULL,
                guidance TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS observations (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                idempotency_key TEXT NOT NULL, status TEXT NOT NULL, image_path TEXT NOT NULL,
                image_sha256 TEXT NOT NULL, result TEXT, error TEXT, created_at REAL NOT NULL,
                updated_at REAL NOT NULL, UNIQUE(session_id, idempotency_key)
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                observation_id TEXT, event TEXT NOT NULL, data TEXT NOT NULL, created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS observations_session ON observations(session_id);
            CREATE INDEX IF NOT EXISTS events_session ON events(session_id);
        """)


def _event(conn: sqlite3.Connection, session_id: str, event: str, observation_id: str | None = None, **data: Any) -> None:
    conn.execute(
        "INSERT INTO events(session_id,observation_id,event,data,created_at) VALUES(?,?,?,?,?)",
        (session_id, observation_id, event, json.dumps(data, default=str), time.time()),
    )


def _session(conn: sqlite3.Connection, session_id: str, secret: str | None) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    supplied = hashlib.sha256((secret or "").encode()).hexdigest()
    if row is None or not hmac.compare_digest(row["secret_hash"] if row else "0" * 64, supplied):
        raise HTTPException(404, detail={"code": "session_not_found"})
    return row


def _revision(conn: sqlite3.Connection, session_id: str, *, stage: str | None = None, status: str | None = None, patterns: list[dict] | None = None, guidance: dict | None = None) -> int:
    changes = ["revision=revision+1", "updated_at=?"]
    values: list[Any] = [time.time()]
    for name, value in (("stage", stage), ("status", status), ("patterns", patterns), ("guidance", guidance)):
        if value is not None:
            changes.append(f"{name}=?")
            values.append(json.dumps(value) if name in ("patterns", "guidance") else value)
    values.append(session_id)
    conn.execute(f"UPDATE sessions SET {','.join(changes)} WHERE id=?", values)
    return conn.execute("SELECT revision FROM sessions WHERE id=?", (session_id,)).fetchone()[0]


def _public_session(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "revision": row["revision"], "stage": row["stage"],
        "status": row["status"], "patterns": json.loads(row["patterns"]),
        "observation_count": conn.execute("SELECT COUNT(*) FROM observations WHERE session_id=?", (row["id"],)).fetchone()[0],
        "guidance": json.loads(row["guidance"]), "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def _observation(row: sqlite3.Row, revision: int) -> dict:
    return {
        "observation_id": row["id"], "session_id": row["session_id"],
        "status": row["status"], "revision": revision,
        "result": json.loads(row["result"]) if row["result"] else None,
        "error": json.loads(row["error"]) if row["error"] else None,
    }


def _cleanup_expired() -> None:
    cutoff = time.time() - TTL_SECONDS
    with _db() as conn:
        expired = [row[0] for row in conn.execute("SELECT id FROM sessions WHERE updated_at < ?", (cutoff,))]
        for session_id in expired:
            conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
    for session_id in expired:
        shutil.rmtree(DATA_DIR / session_id, ignore_errors=True)


async def _cleanup_periodically() -> None:
    while True:
        await asyncio.sleep(3600)
        _cleanup_expired()


def _provider() -> LiveProvider | RecordedProvider:
    recording = os.getenv("PA_RECORDED_RESPONSES")
    return RecordedProvider(recording) if recording else LiveProvider()


async def _process_one(app: FastAPI, observation_id: str) -> None:
    async with app.state.worker_semaphore:
        with _db() as conn:
            row = conn.execute("SELECT * FROM observations WHERE id=?", (observation_id,)).fetchone()
            if row is None:
                return
            session = conn.execute("SELECT * FROM sessions WHERE id=?", (row["session_id"],)).fetchone()
            if session is None or session["status"] != "active":
                return
            now = time.time()
            conn.execute("UPDATE observations SET status='processing', updated_at=? WHERE id=?", (now, observation_id))
            revision = _revision(conn, row["session_id"], stage="analyzing_evidence")
            _event(conn, row["session_id"], "observation_processing", observation_id, revision=revision, image_sha256=row["image_sha256"])
            patterns = json.loads(session["patterns"])
            image_path = Path(row["image_path"])
            session_id = row["session_id"]
        try:
            from pa_eval.session_engine import analyze_observation

            result = await asyncio.get_running_loop().run_in_executor(
                app.state.executor,
                partial(analyze_observation, image_path, observation_id, patterns,
                        DATA_DIR / session_id / "work" / observation_id, _provider()),
            )
            if not isinstance(result, dict) or not isinstance(result.get("patterns"), list) or not isinstance(result.get("guidance"), dict):
                raise ValueError("engine returned invalid session state")
            with _db() as conn:
                session = conn.execute("SELECT status FROM sessions WHERE id=?", (session_id,)).fetchone()
                if session is None or session["status"] != "active":
                    return
                guidance = result["guidance"]
                stage = "complete" if guidance.get("action") == "complete" else "needing_guidance"
                revision = _revision(conn, session_id, stage=stage, patterns=result["patterns"], guidance=guidance)
                conn.execute(
                    "UPDATE observations SET status='complete',result=?,error=NULL,updated_at=? WHERE id=?",
                    (json.dumps(result, default=str), time.time(), observation_id),
                )
                for item in result.get("events", []):
                    if isinstance(item, dict):
                        safe = {key: item[key] for key in (
                            "pattern_id", "status", "reason", "response_id", "action", "cost_usd", "calls",
                            "image_sha256", "crop_sha256", "crop_bbox", "boxes", "count", "image_size",
                            "region_index", "matches", "previous_response_id", "provider_status", "usage",
                            "latency_ms", "errors", "attempts", "target", "measurement", "response_path",
                            "error_type", "source_sha256", "image_path", "crop_path",
                            "gate_reason", "selected_line_id", "assessment_status",
                        ) if key in item}
                        _event(conn, session_id, str(item.get("event", item.get("type", "engine_event")))[:80], observation_id, **safe)
                _event(conn, session_id, "observation_complete", observation_id, revision=revision, stage=stage, guidance_action=guidance.get("action"), usage=result.get("usage"))
        except Exception as exc:
            with _db() as conn:
                session = conn.execute("SELECT status FROM sessions WHERE id=?", (session_id,)).fetchone()
                if session is None or session["status"] != "active":
                    return
                code = "model_failure" if exc.__class__.__name__ == "ProviderError" else "processing_failure"
                revision = _revision(conn, session_id, stage="needing_guidance", guidance={"action": "hold_still", "reason": code})
                conn.execute(
                    "UPDATE observations SET status='failed',error=?,updated_at=? WHERE id=?",
                    (json.dumps({"code": code}), time.time(), observation_id),
                )
                _event(conn, session_id, "observation_failed", observation_id, revision=revision, code=code, error_type=type(exc).__name__)


async def _process(app: FastAPI, observation_id: str) -> None:
    with _db() as conn:
        row = conn.execute("SELECT session_id FROM observations WHERE id=?", (observation_id,)).fetchone()
    if row is None:
        return
    session_id = row["session_id"]
    async with app.state.session_locks.setdefault(session_id, asyncio.Lock()):
        await _process_one(app, observation_id)


def _queue(app: FastAPI, observation_id: str) -> None:
    task = asyncio.create_task(_process(app, observation_id))
    app.state.tasks.add(task)
    app.state.observation_tasks[observation_id] = task
    task.add_done_callback(app.state.tasks.discard)
    task.add_done_callback(lambda _: app.state.observation_tasks.pop(observation_id, None))


@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_db()
    _cleanup_expired()
    app.state.worker_semaphore = asyncio.Semaphore(WORKERS)
    app.state.executor = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="pa-analysis")
    app.state.session_locks = {}
    app.state.tasks = set()
    app.state.observation_tasks = {}
    cleanup_task = asyncio.create_task(_cleanup_periodically())
    with _db() as conn:
        pending = [row[0] for row in conn.execute("SELECT id FROM observations WHERE status IN ('queued','processing')")]
    for observation_id in pending:
        _queue(app, observation_id)
    yield
    cleanup_task.cancel()
    with suppress(asyncio.CancelledError):
        await cleanup_task
    if app.state.tasks:
        await asyncio.gather(*app.state.tasks, return_exceptions=True)
    app.state.executor.shutdown(wait=True)


app = FastAPI(title="Adaptive PA camera API", lifespan=lifespan)


@app.post("/api/sessions", response_model=CreatedSession)
async def create_session() -> dict:
    _init_db()
    _cleanup_expired()
    session_id = str(uuid.uuid4())
    secret = secrets.token_urlsafe(32)
    now = time.time()
    with _db() as conn:
        conn.execute(
            "INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?,?)",
            (session_id, hashlib.sha256(secret.encode()).hexdigest(), 1, "acquiring_overview", "active", "[]", '{"action":"show_full_pattern"}', now, now),
        )
        _event(conn, session_id, "session_created", revision=1, stage="acquiring_overview")
    return {"id": session_id, "access_secret": secret, "revision": 1, "stage": "acquiring_overview"}


@app.get("/api/sessions/{session_id}", response_model=SessionState)
async def get_session(session_id: str, x_session_secret: str | None = Header(default=None)) -> dict:
    with _db() as conn:
        return _public_session(conn, _session(conn, session_id, x_session_secret))


_IMAGE_BODY = {mime: {"schema": {"type": "string", "format": "binary"}} for mime in ("image/jpeg", "image/png", "image/webp")}


@app.post("/api/sessions/{session_id}/observations", response_model=QueuedObservation,
          openapi_extra={"requestBody": {"required": True, "content": _IMAGE_BODY}})
async def upload_observation(session_id: str, request: Request, x_idempotency_key: str = Header(...), x_session_secret: str | None = Header(default=None)) -> dict:
    idempotency_key = x_idempotency_key
    if not 1 <= len(idempotency_key) <= 128:
        raise HTTPException(422, detail={"code": "invalid_idempotency_key"})
    with _db() as conn:
        session = _session(conn, session_id, x_session_secret)
        if session["status"] != "active":
            raise HTTPException(409, detail={"code": "session_not_active"})
        existing = conn.execute("SELECT * FROM observations WHERE session_id=? AND idempotency_key=?", (session_id, idempotency_key)).fetchone()
        if existing:
            return _observation(existing, session["revision"])
        if conn.execute("SELECT COUNT(*) FROM observations WHERE session_id=?", (session_id,)).fetchone()[0] >= 100:
            raise HTTPException(409, detail={"code": "observation_limit_reached"})
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(415, detail={"code": "invalid_image"})
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_IMAGE_BYTES:
            raise HTTPException(413, detail={"code": "image_too_large"})
        chunks.append(chunk)
    raw = b"".join(chunks)
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.format not in ("JPEG", "PNG", "WEBP") or source.width * source.height > MAX_IMAGE_PIXELS:
                raise ValueError("unsupported image or excessive dimensions")
            normalized = ImageOps.exif_transpose(source).convert("RGB")
            output = io.BytesIO()
            normalized.save(output, format="JPEG", quality=94)
            payload = output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(415, detail={"code": "invalid_image"}) from None
    observation_id = str(uuid.uuid4())
    folder = DATA_DIR / session_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{observation_id}.jpg"
    path.write_bytes(payload)
    now = time.time()
    with _db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        session = _session(conn, session_id, x_session_secret)
        if session["status"] != "active":
            path.unlink(missing_ok=True)
            raise HTTPException(409, detail={"code": "session_not_active"})
        existing = conn.execute("SELECT * FROM observations WHERE session_id=? AND idempotency_key=?", (session_id, idempotency_key)).fetchone()
        if existing:
            path.unlink(missing_ok=True)
            return _observation(existing, session["revision"])
        if conn.execute("SELECT COUNT(*) FROM observations WHERE session_id=?", (session_id,)).fetchone()[0] >= 100:
            path.unlink(missing_ok=True)
            raise HTTPException(409, detail={"code": "observation_limit_reached"})
        digest = hashlib.sha256(payload).hexdigest()
        conn.execute(
            "INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?)",
            (observation_id, session_id, idempotency_key, "queued", str(path), digest, None, None, now, now),
        )
        revision = _revision(conn, session_id, stage="analyzing_evidence")
        _event(conn, session_id, "observation_queued", observation_id, revision=revision, image_sha256=digest, bytes=len(payload), width=normalized.width, height=normalized.height)
    _queue(app, observation_id)
    return {"observation_id": observation_id, "revision": revision, "status": "queued"}


@app.get("/api/sessions/{session_id}/observations/{observation_id}", response_model=ObservationState)
async def get_observation(session_id: str, observation_id: str, x_session_secret: str | None = Header(default=None)) -> dict:
    with _db() as conn:
        session = _session(conn, session_id, x_session_secret)
        row = conn.execute("SELECT * FROM observations WHERE id=? AND session_id=?", (observation_id, session_id)).fetchone()
        if row is None:
            raise HTTPException(404, detail={"code": "observation_not_found"})
        return _observation(row, session["revision"])


@app.get("/api/sessions/{session_id}/guidance", response_model=GuidanceState)
async def get_guidance(session_id: str, x_session_secret: str | None = Header(default=None)) -> dict:
    with _db() as conn:
        row = _session(conn, session_id, x_session_secret)
        return {"revision": row["revision"], "guidance": json.loads(row["guidance"])}


def _results(patterns: list[dict]) -> dict:
    rows: list[dict] = []
    unresolved: list[dict] = []
    conflicts: list[dict] = []
    pairs: dict[tuple[Decimal, Decimal], dict] = {}
    blocked: set[tuple[Decimal, Decimal]] = set()
    for pattern in patterns:
        measurement = pattern.get("measurement")
        if pattern.get("status") != "complete" or not isinstance(measurement, dict):
            unresolved.append({"id": pattern.get("id"), "status": pattern.get("status", "inconclusive"), "reason": pattern.get("reason")})
            continue
        try:
            pa, flow, acceleration = (str(measurement[key]) for key in ("pa", "flow", "acceleration"))
            pa_value, flow_value, acceleration_value = (Decimal(value) for value in (pa, flow, acceleration))
            if not all(value.is_finite() for value in (pa_value, flow_value, acceleration_value)) or pa_value < 0 or flow_value <= 0 or acceleration_value <= 0:
                raise ValueError("invalid measurement")
        except (KeyError, ValueError, TypeError, InvalidOperation):
            unresolved.append({"id": pattern.get("id"), "status": "inconclusive", "reason": "invalid_measurement"})
            continue
        row = {"pa": pa, "flow": flow, "acceleration": acceleration, "pattern_id": pattern.get("id"), "evidence": pattern.get("observation_ids", [])}
        pair = (flow_value, acceleration_value)
        previous = pairs.get(pair)
        if previous is None:
            pairs[pair] = row
        elif Decimal(previous["pa"]) != pa_value:
            blocked.add(pair)
            conflicts.append({"flow": flow, "acceleration": acceleration, "pattern_ids": [previous["pattern_id"], row["pattern_id"]]})
        else:
            previous["evidence"] = list(dict.fromkeys(previous["evidence"] + row["evidence"]))
    rows = [row for pair, row in pairs.items() if pair not in blocked]
    return {"rows": rows, "unresolved": unresolved, "conflicts": conflicts}


@app.get("/api/sessions/{session_id}/results", response_model=ResultsState)
async def get_results(session_id: str, x_session_secret: str | None = Header(default=None)) -> dict:
    with _db() as conn:
        session = _session(conn, session_id, x_session_secret)
        return {"revision": session["revision"], **_results(json.loads(session["patterns"]))}


@app.post("/api/sessions/{session_id}/export", response_model=ExportState)
async def export_results(session_id: str, x_session_secret: str | None = Header(default=None)) -> dict:
    result = await get_results(session_id, x_session_secret)
    result["text"] = "\n".join(f"{row['pa']},{row['flow']},{row['acceleration']}" for row in result["rows"])
    with _db() as conn:
        _event(conn, session_id, "results_exported", revision=result["revision"], rows=len(result["rows"]), conflicts=len(result["conflicts"]))
    return result


@app.post("/api/sessions/{session_id}/cancel", response_model=SessionState)
async def cancel_session(session_id: str, x_session_secret: str | None = Header(default=None)) -> dict:
    with _db() as conn:
        session = _session(conn, session_id, x_session_secret)
        if session["status"] != "cancelled":
            revision = _revision(conn, session_id, stage="inconclusive", status="cancelled", guidance={"action": "stop", "reason": "cancelled"})
            _event(conn, session_id, "session_cancelled", revision=revision)
        return _public_session(conn, conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone())


@app.delete("/api/sessions/{session_id}", response_model=DeleteResult)
async def delete_session(session_id: str, x_session_secret: str | None = Header(default=None)) -> dict:
    with _db() as conn:
        _session(conn, session_id, x_session_secret)
        _revision(conn, session_id, status="cancelled", stage="inconclusive")
    with _db() as conn:
        active_ids = [row[0] for row in conn.execute("SELECT id FROM observations WHERE session_id=?", (session_id,))]
    tasks = [app.state.observation_tasks[observation_id] for observation_id in active_ids if observation_id in app.state.observation_tasks]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    with _db() as conn:
        _session(conn, session_id, x_session_secret)
        conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
    shutil.rmtree(DATA_DIR / session_id, ignore_errors=True)
    app.state.session_locks.pop(session_id, None)
    return {"deleted": True}


@app.get("/api/sessions/{session_id}/diagnostics", response_model=DiagnosticsState)
async def get_diagnostics(session_id: str, x_session_secret: str | None = Header(default=None)) -> dict:
    with _db() as conn:
        session = _session(conn, session_id, x_session_secret)
        events = [
            {"id": row["id"], "observation_id": row["observation_id"], "event": row["event"], "data": json.loads(row["data"]), "created_at": row["created_at"]}
            for row in conn.execute("SELECT * FROM events WHERE session_id=? ORDER BY id", (session_id,))
        ]
        return {"revision": session["revision"], "events": events}


@app.get("/{asset_path:path}", include_in_schema=False)
async def serve_web(asset_path: str) -> Response:
    if asset_path.startswith("api/"):
        raise HTTPException(404)
    root = Path(__file__).resolve().parents[3] / "web" / "dist" / "web" / "browser"
    candidate = (root / asset_path).resolve()
    if not candidate.is_relative_to(root):
        raise HTTPException(404)
    if not candidate.is_file() and "." in Path(asset_path).name:
        raise HTTPException(404)
    if not candidate.is_file():
        candidate = root / "index.html"
    if not candidate.is_file():
        raise HTTPException(404, detail="Web app has not been built")
    with candidate.open("rb") as asset:
        content = asset.read(MAX_STATIC_BYTES + 1)
    if len(content) > MAX_STATIC_BYTES:
        raise HTTPException(413, detail="Web asset is too large")
    return Response(content, media_type=mimetypes.guess_type(candidate.name)[0] or "application/octet-stream")
