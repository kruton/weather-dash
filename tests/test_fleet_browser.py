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


def test_fleet_form_cached_image_and_confirmed_deletion(browser_page):
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
    deleted = []

    def api(route):
        if route.request.method == "PUT":
            body = route.request.post_data_json
            saved.append(body)
            panel.update({"config": body | {"configured": True}, "image": {
                "state": "ready", "rendered_at": 1700000000,
                "url": f"/admin/api/panels/{panel['id']}/image",
            }})
            route.fulfill(json=panel)
        elif route.request.method == "DELETE":
            deleted.append(route.request.url)
            if len(deleted) == 1:
                route.fulfill(status=500, json={"detail": "Unable to delete panel"})
            else:
                route.fulfill(json={"deleted": panel["id"]})
        else:
            route.fulfill(json=[] if len(deleted) > 1 else [panel])

    page.route(
        "**/admin", lambda route: route.fulfill(content_type="text/html", body=index)
    )
    page.route("**/admin/api/**", api)
    page.goto(page.url.split("/", 3)[0] + "//" + page.url.split("/")[2] + "/admin")
    page.get_by_role("heading", name="Panel fleet").wait_for()
    page.get_by_text("No cached image", exact=True).wait_for()
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
    link = page.get_by_role("link", name="View cached image")
    assert link.get_attribute("href") == f"/admin/api/panels/{panel['id']}/image"
    assert link.get_attribute("target") == "_blank"
    assert page.get_by_text("Created ").inner_text() != "Created Not reported"

    def cancel(dialog):
        assert dialog.type == "confirm"
        assert "Office (abcdef0123456789)" in dialog.message
        assert "saved settings" in dialog.message
        assert "register again" in dialog.message
        dialog.dismiss()

    page.once("dialog", cancel)
    page.get_by_role("button", name="Delete", exact=True).click()
    assert deleted == []
    assert page.get_by_role("button", name="Configure", exact=True).is_visible()
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Delete", exact=True).click()
    page.get_by_role("alert").filter(has_text="Unable to delete panel").wait_for()
    assert page.get_by_role("button", name="Configure", exact=True).is_visible()
    page.get_by_role("button", name="Configure", exact=True).click()
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Delete", exact=True).click()
    page.get_by_role("status").filter(has_text="Office deleted.").wait_for()
    page.get_by_role("heading", name="Waiting for your first panel").wait_for()
    assert page.get_by_role("heading", name="Configure Office").count() == 0
    assert len(deleted) == 2
    page.unroute("**/admin")
    page.unroute("**/admin/api/**")
