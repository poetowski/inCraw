"""The browser side: a real Chrome window on a dedicated, logged-in profile.

Everything LinkedIn-DOM-specific lives here. Extraction is text-based on
purpose (h1, img alt, innerText of the top card) because LinkedIn's class
names change often.
"""
from __future__ import annotations

import random
import time
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import BrowserContext, Page, sync_playwright
from playwright.sync_api import TimeoutError as PWTimeout

from .inputs import profile_url, slug_from_url

LOGIN_URL = "https://www.linkedin.com/login"
FEED_URL = "https://www.linkedin.com/feed/"

EXTRACT_PROFILE_JS = """
() => {
  const main = document.querySelector('main') || document.body;
  const h1 = main.querySelector('h1');
  const top = (h1 && h1.closest('section')) || main;
  let headline = '';
  const hl = top.querySelector('.text-body-medium');
  if (hl) headline = hl.innerText.trim();
  else if (h1) {
    // fallback: first non-empty line after the name in the top card
    const lines = top.innerText.split('\\n').map(s => s.trim()).filter(Boolean);
    const i = lines.indexOf(h1.innerText.trim());
    if (i >= 0 && lines[i + 1]) headline = lines[i + 1];
  }
  return {
    url: location.href,
    name: h1 ? h1.innerText.trim() : '',
    headline,
    imgAlts: [...top.querySelectorAll('img')].map(i => i.alt || '').filter(Boolean).slice(0, 30),
    topText: top.innerText.slice(0, 5000),
  };
}
"""

EXTRACT_SEARCH_JS = """
() => {
  const out = [], seen = new Set();
  for (const a of document.querySelectorAll('main a[href*="/in/"]')) {
    const m = a.href.match(/linkedin\\.com\\/in\\/([^/?#]+)/);
    if (!m) continue;
    const slug = decodeURIComponent(m[1]).toLowerCase();
    if (seen.has(slug)) continue;
    const card = a.closest('li') || a.closest('[data-chameleon-result-urn]') || a.parentElement;
    const text = (card ? card.innerText : a.innerText || '').trim();
    if (!text) continue;
    seen.add(slug);
    out.push({ slug, text: text.slice(0, 800) });
    if (out.length >= 10) break;
  }
  return out;
}
"""


class Blocked(Exception):
    """LinkedIn wants a login, a captcha or a security check."""


class NotLoggedIn(Blocked):
    pass


class Unavailable(Exception):
    """Profile doesn't exist or isn't visible to this account."""


def _blocked_url(url: str) -> str | None:
    u = url.lower()
    if "/checkpoint/" in u or "/captcha" in u:
        return "LinkedIn asked for a security check"
    if "/authwall" in u or "/login" in u or "/uas/" in u or "/signup" in u:
        return "not logged in"
    return None


class LinkedIn:
    def __init__(self, profile_dir: Path, headless: bool = False):
        self.profile_dir = profile_dir
        self.headless = headless
        self._pw = None
        self._ctx: BrowserContext | None = None
        self._page: Page | None = None

    # -- lifecycle -------------------------------------------------------
    @property
    def is_open(self) -> bool:
        return self._ctx is not None

    def open(self) -> Page:
        if self._page and not self._page.is_closed():
            return self._page
        if self._ctx is None:
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            self._pw = sync_playwright().start()
            kwargs = dict(
                user_data_dir=str(self.profile_dir),
                headless=self.headless,
                viewport={"width": 1280, "height": 900},
                locale="en-US",
                args=["--disable-blink-features=AutomationControlled"],
                ignore_default_args=["--enable-automation"],
            )
            try:
                self._ctx = self._pw.chromium.launch_persistent_context(channel="chrome", **kwargs)
            except Exception:
                # no installed Chrome: fall back to Playwright's Chromium
                self._ctx = self._pw.chromium.launch_persistent_context(**kwargs)
            self._ctx.on("close", lambda _: self._forget())
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        return self._page

    def _forget(self):
        self._ctx = None
        self._page = None

    def close(self):
        try:
            if self._ctx:
                self._ctx.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._pw = None
        self._forget()

    # -- session ---------------------------------------------------------
    def login(self, timeout_s: int = 600, on_wait=None) -> bool:
        """Open the login page and wait until the user has signed in by hand."""
        page = self.open()
        page.goto(FEED_URL, wait_until="domcontentloaded")
        if self._on_feed(page):
            return True
        if "/login" not in page.url and "/checkpoint/" not in page.url:
            page.goto(LOGIN_URL, wait_until="domcontentloaded")
        page.bring_to_front()
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if on_wait:
                on_wait()
            if self._on_feed(page):
                return True
            page.wait_for_timeout(1500)
        return False

    @staticmethod
    def _on_feed(page: Page) -> bool:
        return "/feed" in page.url and _blocked_url(page.url) is None

    def logged_in(self) -> bool:
        self.open()
        return any(c["name"] == "li_at" and c["value"] for c in self._ctx.cookies("https://www.linkedin.com"))

    # -- navigation ------------------------------------------------------
    def _goto(self, url: str) -> Page:
        page = self.open()
        # logged-out profile pages don't reliably show Open to Work, so a
        # result from one would be a false "not detected"
        if not self.logged_in():
            raise NotLoggedIn("not logged in")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except PWTimeout:
            pass  # LinkedIn keeps long-polling; the DOM is usually there anyway
        reason = _blocked_url(page.url)
        if reason == "not logged in":
            raise NotLoggedIn(reason)
        if reason:
            raise Blocked(reason)
        return page

    def _act_human(self, page: Page):
        page.wait_for_timeout(random.randint(1200, 2500))
        for _ in range(random.randint(1, 3)):
            page.mouse.wheel(0, random.randint(250, 700))
            page.wait_for_timeout(random.randint(400, 1100))

    def profile(self, slug: str) -> dict:
        page = self._goto(profile_url(slug))
        try:
            page.wait_for_selector("main h1", timeout=20000)
        except PWTimeout:
            reason = _blocked_url(page.url)
            if reason:
                raise Blocked(reason)
            text = (page.inner_text("body") or "")[:3000].lower()
            if "page doesn" in text or "profile is not available" in text or "/404" in page.url:
                raise Unavailable("profile not found or not visible")
            raise Unavailable("profile did not load (no name on page)")
        self._act_human(page)
        snap = page.evaluate(EXTRACT_PROFILE_JS)
        # LinkedIn may redirect a vanity URL to the canonical slug
        snap["slug"] = slug_from_url(snap.get("url", "")) or slug
        return snap

    def search_people(self, name: str, company: str = "") -> list[dict]:
        q = quote(f"{name} {company}".strip())
        page = self._goto(f"https://www.linkedin.com/search/results/people/?keywords={q}")
        try:
            page.wait_for_selector('main a[href*="/in/"]', timeout=15000)
        except PWTimeout:
            return []
        self._act_human(page)
        return page.evaluate(EXTRACT_SEARCH_JS)
