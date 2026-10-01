"""Real Chrome tests; run after pnpm build with EINK_BROWSER_TESTS=1."""

import base64
import io
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from PIL import Image
from playwright.sync_api import sync_playwright

from weather_dash.images import indexed_png

pytestmark = pytest.mark.skipif(
    os.environ.get("EINK_BROWSER_TESTS") != "1",
    reason="Requires built frontend and Chromium",
)


@pytest.fixture(scope="module")
def browser_page():
    directory = Path(__file__).resolve().parents[1] / "frontend" / "dist"
    assert (directory / "index.html").is_file(), (
        "Build the frontend before browser tests"
    )
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(directory))
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(f"http://127.0.0.1:{server.server_port}")
                page.wait_for_function(
                    "typeof window.optimizeWeatherScreenshot === 'function'"
                )
                yield page
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def process(page, image, profile):
    source = io.BytesIO()
    image.save(source, format="PNG")
    result = page.evaluate(
        "request => window.optimizeWeatherScreenshot(request)",
        {
            "pngBase64": base64.b64encode(source.getvalue()).decode(),
            "panelProfile": profile,
        },
    )
    data = indexed_png(
        base64.b64decode(result["pngBase64"]), result["deviceColors"], image.size
    )
    return Image.open(io.BytesIO(data)), result


@pytest.mark.parametrize(
    "profile", ["spectra6", "spectra6-boeber", "acep", "generic-2-color-eink", "generic-4-grayscale"]
)
@pytest.mark.parametrize("color", ["black", "white"])
def test_solid_ink_stays_solid(browser_page, profile, color):
    source = Image.new("RGB", (63, 31), color)
    result, _ = process(browser_page, source, profile)
    assert result.convert("RGB").tobytes() == source.tobytes()


@pytest.mark.parametrize(
    "profile", ["spectra6", "spectra6-boeber", "acep", "generic-2-color-eink", "generic-4-grayscale"]
)
def test_transparency_is_composited_on_white(browser_page, profile):
    source = Image.new("RGBA", (7, 3), (255, 0, 0, 0))
    result, _ = process(browser_page, source, profile)
    assert result.convert("RGB").getcolors() == [(21, (255, 255, 255))]


@pytest.mark.parametrize("profile", ["spectra6", "spectra6-boeber", "acep"])
def test_neutral_text_has_no_colored_speckles(browser_page, profile):
    encoded = browser_page.evaluate("""() => {
        const canvas = document.createElement('canvas');
        canvas.width = 320; canvas.height = 80;
        const context = canvas.getContext('2d');
        context.fillStyle = 'white'; context.fillRect(0, 0, 320, 80);
        context.fillStyle = 'black'; context.font = 'bold 18px Arial';
        context.fillText('San Francisco 68°F', 10, 30);
        context.font = '14px Arial'; context.fillText('Humidity 72% / Wind 9.4 mph', 10, 60);
        return canvas.toDataURL('image/png').split(',')[1];
    }""")
    with Image.open(io.BytesIO(base64.b64decode(encoded))) as source:
        result, _ = process(browser_page, source, profile)
    assert set(result.convert("RGB").get_flattened_data()) == {
        (0, 0, 0),
        (255, 255, 255),
    }


@pytest.mark.parametrize(
    "profile", ["spectra6", "spectra6-boeber", "acep", "generic-2-color-eink", "generic-4-grayscale"]
)
def test_gradients_use_only_native_colors_and_are_deterministic(browser_page, profile):
    source = Image.new("RGB", (63, 31))
    source.putdata(
        [(x * 255 // 62, y * 255 // 30, 128) for y in range(31) for x in range(63)]
    )
    result, metadata = process(browser_page, source, profile)
    repeated, _ = process(browser_page, source, profile)
    assert result.tobytes() == repeated.tobytes()
    colors = set(result.convert("RGB").get_flattened_data())
    palette = {tuple(bytes.fromhex(color[1:])) for color in metadata["deviceColors"]}
    assert colors <= palette
    assert len(palette) == (2 if profile == "generic-2-color-eink" else 4 if profile == "generic-4-grayscale" else 7 if profile == "acep" else 6)
