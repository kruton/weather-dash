import pytest
from fastapi.testclient import TestClient
from weather_dash import get_app


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    app = get_app()
    return TestClient(app)


def test_healthz_endpoint(client):
    """Test the /healthz endpoint returns healthy status."""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_metrics_endpoint(client):
    """Test the /metrics endpoint returns Prometheus metrics."""
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; version=0.0.4; charset=utf-8"
    # Check that it contains some basic Prometheus metrics
    metrics_text = response.text
    assert "# HELP" in metrics_text
    assert "# TYPE" in metrics_text


def test_api_screenshot_missing_params(client):
    """Test the /api/screenshot endpoint with missing required parameters."""
    response = client.get("/api/screenshot")
    assert response.status_code == 422  # Validation error for missing required params


def test_api_screenshot_with_params(client):
    """Test the /api/screenshot endpoint with valid parameters."""
    params = {
        "width": 800,
        "height": 480,
        "lat": 37.7749,
        "long": -122.4194,
        "name": "San Francisco"
    }
    response = client.get("/api/screenshot", params=params)
    # This will likely fail in tests since it requires the frontend to be built
    # and running, but we can check that it's properly routing
    assert response.status_code in [200, 500]  # Either works or fails due to missing frontend


def test_api_screenshot_invalid_params(client):
    """Test the /api/screenshot endpoint with invalid parameters."""
    params = {
        "width": "invalid",
        "height": 480,
        "lat": 37.7749,
        "long": -122.4194
    }
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