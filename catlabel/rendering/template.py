import base64
import os
import threading
from io import BytesIO
from typing import List

from PIL import Image

_browser_lock = threading.Lock()
_playwright_context = None
_browser_instance = None


def _get_browser():
    """Maintains a persistent, thread-safe headless browser instance."""
    global _playwright_context, _browser_instance
    with _browser_lock:
        if _browser_instance is None:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError as exc:
                raise RuntimeError(
                    "Playwright is not installed. Headless API printing is disabled to save space. "
                    "To enable it, please activate the environment and run: "
                    "pip install playwright && playwright install chromium"
                ) from exc
            _playwright_context = sync_playwright().start()
            _browser_instance = _playwright_context.chromium.launch(headless=True)
        return _browser_instance


def _headless_url_candidates() -> List[str]:
    port = os.environ.get("CATLABEL_PORT", "8000")
    return [
        f"http://127.0.0.1:{port}/index.html?mode=headless",
        "http://127.0.0.1:5173/index.html?mode=headless",
    ]


def _decode_browser_image(data_url_or_b64: str) -> Image.Image:
    image_data = data_url_or_b64 or ""
    if "," in image_data:
        image_data = image_data.split(",", 1)[1]
    decoded = base64.b64decode(image_data)
    return Image.open(BytesIO(decoded)).convert("RGB")


def render_via_browser(canvas_state: dict, variables_collection: list, copies: int = 1) -> List[Image.Image]:
    """
    Uses a persistent browser renderer as the source of truth for final print images.
    """
    payload = {
        "canvas_state": canvas_state or {},
        "variables_collection": variables_collection or [{}],
        "copies": copies,
    }

    try:
        browser = _get_browser()
        context = browser.new_context()
        page = context.new_page()

        try:
            last_error = None
            for url in _headless_url_candidates():
                try:
                    page.goto(url, wait_until="networkidle")
                    last_error = None
                    break
                except Exception as exc:
                    last_error = exc

            if last_error is not None:
                raise RuntimeError("Unable to load the headless frontend renderer.") from last_error

            page.evaluate(
                "(payload) => { window.__INJECTED_PAYLOAD__ = payload; }",
                payload,
            )
            page.wait_for_selector("#render-done", timeout=30000, state="attached")
            rendered_images = page.evaluate("window.__RENDERED_IMAGES__ || []")
        finally:
            page.close()
            context.close()
    except Exception as exc:
        error_text = str(exc).lower()
        if "executable doesn't exist" in error_text or "playwright install" in error_text:
            raise RuntimeError(
                "Chromium binaries are missing. To enable API printing, run: "
                "playwright install chromium"
            ) from exc
        raise RuntimeError(f"Headless rendering failed: {exc}") from exc

    images = []
    for data in rendered_images:
        image = _decode_browser_image(data)
        if canvas_state.get("isRotated"):
            image = image.rotate(90, expand=True)
        images.append(image)

    return images


def render_template(template_data: dict, variables: dict, default_font: str = "RobotoCondensed.ttf") -> Image.Image:
    """
    Backwards-compatible wrapper for any remaining code paths that still expect
    a single rendered PIL image from the old API.
    """
    images = render_via_browser(template_data or {}, [variables or {}], 1)
    if images:
        return images[0]

    width = max(1, int((template_data or {}).get("width", 384) or 384))
    height = max(1, int((template_data or {}).get("height", 384) or 384))
    return Image.new("RGB", (width, height), "white")
