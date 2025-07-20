from fastapi import APIRouter, HTTPException, Response
from playwright.async_api import async_playwright
import asyncio

router = APIRouter(prefix="/api")


@router.get("/screenshot")
async def take_screenshot(
    width: int, height: int, lat: float, long: float, api_key: str
):
    try:
        full_url = (
            f"http://localhost:8000/weather?api_key={api_key}&lat={lat}&lon={long}"
        )

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.set_viewport_size({"width": width, "height": height})
            await page.goto(full_url)
            await page.wait_for_selector("text=Loading...", timeout=10000)
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(5)
            screenshot = await page.screenshot()
            await browser.close()
            return Response(screenshot, media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
