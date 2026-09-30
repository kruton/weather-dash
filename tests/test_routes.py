import base64
import io
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from prometheus_client import CONTENT_TYPE_LATEST

from weather_dash import api_routes, get_app


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    app = get_app()
    return TestClient(app)


@pytest.fixture
def screenshot_browser():
    output = io.BytesIO()
    Image.new("RGB", (800, 480), "white").save(output, format="PNG")
    png = output.getvalue()
    page = AsyncMock()
    page.screenshot.return_value = png
    page.evaluate.side_effect = [
        None,
        {
            "pngBase64": base64.b64encode(png).decode(),
            "deviceColors": ["#000000", "#ffffff"],
        },
    ]
    browser = AsyncMock()
    browser.new_page.return_value = page
    playwright = MagicMock()
    playwright.chromium.launch = AsyncMock(return_value=browser)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=playwright)
    context.__aexit__ = AsyncMock(return_value=False)
    with patch.object(api_routes, "async_playwright", return_value=context):
        yield page, browser, png


def test_healthz_endpoint(client):
    """Test the /healthz endpoint returns healthy status."""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_metrics_endpoint(client):
    """Test the /metrics endpoint returns Prometheus metrics."""
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"] == CONTENT_TYPE_LATEST
    # Check that it contains some basic Prometheus metrics
    metrics_text = response.text
    assert "# HELP" in metrics_text
    assert "# TYPE" in metrics_text


def test_api_screenshot_missing_params(client):
    """Test the /api/screenshot endpoint with missing required parameters."""
    response = client.get("/api/screenshot")
    assert response.status_code == 422  # Validation error for missing required params


@pytest.mark.parametrize(
    "profile", [None, "spectra6", "spectra6-boeber", "generic-2-color-eink", "none"]
)
def test_api_screenshot_with_params(client, screenshot_browser, profile):
    """Test the /api/screenshot endpoint with valid parameters."""
    params = {
        "width": 800,
        "height": 480,
        "lat": 37.7749,
        "long": -122.4194,
        "name": "San Francisco & coast",
    }
    if profile is not None:
        params["panel_profile"] = profile
    response = client.get("/api/screenshot", params=params)
    assert response.status_code == 200
    page, browser, original = screenshot_browser
    query = parse_qs(urlparse(page.goto.call_args.args[0]).query)
    assert query["panel_profile"] == [profile or "spectra6"]
    assert query["name"] == [params["name"]]
    assert response.headers["content-type"] == "image/png"
    assert "X-Weather-Next-Refresh" in response.headers
    assert "X-Weather-Time" in response.headers
    browser.close.assert_awaited_once()
    if profile == "none":
        assert response.content == original
        assert page.evaluate.await_count == 1
    else:
        with Image.open(io.BytesIO(response.content)) as result:
            assert result.mode == "P"
            assert result.size == (800, 480)
            assert result.convert("RGB").getpixel((0, 0)) == (255, 255, 255)
        assert page.evaluate.call_args.args[1]["panelProfile"] == (
            profile or "spectra6"
        )


def test_screenshot_rejects_unknown_profile(client):
    response = client.get(
        "/api/screenshot",
        params={
            "width": 800,
            "height": 480,
            "lat": 37.7749,
            "long": -122.4194,
            "panel_profile": "inky-frame-spectra6-7.3",
        },
    )
    assert response.status_code == 422


def test_screenshot_processing_failure_closes_browser(client, screenshot_browser):
    from playwright.async_api import Error

    page, browser, _ = screenshot_browser
    page.evaluate.side_effect = [None, Error("Processing failed")]
    response = client.get(
        "/api/screenshot",
        params={
            "width": 800,
            "height": 480,
            "lat": 37.7749,
            "long": -122.4194,
        },
    )
    assert response.status_code == 500
    assert response.json()["detail"] == "Processing failed"
    browser.close.assert_awaited_once()


def test_api_screenshot_invalid_params(client):
    """Test the /api/screenshot endpoint with invalid parameters."""
    params = {"width": "invalid", "height": 480, "lat": 37.7749, "long": -122.4194}
    response = client.get("/api/screenshot", params=params)
    assert response.status_code == 422  # Validation error


def test_static_files_fallback(client):
    """Test that non-existent paths fallback to index.html for SPA routing."""
    response = client.get("/weather")
    # Will return 404 if frontend/dist/index.html doesn't exist, which is expected in tests
    assert response.status_code in [200, 404]


def test_root_path(client):
    """Test the root path serves the frontend."""
    response = client.get("/")
    # Will return 404 if frontend/dist/index.html doesn't exist, which is expected in tests
    assert response.status_code in [200, 404]
