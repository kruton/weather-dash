"""Persistent images, single-flight rendering and scheduled cache preparation."""

import asyncio
import hashlib
import io
import json
import logging
import os
from datetime import UTC, datetime, timedelta

from PIL import Image, ImageDraw, ImageFont
from prometheus_client import Counter, Gauge, Histogram

from .fleet import canonical, version
from .schedule import next_refresh, previous_refresh

log = logging.getLogger(__name__)
FAILURES = Counter("weather_dash_prerender_failures", "Image preparation failures")
FAILED = Gauge(
    "weather_dash_prerender_failed_targets",
    "Active image targets whose last preparation failed",
)
DURATION = Histogram(
    "weather_dash_render_duration_seconds",
    "Image rendering duration",
    ["source"],
    buckets=(1, 5, 10, 20, 30, 60, 120),
)
CACHE = Counter(
    "weather_dash_image_cache_requests", "Panel image cache lookups", ["result"]
)
RENDERER_VERSION = "fleet-v1"  # Bump when image-affecting renderer code changes.
LEAD = timedelta(minutes=5)


def target(panel):
    config = panel["config"]
    return {key: config[key] for key in ("lat", "long", "name", "panel_profile")} | {
        "width": panel["width"],
        "height": panel["height"],
        "renderer": RENDERER_VERSION,
    }


def target_key(panel):
    return version(target(panel))


