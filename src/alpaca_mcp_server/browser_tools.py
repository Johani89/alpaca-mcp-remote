"""Playwright browser tools for the Alpaca MCP server."""

import base64
import os
from typing import Any, Optional

from .server import mcp

_playwright: Any = None
_browser: Any = None
_page: Any = None


def _headless_enabled() -> bool:
    return os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() not in {"false", "0", "no", "off"}


async def _ensure_page():
    """Start Playwright lazily so missing dependencies produce a clear tool error."""
    global _playwright, _browser, _page

    if _page and not _page.is_closed():
        return _page

    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is not installed. Install the package and run "
            "`python -m playwright install --with-deps chromium`."
        ) from exc

    if _playwright is None:
        _playwright = await async_playwright().start()

    if _browser is None or not _browser.is_connected():
        _browser = await _playwright.chromium.launch(
            headless=_headless_enabled(),
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

    _page = await _browser.new_page()
    return _page


async def _page_summary(page) -> str:
    title = await page.title()
    return f"URL: {page.url}\nTitle: {title}"


@mcp.tool()
async def browser_open(url: str, wait_until: str = "domcontentloaded") -> str:
    """Open a URL in the shared Chromium browser session."""
    try:
        page = await _ensure_page()
        response = await page.goto(url, wait_until=wait_until)
        status = response.status if response else "unknown"
        return f"Opened page.\nStatus: {status}\n{await _page_summary(page)}"
    except Exception as e:
        return f"Error opening browser page: {str(e)}"


@mcp.tool()
async def browser_click(selector: str, timeout_ms: int = 30000) -> str:
    """Click an element by CSS or Playwright selector."""
    try:
        page = await _ensure_page()
        await page.click(selector, timeout=timeout_ms)
        return f"Clicked selector: {selector}\n{await _page_summary(page)}"
    except Exception as e:
        return f"Error clicking selector '{selector}': {str(e)}"


@mcp.tool()
async def browser_click_text(text: str, exact: bool = False, timeout_ms: int = 30000) -> str:
    """Click an element located by visible text."""
    try:
        page = await _ensure_page()
        await page.get_by_text(text, exact=exact).click(timeout=timeout_ms)
        return f"Clicked text: {text}\n{await _page_summary(page)}"
    except Exception as e:
        return f"Error clicking text '{text}': {str(e)}"


@mcp.tool()
async def browser_type(
    selector: str,
    text: str,
    clear_first: bool = True,
    timeout_ms: int = 30000,
) -> str:
    """Type text into an element by CSS or Playwright selector."""
    try:
        page = await _ensure_page()
        locator = page.locator(selector)
        await locator.wait_for(timeout=timeout_ms)
        if clear_first:
            await locator.fill(text, timeout=timeout_ms)
        else:
            await locator.type(text, timeout=timeout_ms)
        return f"Typed into selector: {selector}\nCharacters: {len(text)}\n{await _page_summary(page)}"
    except Exception as e:
        return f"Error typing into selector '{selector}': {str(e)}"


@mcp.tool()
async def browser_press(
    key: str,
    selector: Optional[str] = None,
    timeout_ms: int = 30000,
) -> str:
    """Press a keyboard key, optionally focusing a selector first."""
    try:
        page = await _ensure_page()
        if selector:
            await page.locator(selector).press(key, timeout=timeout_ms)
            target = f"selector: {selector}"
        else:
            await page.keyboard.press(key)
            target = "page"
        return f"Pressed {key} on {target}.\n{await _page_summary(page)}"
    except Exception as e:
        return f"Error pressing key '{key}': {str(e)}"


@mcp.tool()
async def browser_page_text(max_chars: int = 12000) -> str:
    """Return visible page text from the current browser page."""
    try:
        page = await _ensure_page()
        text = await page.locator("body").inner_text(timeout=30000)
        clipped = text[:max_chars]
        suffix = "\n[truncated]" if len(text) > max_chars else ""
        return f"{await _page_summary(page)}\n\n{clipped}{suffix}"
    except Exception as e:
        return f"Error reading page text: {str(e)}"


@mcp.tool()
async def browser_evaluate(script: str) -> str:
    """Evaluate JavaScript in the current browser page."""
    try:
        page = await _ensure_page()
        result = await page.evaluate(script)
        return f"Evaluation result:\n{result}\n{await _page_summary(page)}"
    except Exception as e:
        return f"Error evaluating script: {str(e)}"


@mcp.tool()
async def browser_screenshot(full_page: bool = True) -> str:
    """Return a PNG screenshot as base64-encoded text."""
    try:
        page = await _ensure_page()
        screenshot = await page.screenshot(full_page=full_page, type="png")
        encoded = base64.b64encode(screenshot).decode("ascii")
        return f"{await _page_summary(page)}\nPNG base64:\n{encoded}"
    except Exception as e:
        return f"Error taking screenshot: {str(e)}"


@mcp.tool()
async def browser_close() -> str:
    """Close the shared Chromium browser session."""
    global _playwright, _browser, _page

    try:
        if _page and not _page.is_closed():
            await _page.close()
        if _browser and _browser.is_connected():
            await _browser.close()
        if _playwright:
            await _playwright.stop()
        _page = None
        _browser = None
        _playwright = None
        return "Browser session closed."
    except Exception as e:
        return f"Error closing browser session: {str(e)}"
