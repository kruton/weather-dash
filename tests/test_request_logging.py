import asyncio
import logging

import pytest
from fastapi.testclient import TestClient

from weather_dash import get_app, request_logging
from weather_dash.request_logging import RequestLoggingMiddleware


def test_access_logs_exclude_health_checks(caplog, tmp_path, monkeypatch):
    frontend = tmp_path / "frontend" / "dist"
    frontend.mkdir(parents=True)
    (frontend / "index.html").write_text("<!doctype html><title>Health check</title>")
    monkeypatch.chdir(tmp_path)
    with caplog.at_level(logging.INFO, logger="weather_dash.access"):
        client = TestClient(get_app())
        assert client.get("/").status_code == 200
        assert client.head("/").status_code == 200
        assert client.get("/healthz").status_code == 200
        assert not [
            record for record in caplog.records if record.name == "weather_dash.access"
        ]
        assert client.get("/metrics").status_code == 200
    messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == "weather_dash.access"
    ]
    assert len(messages) == 1
    assert "GET '/metrics' status=200 duration_ms=" in messages[0]


def test_timing_includes_streamed_response_body(caplog, monkeypatch):
    now = [10.0]
    monkeypatch.setattr(request_logging, "perf_counter", lambda: now[0])

    async def app(scope, receive, send):
        now[0] += 0.1
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"first", "more_body": True})
        assert not caplog.records
        now[0] += 2.4
        await send({"type": "http.response.body", "body": b"last"})
        now[0] += 5  # Background work after the response does not delay the device.

    async def send(message):
        pass

    async def receive():
        return {"type": "http.request", "body": b""}

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/screenshot",
        "query_string": b"width=800&height=480",
        "headers": [(b"x-weather-device-id", b"abcdef0123456789")],
    }
    with caplog.at_level(logging.INFO, logger="weather_dash.access"):
        asyncio.run(RequestLoggingMiddleware(app)(scope, receive, send))
    assert len(caplog.records) == 1
    assert caplog.records[0].getMessage() == (
        "GET '/api/screenshot?width=800&height=480' status=200 "
        "duration_ms=2500.0 device_id='abcdef0123456789'"
    )


def test_failed_request_still_logs_timing(caplog):
    async def app(scope, receive, send):
        raise RuntimeError("Render failed")

    scope = {"type": "http", "method": "GET", "path": "/", "headers": []}
    with (
        caplog.at_level(logging.INFO, logger="weather_dash.access"),
        pytest.raises(RuntimeError, match="Render failed"),
    ):
        asyncio.run(RequestLoggingMiddleware(app)(scope, None, None))
    assert len(caplog.records) == 1
    assert "GET '/' status=500 duration_ms=" in caplog.records[0].getMessage()
