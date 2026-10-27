"""Local web UI: paste people, watch results come in."""
from __future__ import annotations

import csv
import io
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

from .engine import Engine
from .inputs import parse_text

STATIC = Path(__file__).parent / "static"

CSV_COLUMNS = ["input", "name", "profile_url", "status", "open_to_work_roles", "signals",
               "headline", "note", "checked_at", "from_cache"]


def export_rows(items: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    for it in items:
        w.writerow([
            it["raw"], it["profile_name"] or it["query_name"], it["url"], it["status"], it["roles"],
            "; ".join(s["evidence"] for s in it["signals"]), it["headline"], it["note"],
            datetime.fromtimestamp(it["checked_at"]).isoformat(timespec="seconds") if it["checked_at"] else "",
            "yes" if it["from_cache"] else "",
        ])
    return buf.getvalue()


def create_app(engine: Engine) -> Flask:
    app = Flask(__name__, static_folder=None)
    store = engine.store

    @app.get("/")
    def index():
        return send_from_directory(STATIC, "index.html")

    @app.get("/api/status")
    def status():
        return jsonify(engine.status())

    @app.get("/api/batches")
    def batches():
        return jsonify(store.batches())

    @app.get("/api/items")
    def items():
        return jsonify(store.items(request.args.get("batch") or None))

    @app.post("/api/check")
    def check():
        body = request.get_json(force=True)
        reqs, rejected = parse_text(body.get("text", ""))
        if not reqs:
            return jsonify({"error": "No people found in the input.", "rejected": rejected}), 400
        batch = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        force = bool(body.get("force"))
        for r in reqs:
            item_id = store.add(batch, r)
            if force:
                store.update(item_id, note="force")
            engine.enqueue(item_id)
        return jsonify({"batch": batch, "count": len(reqs), "rejected": rejected})

    @app.post("/api/items/<int:item_id>/pick")
    def pick(item_id: int):
        slug = (request.get_json(force=True).get("slug") or "").strip().lower()
        if not slug:
            return jsonify({"error": "slug required"}), 400
        store.update(item_id, slug=slug, status="queued", note="")
        engine.enqueue(item_id)
        return jsonify({"ok": True})

    @app.post("/api/items/<int:item_id>/retry")
    def retry(item_id: int):
        it = store.get(item_id)
        if not it:
            return jsonify({"error": "not found"}), 404
        # a name lookup that never resolved goes back through search
        slug = it["slug"] if it["status"] not in ("not_found", "ambiguous") else ""
        store.update(item_id, slug=slug, status="queued", note="force", from_cache=0)
        engine.enqueue(item_id)
        return jsonify({"ok": True})

    @app.delete("/api/batches/<path:batch>")
    def delete_batch(batch: str):
        store.delete_batch(batch)
        return jsonify({"ok": True})

    @app.post("/api/login")
    def login():
        engine.request_login()
        return jsonify({"ok": True})

    @app.post("/api/pause")
    def pause():
        engine.pause("Paused")
        return jsonify({"ok": True})

    @app.post("/api/resume")
    def resume():
        engine.resume()
        return jsonify({"ok": True})

    @app.get("/api/export.csv")
    def export():
        batch = request.args.get("batch") or None
        data = export_rows(store.items(batch))
        name = f"incraw-{(batch or 'recent').replace(':', '').replace(' ', '_')}.csv"
        return Response("﻿" + data, mimetype="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    return app
