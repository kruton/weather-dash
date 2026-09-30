import asyncio
import base64
from typing import Literal
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Response
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

from .images import indexed_png
from .ota import root_header
from .schedule import refresh_headers

router = APIRouter(prefix="/api")


@router.get("/screenshot")
async def take_screenshot(
    width: int,
    height: int,
    lat: float,
    long: float,
    name: str | None = None,
    panel_profile: Literal[
        "spectra6", "spectra6-boeber", "generic-2-color-eink", "none"
    ] = "spectra6",
    ota_profile: str | None = None,
):
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
            return Response(
                screenshot,
                media_type="image/png",
                headers={**refresh_headers(), **root_header(ota_profile)},
            )
    except (PlaywrightError, OSError, ValueError, KeyError, TypeError) as e:
        raise HTTPException(status_code=500, detail=str(e))