def setup_image(width, height, device_id, admin_url):
    image = Image.new("P", (width, height), 1)
    image.putpalette(bytes([0, 0, 0, 255, 255, 255]) + bytes(762))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=max(12, min(width // 28, 26)))
    # Keep the hostname visible without overflowing narrow displays.
    lines = [
        "Weather panel setup",
        "",
        "Panel ID:",
        device_id,
        "",
        "Configure this panel at:",
    ]
    limit = max(12, width // max(8, font.size // 2) - 4)
    lines += [admin_url[i : i + limit] for i in range(0, len(admin_url), limit)]
    draw.multiline_text((20, 20), "\n".join(lines), fill=0, font=font, spacing=8)
    output = io.BytesIO()
    image.save(output, format="PNG", bits=8)
    return output.getvalue()


class ImageCache:
    def __init__(self, registry, render, now=None):
        self.registry = registry
        self.render = render
        self.now = now or (lambda: datetime.now(UTC))
        self.directory = registry.directory / "images"
        self.directory.mkdir(exist_ok=True)
        self.jobs = {}
        self.errors = {}
        self.semaphore = asyncio.Semaphore(1)
        self.worker = None
        self.queued = set()

    def metadata(self, key):
        try:
            data = json.loads((self.directory / (key + ".json")).read_text())
            if not isinstance(data, dict) or not isinstance(data.get("cycle"), int):
                return None
            if not isinstance(data.get("rendered_at"), int) or not isinstance(
                data.get("sha256"), str
            ):
                return None
            if data.get("file") != f"{key}-{data['cycle']}.png":
                return None
            if not (self.directory / data["file"]).is_file():
                return None
            return data
        except OSError, ValueError, TypeError, KeyError:
            return None

    def status(self, panel):
        if not panel["config"]["configured"]:
            return {"state": "unconfigured"}
        key = target_key(panel)
        metadata = self.metadata(key)
        state = (
            "ready"
            if metadata
            and metadata["cycle"] >= int(previous_refresh(self.now()).timestamp())
            else "pending"
        )
        if key in self.errors:
            state = "failed"
        return {
            "state": state,
            "rendered_at": metadata.get("rendered_at") if metadata else None,
            "error": self.errors.get(key),
        }

    async def get(self, panel):
        cycle = int(previous_refresh(self.now()).timestamp())
        key = target_key(panel)
        metadata = self.metadata(key)
        if metadata and metadata["cycle"] >= cycle:
            image = (self.directory / metadata["file"]).read_bytes()
            if hashlib.sha256(image).hexdigest() == metadata["sha256"]:
                CACHE.labels("hit").inc()
                return image, metadata
            (self.directory / (key + ".json")).unlink(missing_ok=True)
            metadata = None
        CACHE.labels("hit" if metadata and metadata["cycle"] >= cycle else "miss").inc()
        await self.ensure(panel, cycle, "request")
        metadata = self.metadata(key)
        return (self.directory / metadata["file"]).read_bytes(), metadata

    async def ensure(self, panel, cycle, source):
        key = target_key(panel)
        metadata = self.metadata(key)
        if metadata and metadata["cycle"] >= cycle:
            return
        for (job_key, job_cycle), task in self.jobs.items():
            if job_key == key and job_cycle >= cycle:
                return await asyncio.shield(task)
        identity = (key, cycle)
        task = asyncio.create_task(self.prepare(panel, cycle, source))
        self.jobs[identity] = task

        def done(completed):
            self.jobs.pop(identity, None)
            if not completed.cancelled():
                completed.exception()  # Background failures are logged by prepare().

        task.add_done_callback(done)
        return await asyncio.shield(task)

    async def prepare(self, panel, cycle, source):
        key = target_key(panel)
        try:
            async with self.semaphore:
                with DURATION.labels(source).time():
                    values = target(panel)
                    values.pop("renderer")
                    png = await self.render(**values)
                file = f"{key}-{cycle}.png"
                path = self.directory / file
                temporary = path.with_suffix(".tmp")
                temporary.write_bytes(png)
                os.replace(temporary, path)
                metadata = self.metadata(key)
                if metadata is None or cycle >= metadata["cycle"]:
                    data = {
                        "file": file,
                        "cycle": cycle,
                        "rendered_at": int(self.now().timestamp()),
                        "sha256": hashlib.sha256(png).hexdigest(),
                    }
                    path = self.directory / (key + ".json")
                    path.with_suffix(".tmp").write_text(canonical(data))
                    os.replace(path.with_suffix(".tmp"), path)
                    if metadata and metadata["file"] != file:
                        (self.directory / metadata["file"]).unlink(missing_ok=True)
            self.errors.pop(key, None)
            FAILED.set(len(self.errors))
        except Exception as error:
            self.errors[key] = str(error)
            FAILURES.inc()
            FAILED.set(len(self.errors))
            log.exception("Weather image preparation failed (%s)", source)
            raise

    def queue(self, panel):
        task = asyncio.create_task(
            self.ensure(panel, int(previous_refresh(self.now()).timestamp()), "config")
        )
        self.queued.add(task)

        def done(completed):
            self.queued.discard(completed)
            if not completed.cancelled():
                completed.exception()

        task.add_done_callback(done)

    async def tick(self):
        now = self.now()
        upcoming = next_refresh(now)
        cycle = int(
            (upcoming if upcoming - now <= LEAD else previous_refresh(now)).timestamp()
        )
        panels = {
            target_key(panel): panel
            for panel in self.registry.panels()
            if panel["config"]["configured"]
        }
        self.errors = {
            key: error for key, error in self.errors.items() if key in panels
        }
        FAILED.set(len(self.errors))
        await asyncio.gather(
            *(self.ensure(panel, cycle, "scheduled") for panel in panels.values()),
            return_exceptions=True,
        )
        # Remove obsolete configuration images once no render is using their key.
        active = {
            target_key(panel)
            for panel in self.registry.panels()
            if panel["config"]["configured"]
        } | {key for key, _ in self.jobs}
        for path in self.directory.iterdir():
            if path.name.split(".")[0].split("-")[0] not in active:
                path.unlink(missing_ok=True)

    async def run(self):
        while True:
            try:
                await self.tick()
            except Exception:
                FAILURES.inc()
                FAILED.set(max(1, len(self.errors)))
                log.exception("Weather preparation worker failed; retrying")
            await asyncio.sleep(15)

    def start(self):
        self.worker = asyncio.create_task(self.run())

    async def stop(self):
        tasks = (
            ([self.worker] if self.worker else [])
            + list(self.jobs.values())
            + list(self.queued)
        )
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
