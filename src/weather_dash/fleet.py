"""Persistent panel registry. Administrative access is enforced by the ingress."""

import hashlib
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

DISPLAY = "inky-frame-spectra-7"
PROFILES = ("spectra6", "spectra6-boeber", "generic-2-color-eink", "none")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def version(config):
    return hashlib.sha256(canonical(config).encode()).hexdigest()


def default_config():
    return {
        "configured": False,
        "display": DISPLAY,
        "panel_profile": "spectra6",
        "name": "",
        "lat": None,
        "long": None,
        "battery_type": "unknown",
        "battery_cells": 3,
    }


class PanelSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    friendly_name: str = Field(default="", max_length=120)
    display: Literal["inky-frame-spectra-7"] = DISPLAY
    panel_profile: Literal[
        "spectra6", "spectra6-boeber", "generic-2-color-eink", "none"
    ] = "spectra6"
    name: str = Field(default="", max_length=160)
    lat: float = Field(ge=-90, le=90)
    long: float = Field(ge=-180, le=180)
    battery_type: Literal["unknown", "alkaline", "li-poly", "li-ion"] = "unknown"
    battery_cells: int = Field(default=3, ge=1, le=4)

    @model_validator(mode="after")
    def validate_battery(self):
        if self.battery_type in ("li-poly", "li-ion") and self.battery_cells != 1:
            raise ValueError(
                "The Inky battery connector supports single-cell lithium packs"
            )
        return self


class Registry:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "panels.sqlite3"
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS panels (
                id TEXT PRIMARY KEY, friendly_name TEXT NOT NULL DEFAULT '',
                registered_at INTEGER NOT NULL, last_seen INTEGER NOT NULL,
                width INTEGER NOT NULL, height INTEGER NOT NULL,
                reported_version TEXT, config TEXT NOT NULL)""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(panels)")}
            for column in (
                "battery_voltage REAL",
                "battery_reported_at INTEGER",
                "power_source TEXT",
            ):
                if column.split()[0] not in columns:
                    db.execute("ALTER TABLE panels ADD COLUMN " + column)
            db.execute("PRAGMA user_version=2")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def register(
        self,
        device_id,
        width,
        height,
        reported_version,
        battery_voltage=None,
        power_source=None,
    ):
        now = int(time.time())
        with self.connect() as db:
            db.execute(
                """INSERT INTO panels
                (id, registered_at, last_seen, width, height, reported_version, config)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen,
                width=excluded.width, height=excluded.height,
                reported_version=excluded.reported_version""",
                (
                    device_id,
                    now,
                    now,
                    width,
                    height,
                    reported_version,
                    canonical(default_config()),
                ),
            )
            if battery_voltage is not None and power_source == "battery":
                db.execute(
                    "UPDATE panels SET battery_voltage=?, battery_reported_at=? WHERE id=?",
                    (battery_voltage, now, device_id),
                )
            if power_source is not None:
                db.execute(
                    "UPDATE panels SET power_source=? WHERE id=?",
                    (power_source, device_id),
                )
        return self.get(device_id)

    @staticmethod
    def decode(row):
        panel = dict(row)
        panel["config"] = default_config() | json.loads(panel["config"])
        panel["config_version"] = version(panel["config"])
        return panel

    def get(self, device_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM panels WHERE id=?", (device_id,)).fetchone()
        return self.decode(row) if row else None

    def panels(self):
        with self.connect() as db:
            return [
                self.decode(row)
                for row in db.execute("SELECT * FROM panels ORDER BY registered_at, id")
            ]

    def configure(self, device_id, settings):
        config = settings.model_dump(exclude={"friendly_name"}) | {"configured": True}
        with self.connect() as db:
            result = db.execute(
                "UPDATE panels SET friendly_name=?, config=? WHERE id=?",
                (settings.friendly_name, canonical(config), device_id),
            )
        return self.get(device_id) if result.rowcount else None


router = APIRouter(prefix="/admin/api")


def describe(panel, cache):
    config = panel["config"]
    voltage = panel["battery_voltage"]
    battery_type = config.get("battery_type", "unknown")
    percent = None
    if voltage is not None and battery_type != "unknown":
        # Rough voltage estimate: actual capacity depends on load and cell age.
        empty, full = (1.0, 1.6) if battery_type == "alkaline" else (3.0, 4.2)
        cell_voltage = voltage / config.get("battery_cells", 3)
        percent = round(max(0, min(100, 100 * (cell_voltage - empty) / (full - empty))))
    return panel | {"image": cache.status(panel), "battery_percent": percent}


@router.get("/panels")
async def list_panels(request: Request):
    registry, cache = request.app.state.fleet()
    return [describe(panel, cache) for panel in registry.panels()]


@router.get("/panels/{device_id}")
async def get_panel(device_id: str, request: Request):
    registry, cache = request.app.state.fleet()
    panel = registry.get(device_id)
    if panel is None:
        raise HTTPException(404, "Unknown panel")
    return describe(panel, cache)


@router.put("/panels/{device_id}/config")
async def configure_panel(device_id: str, settings: PanelSettings, request: Request):
    # Browser writes must originate on this host; authentication lives at Envoy.
    origin = request.headers.get("origin")
    public_url = os.environ.get("WEATHER_PUBLIC_URL", str(request.base_url))
    if origin and origin.rstrip("/") != public_url.rstrip("/"):
        raise HTTPException(403, "Cross-origin management request")
    registry, cache = request.app.state.fleet()
    panel = registry.configure(device_id, settings)
    if panel is None:
        raise HTTPException(404, "Unknown panel")
    cache.queue(panel)
    return describe(panel, cache)
