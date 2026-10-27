"""Runs checks one at a time, politely, on a single background thread.

Playwright's sync API must stay on the thread that started it, so the browser
is owned by the worker thread and everything else talks to it through a queue.
"""
from __future__ import annotations

import os
import queue
import random
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from . import detect, resolve
from .linkedin import Blocked, LinkedIn, NotLoggedIn, Unavailable
from .store import Store

ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass
class Settings:
    data_dir: Path = ROOT / "data"
    profile_dir: Path = ROOT / ".browser-profile"
    delay_min: float = _env("INCRAW_DELAY_MIN", 8)      # seconds between page loads
    delay_max: float = _env("INCRAW_DELAY_MAX", 20)
    daily_cap: int = int(_env("INCRAW_DAILY_CAP", 120))  # page loads per day
    cache_days: float = _env("INCRAW_CACHE_DAYS", 7)     # reuse a result this fresh
    idle_close_s: float = 180                            # close Chrome when idle
    headless: bool = os.environ.get("INCRAW_HEADLESS") == "1"


class Engine:
    def __init__(self, settings: Settings | None = None):
        self.s = settings or Settings()
        self.store = Store(self.s.data_dir / "incraw.db")
        self.li = LinkedIn(self.s.profile_dir, headless=self.s.headless)
        self.state = "idle"     # idle | running | paused | login
        self.message = ""
        self.session = "unknown"  # unknown | logged_in | logged_out
        self.current: int | None = None
        self._q: queue.Queue = queue.Queue()
        self._paused = threading.Event()
        self._last_load = 0.0
        self._last_active = 0.0
        self._thread: threading.Thread | None = None

    # -- public API (any thread) ----------------------------------------
    def start(self):
        if not self._thread:
            self._thread = threading.Thread(target=self._run, daemon=True, name="incraw-worker")
            self._thread.start()
            for item_id in self.store.queued_ids():
                self._q.put(("check", item_id))

    def enqueue(self, item_id: int):
        self._q.put(("check", item_id))

    def request_login(self):
        self._q.put(("login", None))

    def pause(self, message: str = "paused"):
        self._paused.set()
        self.state, self.message = "paused", message

    def resume(self):
        self._paused.clear()
        self.state, self.message = "idle", ""
        for item_id in self.store.queued_ids():
            self._q.put(("check", item_id))

    def status(self) -> dict:
        return {
            "state": self.state,
            "message": self.message,
            "session": self.session,
            "current": self.current,
            "loads_today": self.store.loads_today(),
            "daily_cap": self.s.daily_cap,
            "queued": len(self.store.queued_ids()),
            "browser_open": self.li.is_open,
        }

    # -- worker thread ---------------------------------------------------
    def _run(self):
        while True:
            try:
                task, arg = self._q.get(timeout=5)
            except queue.Empty:
                # keep Chrome open while paused: the user may be solving a check in it
                if self.li.is_open and self.state == "idle" and time.time() - self._last_active > self.s.idle_close_s:
                    self.li.close()
                continue
            try:
                if task == "login":
                    self.do_login()
                elif task == "check":
                    if self._paused.is_set():
                        continue  # stays queued in the DB; resume() re-enqueues
                    self.check(arg)
            except Exception as e:  # never let the worker die
                self.message = f"worker error: {e}"
            self._last_active = time.time()

    def do_login(self) -> bool:
        self.state, self.message = "login", "Sign in to LinkedIn in the Chrome window"
        try:
            ok = self.li.login(on_wait=lambda: None)
        except Exception as e:
            ok, self.message = False, f"login failed: {e}"
        self.session = "logged_in" if ok else "logged_out"
        self._last_load = time.time()
        if ok:
            self.state, self.message = "idle", "Logged in"
            if self._paused.is_set():
                self.resume()
        else:
            self.state = "paused" if self._paused.is_set() else "idle"
            self.message = self.message if self.message.startswith("login failed") else "Login not completed"
        return ok

    def _wait_turn(self):
        """Random gap between page loads + the daily budget."""
        if self.store.loads_today() >= self.s.daily_cap:
            raise _CapReached()
        gap = random.uniform(self.s.delay_min, self.s.delay_max)
        wait = self._last_load + gap - time.time()
        if wait > 0:
            time.sleep(wait)
        self.store.count_load()
        self._last_load = time.time()

    def check(self, item_id: int):
        item = self.store.get(item_id)
        if not item or item["status"] != "queued":
            return
        self.current = item_id
        self.state = "running"
        self.store.update(item_id, status="running", note="")
        try:
            self._check(item)
        except _CapReached:
            self.store.update(item_id, status="queued", note="daily limit reached")
            self.pause(f"Daily limit of {self.s.daily_cap} page loads reached; resume tomorrow or raise INCRAW_DAILY_CAP")
        except NotLoggedIn:
            self.session = "logged_out"
            self.store.update(item_id, status="queued", note="waiting for login")
            self.pause("Not logged in to LinkedIn: click Log in")
        except Blocked as e:
            self.store.update(item_id, status="queued", note=str(e))
            self.pause(f"{e}: solve it in the Chrome window, then Resume")
        except Exception as e:
            self.store.update(item_id, status="error", note=str(e)[:300], checked_at=time.time())
        finally:
            self.current = None
            if self.state == "running":
                self.state = "idle"

    def _check(self, item: dict):
        item_id = item["id"]
        slug = item["slug"]
        if not self.li.logged_in():
            raise NotLoggedIn("not logged in")

        if not slug:  # name -> profile
            self._wait_turn()
            raw = self.li.search_people(item["query_name"], item["query_company"])
            if not raw and item["query_company"]:
                self._wait_turn()
                raw = self.li.search_people(item["query_name"])
            self.session = "logged_in"
            cands = resolve.rank(item["query_name"], item["query_company"], raw)
            pick = resolve.choose(cands)
            top = [c.as_dict() for c in cands[:6]]
            if not cands:
                self.store.update(item_id, status="not_found", candidates=[], checked_at=time.time(),
                                  note="no matching people in search")
                return
            if not pick:
                self.store.update(item_id, status="ambiguous", candidates=top, checked_at=time.time(),
                                  note="several possible matches, pick one")
                return
            slug = pick.slug
            self.store.update(item_id, slug=slug, candidates=top)

        cached = None if item["note"] == "force" else self.store.cached(slug, self.s.cache_days)
        if cached:
            self.store.update(
                item_id, slug=slug, status=cached["status"], profile_name=cached["profile_name"],
                headline=cached["headline"], roles=cached["roles"], signals=cached["signals"],
                from_cache=1, checked_at=cached["checked_at"], note="",
            )
            return

        self._wait_turn()
        try:
            snap = self.li.profile(slug)
        except Unavailable as e:
            self.store.update(item_id, status="unavailable", note=str(e), checked_at=time.time())
            return
        self.session = "logged_in"
        d = detect.detect(snap)
        self.store.update(
            item_id, slug=snap.get("slug") or slug, status=d.status, profile_name=snap.get("name", ""),
            headline=snap.get("headline", ""), roles=d.roles, signals=[s.as_dict() for s in d.signals],
            from_cache=0, checked_at=time.time(), note="",
        )


class _CapReached(Exception):
    pass
