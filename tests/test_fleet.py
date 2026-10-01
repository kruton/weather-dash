import asyncio
import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from weather_dash import get_app
from weather_dash.fleet import PanelSettings, Registry, describe, version
from weather_dash.prepared import FAILED, FAILURES, ImageCache, target_key
from weather_dash.schedule import previous_refresh


def png():
    output = io.BytesIO()
    Image.new("RGB", (800, 480), "white").save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def services(tmp_path, monkeypatch):
    monkeypatch.setenv("WEATHER_DATA_DIR", str(tmp_path))
    app = get_app()
    registry, cache = app.state.fleet()
    cache.render = AsyncMock(return_value=png())
    monkeypatch.setattr(cache, "start", lambda: None)
    with TestClient(app) as client:
        yield client, registry, cache


def test_registration_setup_sync_and_server_authority(services):
    client, registry, cache = services
    headers = {"X-Weather-Device-ID": "ABCDEF0123456789"}
    response = client.get("/api/screenshot?width=800&height=480", headers=headers)
    assert response.status_code == 200
    with Image.open(io.BytesIO(response.content)) as image:
        assert image.mode == "P" and image.size == (800, 480)
    initial = json.loads(response.headers["X-Weather-Config"])
    assert not initial["config"]["configured"]
    assert (
        int(response.headers["X-Weather-Next-Refresh"])
        - int(response.headers["X-Weather-Time"])
        == 300
    )
    headers["X-Weather-Config-Version"] = initial["version"]
    response = client.get("/api/screenshot?width=800&height=480", headers=headers)
    assert "X-Weather-Config" not in response.headers
    assert len(registry.panels()) == 1
    response = client.put(
        "/admin/api/panels/abcdef0123456789/config",
        json={"friendly_name": "Office", "lat": 48.86, "long": 2.35, "name": "Paris 🌦"},
    )
    assert response.status_code == 200
    response = client.get(
        "/api/screenshot?width=800&height=480&lat=0&long=0&panel_profile=none",
        headers=headers,
    )
    assert response.status_code == 200
    updated = json.loads(response.headers["X-Weather-Config"])
    assert updated["config"]["name"] == "Paris 🌦"
    assert updated["config"]["lat"] == 48.86
    assert cache.render.call_args.kwargs["panel_profile"] == "spectra6"
    assert response.headers["X-Weather-Image-Time"]
    headers["X-Weather-Config-Version"] = updated["version"]
    response = client.get("/api/screenshot?width=800&height=480", headers=headers)
    assert "X-Weather-Config" not in response.headers
    assert cache.render.call_count == 1
    assert (
        client.get("/admin/api/panels").json()[0]["reported_version"]
        == updated["version"]
    )


def test_registration_race_and_persistence(tmp_path):
    registry = Registry(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: registry.register("ab" * 8, 800, 480, None), range(20)))
    registry.configure("ab" * 8, PanelSettings(lat=10, long=20))
    reloaded = Registry(tmp_path)
    assert len(reloaded.panels()) == 1
    assert reloaded.get("ab" * 8)["config"]["lat"] == 10


def test_57_registration_reconciles_existing_panel(services):
    client, registry, _ = services
    device_id = "cd" * 8
    registry.register(device_id, 800, 480, None)
    response = client.get(
        "/api/screenshot?width=600&height=448",
        headers={"X-Weather-Device-ID": device_id,
                 "X-Weather-Display": "inky-frame-5.7"},
    )
    assert response.status_code == 200
    assert registry.get(device_id)["config"]["display"] == "inky-frame-5.7"
    assert registry.get(device_id)["config"]["panel_profile"] == "acep"
    config = json.loads(response.headers["X-Weather-Config"])["config"]
    assert config["display"] == "inky-frame-5.7"
    assert config["panel_profile"] == "acep"
    assert client.put(f"/admin/api/panels/{device_id}/config", json={
        "display": "inky-frame-5.7", "panel_profile": "acep",
        "lat": 48.86, "long": 2.35,
    }).status_code == 200
    assert client.put(f"/admin/api/panels/{device_id}/config", json={
        "display": "inky-frame-5.7", "panel_profile": "spectra6",
        "lat": 48.86, "long": 2.35,
    }).status_code == 422


