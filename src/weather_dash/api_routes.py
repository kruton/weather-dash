import asyncio
import base64
import os
import re
from typing import Annotated, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

from .fleet import canonical
from .images import indexed_png, inky_57_frame
from .ota import root_header
from .prepared import setup_image
from .schedule import refresh_headers

router = APIRouter(prefix="/api")


async def render_image(width, height, lat, long, name=None, panel_profile="spectra6"):
    try:
        params = {"lat": lat, "long": long, "panel_profile": panel_profile}
        if name:
            params["name"] = name
        full_url = "http://localhost:8000/weather?" + urlencode(params)

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    # https://peter.sh/experiments/chromium-command-line-switches/
                    "--disable-gpu",  # Disables GPU hardware acceleration. If software renderer is not in place, then the GPU process won't launch.
                    "--disable-gpu-rasterization",  # Disable GPU rasterization, i.e. rasterize on the CPU only. Overrides the kEnableGpuRasterization flag.
                    "--disable-gpu-compositing",  # Prevent the compositor from using its GPU implementation.
                    "--disable-font-subpixel-positioning",  # Force disables font subpixel positioning. This affects the character glyph sharpness, kerning, hinting and layout.
                    "--disable-software-rasterizer",  # Disables the use of a 3D software rasterizer. (Necessary to make --disable-gpu work)
                    "--ppapi-subpixel-rendering-setting=0",  # The enum value of FontRenderParams::subpixel_rendering to be passed to Ppapi processes.
                    "--force-device-scale-factor=1",  # Overrides the device scale factor for the browser UI and the contents.
                    "--force-color-profile=srgb",  # Force all monitors to be treated as though they have the specified color profile.
                    "--disable-lcd-text",  # Disable hinting for LCD screens
                ],
            )
            try:
                page = await browser.new_page(device_scale_factor=1)
                await page.set_viewport_size({"width": width, "height": height})
                await page.goto(full_url)
                await page.wait_for_selector(
                    '[data-weather-ready="true"]', timeout=30000
                )
                await page.evaluate("""async () => {
                    await document.fonts.ready;
                    await Promise.all(Array.from(document.images, image => image.decode()));
                    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
                }""")
                screenshot = await page.screenshot(omit_background=True)
                if panel_profile != "none":
                    processed = await page.evaluate(
                        "request => window.optimizeWeatherScreenshot(request)",
                        {
                            "pngBase64": base64.b64encode(screenshot).decode("ascii"),
                            "panelProfile": panel_profile,
                        },
                    )
                    screenshot = await asyncio.to_thread(
                        indexed_png,
                        base64.b64decode(processed["pngBase64"], validate=True),
                        processed["deviceColors"],
                        (width, height),
                    )
            finally:
                await browser.close()
            return screenshot
    except (PlaywrightError, OSError, ValueError, KeyError, TypeError) as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/screenshot")
async def take_screenshot(
    width: int = Query(ge=1, le=2000),
    height: int = Query(ge=1, le=2000),
    lat: float | None = None,
    long: float | None = None,
    name: str | None = None,
    panel_profile: Literal[
        "spectra6", "spectra6-boeber", "acep", "generic-2-color-eink",
        "generic-4-grayscale", "none"
    ] = "spectra6",
    image_format: Literal["png", "inky-57-raw"] = "png",
    ota_profile: str | None = None,
    request: Request = None,
    device_id: Annotated[str | None, Header(alias="X-Weather-Device-ID")] = None,
    display: Annotated[
        Literal["inky-frame-spectra-7", "inky-frame-5.7", "reterminal-e1001"] | None,
        Header(alias="X-Weather-Display"),
    ] = None,
    config_version: Annotated[
        str | None, Header(alias="X-Weather-Config-Version")
    ] = None,
    battery_voltage: Annotated[
        float | None,
        Header(alias="X-Weather-Battery-Voltage", ge=1, le=6, allow_inf_nan=False),
    ] = None,
    power_source: Annotated[
        Literal["battery", "usb"] | None, Header(alias="X-Weather-Power-Source")
    ] = None,
):
    extra_headers = {}
    if device_id is not None:
        if not re.fullmatch(r"[0-9a-fA-F]{2,64}", device_id) or len(device_id) % 2:
            raise HTTPException(
                422, "Device ID must be a hexadecimal hardware identifier"
            )
        if config_version is not None and not re.fullmatch(
            r"[0-9a-f]{64}", config_version
        ):
            raise HTTPException(422, "Invalid configuration version")
        registry, cache = request.app.state.fleet()
        panel = registry.register(
            device_id.lower(),
            width,
            height,
            config_version,
            battery_voltage,
            power_source,
            display,
        )
        if config_version != panel["config_version"]:
            extra_headers["X-Weather-Config"] = canonical(
                {
                    "schema": 1,
                    "version": panel["config_version"],
                    "config": panel["config"],
                }
            )
        if not panel["config"]["configured"]:
            admin_url = (
                os.environ.get("WEATHER_PUBLIC_URL", str(request.base_url)).rstrip("/")
                + "/admin"
            )
            image = setup_image(width, height, panel["id"], admin_url)
            extra_headers["X-Weather-Setup"] = "1"
        else:
            try:
                image, metadata = await cache.get(panel)
                extra_headers["X-Weather-Image-Time"] = str(metadata["rendered_at"])
            except HTTPException, OSError, ValueError, KeyError, TypeError:
                # Config delivery and OTA discovery must remain possible on a render failure.
                return Response(
                    status_code=503,
                    headers={
                        **refresh_headers(),
                        **root_header(ota_profile),
                        **extra_headers,
                    },
                )
    else:
        if lat is None or long is None:
            raise HTTPException(
                422, "Latitude and longitude are required without a device ID"
            )
        image = await render_image(width, height, lat, long, name, panel_profile)
    if image_format == "inky-57-raw":
        if (width, height) != (600, 448) or (
            device_id is not None and panel["config"]["display"] != "inky-frame-5.7"
        ):
            raise HTTPException(422, "Raw image requires a 5.7-inch Inky Frame")
        try:
            image = inky_57_frame(image)
        except ValueError as error:
            raise HTTPException(500, str(error)) from error
    headers = {**refresh_headers(), **root_header(ota_profile), **extra_headers}
    if extra_headers.get("X-Weather-Setup"):
        headers["X-Weather-Next-Refresh"] = str(int(headers["X-Weather-Time"]) + 300)
    return Response(image, media_type=("application/octet-stream"
                    if image_format == "inky-57-raw" else "image/png"), headers=headers)
