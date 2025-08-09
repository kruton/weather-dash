from fastapi import APIRouter, HTTPException, Response
from playwright.async_api import async_playwright
import asyncio
from PIL import Image, ImageEnhance
import io

router = APIRouter(prefix="/api")

# fmt: off
#
# From the PicoGraphics code. This shows 'real' colors commented out
# and 'assumed' colors substituted in. That means that if we use the
# RGB values from the palette, it will choose the wrong color when we
# use the real color values. Therefore you need to have it bypass the
# closest color matching and set it to the palette index.
#
# RGB palette[8] = {
#   /*
#   {0x2b, 0x2a, 0x37},
#   {0xdc, 0xcb, 0xba},
#   {0x35, 0x56, 0x33},
#   {0x33, 0x31, 0x47},
#   {0x9c, 0x3b, 0x2e},
#   {0xd3, 0xa9, 0x34},
#   {0xab, 0x58, 0x37},
#   {0xb2, 0x8e, 0x67}
#   */
#   {  0,   0,   0}, // black
#   {255, 255, 255}, // white
#   {  0, 255,   0}, // green
#   {  0,   0, 255}, // blue
#   {255,   0,   0}, // red
#   {255, 255,   0}, // yellow
#   {255, 128,   0}, // orange
#   {220, 180, 200}  // clean / taupe?!
# };

E_INK_PALETTE = [
    0x2b, 0x2a, 0x37,  # Black
    0xdc, 0xcb, 0xba,  # White
    0x35, 0x56, 0x33,  # Green
    0x33, 0x31, 0x47,  # Blue
    0x9c, 0x3b, 0x2e,  # Red
    0xd3, 0xa9, 0x34,  # Yellow
    0xab, 0x58, 0x37,  # Orange
    0xb2, 0x8e, 0x67   # Clean / Taupe
]
# fmt: on


def image_enhance(
    png_data: bytes,
    color: float,
    brightness: float,
    quantize: bool,
    black: int | None,
) -> bytes:
    image = Image.open(io.BytesIO(png_data))

    image = ImageEnhance.Color(image).enhance(color)
    image = ImageEnhance.Brightness(image).enhance(brightness)
    if black is not None:
        image = image.point(lambda p: p - black if p > black else 0)

    if quantize:
        image = image.convert("RGB")
        quantized_image = Image.new("P", image.size)
        quantized_image.putpalette(E_INK_PALETTE)
        image = image.quantize(
            palette=quantized_image, dither=Image.Dither.FLOYDSTEINBERG
        )

    data_arr = io.BytesIO()
    image.save(data_arr, format="PNG")
    return data_arr.getvalue()


@router.get("/screenshot")
async def take_screenshot(
    width: int,
    height: int,
    lat: float,
    long: float,
    name: str | None = None,
    color: float = 1.2,
    brightness: float = 1.0,
    quantize: bool = False,
    black: int | None = None,
):
    try:
        full_url = f"http://localhost:8000/weather?lat={lat}&long={long}"
        if name:
            full_url += f"&name={name}"

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
            page = await browser.new_page()
            await page.set_viewport_size({"width": width, "height": height})
            await page.goto(full_url)
            await page.wait_for_selector("text=Loading...", timeout=10000)
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(5)
            screenshot = await page.screenshot(omit_background=True)
            await browser.close()
            screenshot = await asyncio.to_thread(
                image_enhance, screenshot, color, brightness, quantize, black
            )
            return Response(screenshot, media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