def test_e1001_server_profile_and_grayscale_selection(services):
    client, registry, cache = services
    device_id = "ef" * 8
    response = client.get(
        "/api/screenshot?width=800&height=480",
        headers={"X-Weather-Device-ID": device_id,
                 "X-Weather-Display": "reterminal-e1001"},
    )
    assert response.status_code == 200
    config = registry.get(device_id)["config"]
    assert config["display"] == "reterminal-e1001"
    assert config["panel_profile"] == "generic-2-color-eink"
    response = client.put(f"/admin/api/panels/{device_id}/config", json={
        "display": "reterminal-e1001", "panel_profile": "generic-4-grayscale",
        "lat": 48.86, "long": 2.35,
    })
    assert response.status_code == 200
    assert cache.render.call_args.kwargs["panel_profile"] == "generic-4-grayscale"
    assert client.put(f"/admin/api/panels/{device_id}/config", json={
        "display": "reterminal-e1001", "panel_profile": "acep",
        "lat": 48.86, "long": 2.35,
    }).status_code == 422


@pytest.mark.parametrize(
    "settings",
    [
        {"lat": 91, "long": 0},
        {"lat": 0, "long": 181},
        {"lat": "NaN", "long": 0},
        {"lat": 0, "long": 0, "display": "arbitrary"},
        {"lat": 0, "long": 0, "panel_profile": "arbitrary"},
        {"lat": 0, "long": 0, "battery_type": "li-ion", "battery_cells": 3},
    ],
)
def test_reject_settings(services, settings):
    client, registry, _ = services
    registry.register("aa", 800, 480, None)
    assert client.put("/admin/api/panels/aa/config", json=settings).status_code == 422
    assert not registry.get("aa")["config"]["configured"]


def test_bad_headers_and_cross_origin(services):
    client, registry, _ = services
    for headers in (
        {"X-Weather-Device-ID": "../x"},
        {"X-Weather-Device-ID": "aa", "X-Weather-Config-Version": "invalid"},
        {"X-Weather-Device-ID": "aa", "X-Weather-Battery-Voltage": "NaN"},
    ):
        assert (
            client.get(
                "/api/screenshot?width=800&height=480", headers=headers
            ).status_code
            == 422
        )
    registry.register("aa", 800, 480, None)
    assert (
        client.put(
            "/admin/api/panels/aa/config",
            json={"lat": 0, "long": 0},
            headers={"Origin": "https://untrusted.example"},
        ).status_code
        == 403
    )
    assert client.get("/admin/api/panels/no-such-id").status_code == 404


def test_battery_last_known_and_chemistry(services):
    client, registry, cache = services
    headers = {
        "X-Weather-Device-ID": "aa",
        "X-Weather-Battery-Voltage": "3.9",
        "X-Weather-Power-Source": "battery",
    }
    assert (
        client.get("/api/screenshot?width=800&height=480", headers=headers).status_code
        == 200
    )
    panel = registry.configure(
        "aa", PanelSettings(lat=0, long=0, battery_type="li-poly", battery_cells=1)
    )
    assert describe(panel, cache)["battery_percent"] == 75
    headers.update(
        {"X-Weather-Battery-Voltage": "5.0", "X-Weather-Power-Source": "usb"}
    )
    client.get("/api/screenshot?width=800&height=480", headers=headers)
    panel = registry.get("aa")
    assert panel["battery_voltage"] == 3.9 and panel["power_source"] == "usb"
    client.get(
        "/api/screenshot?width=800&height=480", headers={"X-Weather-Device-ID": "aa"}
    )
    assert registry.get("aa")["battery_reported_at"] == panel["battery_reported_at"]
    panel = registry.configure(
        "aa", PanelSettings(lat=0, long=0, battery_type="alkaline", battery_cells=3)
    )
    assert describe(panel, cache)["battery_percent"] == 50
    panel = registry.configure("aa", PanelSettings(lat=0, long=0))
    assert describe(panel, cache)["battery_percent"] is None


