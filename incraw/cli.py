"""inCraw command line.

    python -m incraw serve            # web UI on http://127.0.0.1:8765
    python -m incraw login            # sign in once in the Chrome window
    python -m incraw check people.txt # batch run without the UI, writes a CSV
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

from .engine import Engine
from .inputs import parse_text

ICONS = {"open": "OPEN TO WORK", "likely": "likely (headline)", "not_detected": "not detected",
         "ambiguous": "ambiguous name", "not_found": "not found", "unavailable": "unavailable",
         "error": "error"}


def cmd_serve(args):
    from .web import create_app

    engine = Engine()
    engine.start()
    url = f"http://127.0.0.1:{args.port}/"
    print(f"inCraw running at {url}  (Ctrl+C to stop)")
    if not args.no_open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    create_app(engine).run(host="127.0.0.1", port=args.port, debug=False, threaded=True)


def cmd_login(args):
    engine = Engine()
    print("A Chrome window is opening. Sign in to LinkedIn there (up to 10 minutes)...")
    ok = engine.do_login()
    engine.li.close()
    print("Logged in. The session is saved in .browser-profile/." if ok else "Login was not completed.")
    return 0 if ok else 1


def cmd_check(args):
    from .web import export_rows

    text = "\n".join(Path(a).read_text(encoding="utf-8-sig") if Path(a).is_file() else a for a in args.inputs)
    reqs, rejected = parse_text(text)
    for r in rejected:
        print(f"  skipped (not a URL or name): {r}")
    if not reqs:
        print("No people to check.")
        return 1

    engine = Engine()
    batch = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ids = []
    for r in reqs:
        item_id = engine.store.add(batch, r)
        if args.force:
            engine.store.update(item_id, note="force")
        ids.append(item_id)

    print(f"Checking {len(ids)} people (pause {engine.s.delay_min:.0f}-{engine.s.delay_max:.0f}s between pages)...")
    try:
        for n, item_id in enumerate(ids, 1):
            engine.check(item_id)
            it = engine.store.get(item_id)
            label = it["profile_name"] or it["raw"]
            extra = f" - {it['roles']}" if it["roles"] else (f" - {it['note']}" if it["note"] else "")
            print(f"[{n}/{len(ids)}] {label}: {ICONS.get(it['status'], it['status'])}{extra}")
            if engine.state == "paused":
                print(f"\nStopped: {engine.message}")
                break
    finally:
        engine.li.close()

    out = Path(args.out or f"data/results-{batch.replace(':', '').replace(' ', '_')}.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("﻿" + export_rows(engine.store.items(batch)), encoding="utf-8")
    print(f"\nSaved {out}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="incraw", description="Check LinkedIn profiles for Open to Work.")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="start the web UI")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-open", action="store_true", help="don't open the browser")
    s.set_defaults(func=cmd_serve)
    l = sub.add_parser("login", help="sign in to LinkedIn once")
    l.set_defaults(func=cmd_login)
    c = sub.add_parser("check", help="check people from files, URLs or names")
    c.add_argument("inputs", nargs="+", help="text/CSV files, profile URLs, or quoted names")
    c.add_argument("--out", help="CSV output path")
    c.add_argument("--force", action="store_true", help="ignore cached results")
    c.set_defaults(func=cmd_check)
    args = p.parse_args(argv)
    sys.exit(args.func(args) or 0)
