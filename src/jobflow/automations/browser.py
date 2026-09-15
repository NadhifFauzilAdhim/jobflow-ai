"""Playwright Browser session manager with stealth and cookie persistence."""

import os
import random
import asyncio
import logging
from pathlib import Path
from typing import Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from jobflow.config import settings

logger = logging.getLogger("jobflow.browser")


class BrowserManager:
    def __init__(self, session_name: str = "default"):
        self.session_name = session_name
        self.session_dir = Path(settings.USER_DATA_DIR) / session_name
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.session_dir / "state.json"
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def start(self) -> BrowserContext:
        """Launch browser with persistent storage state and stealth configurations."""
        self.playwright = await async_playwright().start()
        
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-infobars",
            "--disable-extensions",
        ]

        self.browser = await self.playwright.chromium.launch(
            headless=settings.BROWSER_HEADLESS,
            slow_mo=settings.BROWSER_SLOW_MO,
            args=launch_args
        )

        state_path = str(self.state_file) if self.state_file.exists() else None
        
        self.context = await self.browser.new_context(
            storage_state=state_path,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768},
            locale="en-US",
            timezone_id="Asia/Jakarta",
        )

        # Inject stealth scripts to avoid bot detection
        await self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            window.chrome = { runtime: {} };
        """)

        return self.context

    async def get_page(self) -> Page:
        """Get an existing or new page in context."""
        if not self.context:
            await self.start()
        pages = self.context.pages
        return pages[0] if pages else await self.context.new_page()

    async def save_session_state(self):
        """Save cookies and local storage for persistent login."""
        if self.context:
            await self.context.storage_state(path=str(self.state_file))
            logger.info(f"Saved session state to {self.state_file}")

    async def human_delay(self, min_sec: float = 1.0, max_sec: float = 3.0):
        """Sleep with random jitter to mimic natural user behavior."""
        delay = random.uniform(min_sec, max_sec)
        await asyncio.sleep(delay)

    async def close(self):
        """Safely close context and browser."""
        if self.context:
            try:
                await self.save_session_state()
            except Exception:
                pass
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