def test_cache_schedule_single_flight_and_failure(tmp_path):
    async def run():
        registry = Registry(tmp_path)
        for identifier in ("aa", "bb"):
            registry.register(identifier, 800, 480, None)
            registry.configure(identifier, PanelSettings(lat=1, long=2))
        panel = registry.get("aa")
        clock = [datetime.fromisoformat("2026-09-30T06:54:00-07:00")]
        render = AsyncMock(return_value=png())
        cache = ImageCache(registry, render, lambda: clock[0])
        await cache.tick()  # Startup warming for the current cycle.
        assert render.call_count == 1
        clock[0] += timedelta(minutes=1)
        await cache.tick()  # Prepare 7 am, shared by two panels.
        assert render.call_count == 2
        clock[0] += timedelta(minutes=5)
        await asyncio.gather(*(cache.get(panel) for _ in range(5)))
        assert render.call_count == 2
        # Persisted cache survives process restarts.
        cache = ImageCache(registry, render, lambda: clock[0])
        await cache.get(panel)
        assert render.call_count == 2
        # Next preparation fails; old bytes cannot satisfy the next cycle.
        clock[0] = datetime.fromisoformat("2026-09-30T10:55:00-07:00")
        before = FAILURES._value.get()
        render.side_effect = OSError("Provider offline")
        await cache.tick()
        assert FAILURES._value.get() == before + 1
        assert FAILED._value.get() == 1
        assert cache.status(panel)["state"] == "failed"
        clock[0] += timedelta(minutes=5)
        render.side_effect = None
        await asyncio.gather(*(cache.get(panel) for _ in range(5)))
        assert render.call_count == 4
        assert FAILED._value.get() == 0
        # Configuration changes invalidate the shared render key.
        changed = registry.configure("aa", PanelSettings(lat=3, long=4))
        assert target_key(changed) != target_key(panel)
        await cache.get(changed)
        assert render.call_count == 5
        await cache.stop()

    asyncio.run(run())


def test_render_failure_still_delivers_config(services):
    client, registry, cache = services
    registry.register("aa", 800, 480, None)
    registry.configure("aa", PanelSettings(lat=1, long=2))
    cache.render.side_effect = OSError("Offline")
    response = client.get(
        "/api/screenshot?width=800&height=480", headers={"X-Weather-Device-ID": "aa"}
    )
    assert response.status_code == 503
    assert json.loads(response.headers["X-Weather-Config"])["config"]["configured"]


@pytest.mark.parametrize(
    "instant, expected",
    [
        ("2026-03-08T07:00:00-07:00", "2026-03-08T14:00:00+00:00"),
        ("2026-11-01T06:55:00-08:00", "2026-11-01T02:00:00+00:00"),
    ],
)
def test_previous_cycle_dst(instant, expected):
    assert previous_refresh(datetime.fromisoformat(instant)) == datetime.fromisoformat(
        expected
    )


def test_versions_change_with_battery_but_not_render_key(tmp_path):
    registry = Registry(tmp_path)
    registry.register("aa", 800, 480, None)
    first = registry.configure("aa", PanelSettings(lat=1, long=2))
    second = registry.configure(
        "aa", PanelSettings(lat=1, long=2, battery_type="alkaline")
    )
    assert version(first["config"]) != version(second["config"])
    assert target_key(first) == target_key(second)


def test_corrupt_image_is_rebuilt(tmp_path):
    async def run():
        registry = Registry(tmp_path)
        registry.register("aa", 800, 480, None)
        panel = registry.configure("aa", PanelSettings(lat=1, long=2))
        render = AsyncMock(return_value=png())
        cache = ImageCache(registry, render)
        image, metadata = await cache.get(panel)
        (cache.directory / metadata["file"]).write_bytes(b"interrupted disk write")
        restored, _ = await cache.get(panel)
        assert restored == image
        assert render.call_count == 2
        await cache.stop()

    asyncio.run(run())


def test_config_change_during_preparation_keeps_new_image(tmp_path):
    async def run():
        registry = Registry(tmp_path)
        registry.register("aa", 800, 480, None)
        original = registry.configure("aa", PanelSettings(lat=1, long=2))
        cache = ImageCache(registry, AsyncMock(return_value=png()))
        ensure = cache.ensure
        changed = None

        async def change_during_preparation(panel, cycle, source):
            nonlocal changed
            await ensure(panel, cycle, source)
            changed = registry.configure("aa", PanelSettings(lat=3, long=4))
            await ensure(changed, cycle, "config")

        cache.ensure = change_during_preparation
        await cache.tick()
        assert cache.metadata(target_key(changed)) is not None
        assert cache.metadata(target_key(original)) is None
        await cache.stop()

    asyncio.run(run())
