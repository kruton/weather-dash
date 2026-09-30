from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from weather_dash import api_routes
from weather_dash.schedule import next_refresh, refresh_headers


@pytest.mark.parametrize(
    "now, expected",
    [
        ("2026-09-30T06:59:00-07:00", "2026-09-30T14:00:00+00:00"),
        ("2026-09-30T07:00:00-07:00", "2026-09-30T18:00:00+00:00"),
        ("2026-09-30T19:01:00-07:00", "2026-10-01T14:00:00+00:00"),
        ("2026-12-31T19:00:00-08:00", "2027-01-01T15:00:00+00:00"),
        ("2026-03-07T19:00:00-08:00", "2026-03-08T14:00:00+00:00"),
        ("2026-10-31T19:00:00-07:00", "2026-11-01T15:00:00+00:00"),
    ],
)
def test_next_refresh(now, expected):
    assert next_refresh(datetime.fromisoformat(now)) == datetime.fromisoformat(expected)


def test_requires_aware_time():
    with pytest.raises(ValueError, match="timezone"):
        next_refresh(datetime(2026, 9, 30))  # noqa: DTZ001 -- test rejects naive time


def test_refresh_headers():
    now = datetime(2026, 9, 30, 22, 0, tzinfo=UTC)
    headers = refresh_headers(now)
    assert int(headers["X-Weather-Time"]) == int(now.timestamp())
    assert int(headers["X-Weather-Next-Refresh"]) == int(
        datetime(2026, 10, 1, 2, 0, tzinfo=UTC).timestamp()
    )
    assert headers["Cache-Control"] == "no-store"


def test_screenshot_returns_schedule_after_rendering():
    import asyncio

    page = AsyncMock()
    page.screenshot.return_value = b"image"
    browser = AsyncMock()
    browser.new_page.return_value = page
    playwright = MagicMock()
    playwright.chromium.launch = AsyncMock(return_value=browser)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=playwright)
    context.__aexit__ = AsyncMock(return_value=False)
    events = []
    page.screenshot.side_effect = lambda **kwargs: events.append("render") or b"image"

    def headers():
        events.append("schedule")
        return refresh_headers(datetime(2026, 9, 30, 22, 0, tzinfo=UTC))

    with (
        patch.object(api_routes, "async_playwright", return_value=context),
        patch.object(api_routes, "indexed_png", return_value=b"png"),
        patch.object(api_routes, "refresh_headers", side_effect=headers),
    ):
        page.evaluate.return_value = {
            "pngBase64": "cG5n",
            "deviceColors": ["#000000", "#ffffff"],
        }
        response = asyncio.run(api_routes.take_screenshot(800, 480, 37.7749, -122.4194))
    assert response.body == b"png"
    assert response.media_type == "image/png"
    assert "X-Weather-Next-Refresh" in response.headers
    assert "X-Weather-Time" in response.headers
    assert events == ["render", "schedule"]
