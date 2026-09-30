"""Exercise the fleet form in production Chrome, without weather-provider calls."""

import os
from pathlib import Path

import pytest

from weather_dash.fleet import default_config

pytest_plugins = ["tests.test_eink_browser"]

pytestmark = pytest.mark.skipif(
    os.environ.get("EINK_BROWSER_TESTS") != "1",
    reason="Requires built frontend and Chromium",
)


def test_fleet_form_and_battery_selector(browser_page):
    page = browser_page
    index = Path("frontend/dist/index.html").read_text()
    panel = {
        "id": "abcdef0123456789",
        "friendly_name": "Office",
        "registered_at": 1,
        "last_seen": 1,
        "config": default_config(),
        "config_version": "a" * 64,
        "reported_version": None,
        "width": 800,
        "height": 480,
        "battery_voltage": 3.9,
        "battery_percent": None,
        "battery_reported_at": 1,
        "power_source": "battery",
        "image": {"state": "unconfigured"},
    }
    saved = []

    def api(route):
        if route.request.method == "PUT":
            body = route.request.post_data_json
            saved.append(body)
            route.fulfill(json=panel | {"config": body | {"configured": True}})
        else:
            route.fulfill(json=[panel])

    page.route(
        "**/admin", lambda route: route.fulfill(content_type="text/html", body=index)
    )
    page.route("**/admin/api/**", api)
    page.goto(page.url.split("/", 3)[0] + "//" + page.url.split("/")[2] + "/admin")
    page.get_by_role("heading", name="Panel fleet").wait_for()
    page.get_by_role("button", name="Configure", exact=True).click()
    page.get_by_label("Location name").fill("Paris")
    page.get_by_label("Latitude", exact=True).fill("48.86")
    page.get_by_label("Longitude", exact=True).fill("2.35")
    page.get_by_label("Battery chemistry").select_option("li-poly")
    assert page.get_by_label("Cells in series").input_value() == "1"
    page.get_by_role("button", name="Save settings").click()
    page.get_by_role("status").wait_for()
    assert saved[0]["battery_type"] == "li-poly"
    assert saved[0]["battery_cells"] == 1
    assert saved[0]["lat"] == 48.86
    assert "configured" not in saved[0]
    page.unroute("**/admin")
    page.unroute("**/admin/api/**")
