"""Replaceable recorded and live Responses API adapters."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping, Sequence

from .protocol import ENDPOINT, build_request


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, response: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


def _normalize(raw: Mapping[str, Any], request: Mapping[str, Any], latency_ms: float) -> dict[str, Any]:
    if "output_text" in raw:
        output_text = raw["output_text"]
    elif "supported_pattern" in raw:
        output_text = json.dumps(raw)
    else:
        texts = [part["text"] for item in raw.get("output", []) if item.get("type") == "message"
                 for part in item.get("content", []) if part.get("type") == "output_text"]
        output_text = "".join(texts)
    return {
        "id": raw.get("id"),
        "status": raw.get("status", "completed"),
        "output_text": output_text,
        "usage": raw.get("usage"),
        "cost_usd": raw.get("cost_usd", cost_usd_from_usage(raw.get("usage"))),
        "raw": dict(raw),
        "request": dict(request),
        "latency_ms": latency_ms,
    }


def cost_usd_from_usage(usage: Any) -> float | None:
    if not isinstance(usage, dict):
        return None
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    details = usage.get("input_tokens_details") or {}
    cached = details.get("cached_tokens", 0)
    cache_writes = details.get("cache_write_tokens", details.get("cache_creation_tokens", 0))
    if not all(isinstance(value, int) and value >= 0 for value in (input_tokens, output_tokens, cached, cache_writes)):
        return None
    if cached + cache_writes > input_tokens or input_tokens > 272_000:
        return None
    uncached = input_tokens - cached - cache_writes
    return (uncached * 0.10 + cached * 0.01 + cache_writes * 0.125 + output_tokens * 0.50) / 1_000_000


class RecordedProvider:
    """Replay one saved response per request, in order, without interpreting results."""

    def __init__(self, path: str | Path):
        data = json.loads(Path(path).read_text())
        if not isinstance(data, list):
            raise ValueError("recorded response fixture must be a JSON array")
        self._responses = data
        self._index = 0

    def request(self, inputs: Sequence[Mapping[str, Any]], previous_response_id: str | None = None) -> dict[str, Any]:
        request = build_request(inputs, previous_response_id)
        if self._index >= len(self._responses):
            raise ProviderError("recorded responses exhausted")
        raw = self._responses[self._index]
        self._index += 1
        if not isinstance(raw, dict):
            raise ProviderError("recorded response is not an object")
        if "error" in raw:
            raise ProviderError(f"recorded provider error: {raw['error']}", response=raw)
        return _normalize(raw, request, 0.0)


class LiveProvider:
    """Direct HTTPS Responses adapter with no silent detail or model fallback."""

    def __init__(self, api_key: str | None = None, *, timeout: float = 120.0):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ProviderError("OPENAI_API_KEY is required for live requests")
        self.timeout = timeout

    def request(self, inputs: Sequence[Mapping[str, Any]], previous_response_id: str | None = None) -> dict[str, Any]:
        request = build_request(inputs, previous_response_id)
        wire = json.dumps(request, separators=(",", ":")).encode("utf-8")
        http_request = urllib.request.Request(
            ENDPOINT,
            data=wire,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        start = time.monotonic()
        try:
            with urllib.request.urlopen(http_request, timeout=self.timeout) as response:
                raw = json.load(response)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                detail: Any = json.loads(body)
            except ValueError:
                detail = body
            raise ProviderError(f"Responses API HTTP {exc.code}", status_code=exc.code, response=detail) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ProviderError(f"Responses API transport error: {exc}") from exc
        latency_ms = (time.monotonic() - start) * 1000
        if not isinstance(raw, dict):
            raise ProviderError("Responses API returned a non-object", response=raw)
        return _normalize(raw, request, latency_ms)
