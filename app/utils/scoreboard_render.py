"""Render scoreboard overlay frames with headless Chromium.

Loads the SPA's ``/scoreboard-render`` page, which renders the same markup and
CSS as the live OBS scoreboard (``/<url>/scoreboard``) but takes its state from
``window.arctosRenderScoreboard(stateJson)`` instead of polling. OBS's browser
source is Chromium (CEF), so the transparent PNGs captured here look like the
live overlay.

Configured by ``ARCTOS_FRONTEND_URL`` (origin serving the SPA) and optionally
``ARCTOS_CHROMIUM_PATH`` (system Chromium; otherwise Playwright's bundled
Chromium from ``uv run playwright install chromium``).
"""

from __future__ import annotations

import json
import logging
import math
import os
from typing import Any

from playwright.sync_api import Error as PlaywrightError, sync_playwright

from app.error_values import Err, Ok, Result
from app.exceptions import ArctosError, ValidationError

logger = logging.getLogger(__name__)

# CSS width the scoreboard is laid out at before scaling to the requested pixel
# width. The container stretches to the viewport (min-width 600px); 800px fits
# long team names plus several set columns without wrapping.
SCOREBOARD_CSS_WIDTH = 800
MIN_OVERLAY_DIMENSION = 32
MAX_OVERLAY_WIDTH = 3840
MAX_OVERLAY_HEIGHT = 2160
RENDER_PAGE_PATH = "/scoreboard-render"
RENDER_TIMEOUT_MS = 15_000

_FRAME_READY_JS = """
sequence => document.querySelector(`[data-render-sequence="${sequence}"]`) !== null
    && Array.from(document.images).every(image => image.complete)
"""
_TWO_ANIMATION_FRAMES_JS = """
() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
"""


def validate_overlay_size(width: int | None, height: int | None) -> Result[tuple[int, int], ValidationError]:
    """Check a requested overlay size in output pixels.

    Returns:
        ``Ok((width, height))``, or ``Err(ValidationError)`` when either is
        missing, non-integer, or outside the supported bounds.
    """
    if width is None or height is None:
        return Err(ValidationError("width and height are required integer query parameters"))
    if not (MIN_OVERLAY_DIMENSION <= width <= MAX_OVERLAY_WIDTH) or not (
        MIN_OVERLAY_DIMENSION <= height <= MAX_OVERLAY_HEIGHT
    ):
        return Err(
            ValidationError(
                f"width must be between {MIN_OVERLAY_DIMENSION} and {MAX_OVERLAY_WIDTH} and height between "
                f"{MIN_OVERLAY_DIMENSION} and {MAX_OVERLAY_HEIGHT}"
            )
        )
    return Ok((width, height))


def render_scoreboard_frames(states: list[dict[str, Any]], width: int, height: int) -> Result[list[bytes], ArctosError]:
    """Screenshot the scoreboard once per state as ``width`` x ``height`` PNGs.

    The page is laid out :data:`SCOREBOARD_CSS_WIDTH` CSS pixels wide and
    scaled with ``device_scale_factor`` so that maps to *width* output pixels.

    Args:
        states: Scoreboard state dicts in the live ``scoreboard-state`` shape.
        width: Output width in pixels (see :func:`validate_overlay_size`).
        height: Output height in pixels.

    Returns:
        ``Ok`` with one PNG (with alpha) per state, or ``Err`` with status 503
        when rendering isn't configured or the browser fails.
    """
    frontend_url = os.environ.get("ARCTOS_FRONTEND_URL", "").strip().rstrip("/")
    if not frontend_url:
        return Err(ArctosError("Scoreboard rendering is not configured on this server", status_code=503))
    chromium_path = os.environ.get("ARCTOS_CHROMIUM_PATH", "").strip() or None

    scale = width / SCOREBOARD_CSS_WIDTH
    css_height = height / scale
    try:
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(executable_path=chromium_path)
            except PlaywrightError:
                logger.exception("scoreboard_render: chromium launch failed chromium_path=%s", chromium_path)
                return Err(ArctosError("Scoreboard renderer is unavailable", status_code=503))
            try:
                page = browser.new_page(
                    viewport={"width": SCOREBOARD_CSS_WIDTH, "height": math.ceil(css_height)},
                    device_scale_factor=scale,
                )
                page.set_default_timeout(RENDER_TIMEOUT_MS)
                page.goto(frontend_url + RENDER_PAGE_PATH)
                page.wait_for_function("() => typeof window.arctosRenderScoreboard === 'function'")
                frames = []
                for state in states:
                    sequence = page.evaluate("state => window.arctosRenderScoreboard(state)", json.dumps(state))
                    page.wait_for_function(_FRAME_READY_JS, arg=sequence)
                    page.evaluate(_TWO_ANIMATION_FRAMES_JS)
                    frames.append(
                        page.screenshot(
                            omit_background=True,
                            clip={"x": 0, "y": 0, "width": SCOREBOARD_CSS_WIDTH, "height": css_height},
                        )
                    )
                return Ok(frames)
            finally:
                browser.close()
    except PlaywrightError:
        logger.exception("scoreboard_render: rendering failed frontend_url=%s", frontend_url)
        return Err(ArctosError("Scoreboard rendering failed", status_code=503))
