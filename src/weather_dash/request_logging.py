"""Access logs measured through completion of the response body."""

import logging
from time import perf_counter

from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger("weather_dash.access")


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        started = perf_counter()
        status = 500
        completed_at = None

        async def send_response(message: Message):
            nonlocal status, completed_at
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)
            if (
                message["type"] == "http.response.body"
                and not message.get("more_body", False)
            ) or message["type"] == "http.response.pathsend":
                completed_at = perf_counter()

        try:
            await self.app(scope, receive, send_response)
        finally:
            elapsed_ms = (
                (completed_at if completed_at is not None else perf_counter()) - started
            ) * 1000
            if not (
                scope["method"] in ("GET", "HEAD")
                and scope["path"] in ("/", "/healthz")
                and status < 400
            ):
                target = scope.get("raw_path", scope["path"].encode()).decode(
                    "ascii", errors="backslashreplace"
                )
                if scope.get("query_string"):
                    target += "?" + scope["query_string"].decode(
                        "ascii", errors="backslashreplace"
                    )
                device_id = next(
                    (
                        value.decode("latin-1")
                        for name, value in scope["headers"]
                        if name.lower() == b"x-weather-device-id"
                    ),
                    None,
                )
                log.info(
                    "%s %r status=%s duration_ms=%.1f device_id=%r",
                    scope["method"],
                    target,
                    status,
                    elapsed_ms,
                    device_id,
                )
