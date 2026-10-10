"""LANpack: a small, self-hosted toolkit for a room full of players."""

import hashlib
import io
import os
import re
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import qrcode
import qrcode.image.svg
from flask import Flask, g, jsonify, make_response, render_template, request, session
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

PUBLIC_FIELDS = "id, name, nickname, steam_code, created_at, updated_at"
COOKIE = "lanpack_edit"


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("LANPACK_SECRET_KEY", ""),
        ADMIN_PASSWORD=os.environ.get("LANPACK_ADMIN_PASSWORD", ""),
        DATABASE=os.environ.get("LANPACK_DB", "data/lanpack.sqlite"),
        PUBLIC_URL=os.environ.get("LANPACK_PUBLIC_URL", "http://127.0.0.1:8080"),
        EXPECTED_PLAYERS=int(os.environ.get("LANPACK_EXPECTED_PLAYERS", "27")),
        MAX_CONTENT_LENGTH=4096,
        SESSION_COOKIE_NAME="lanpack_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        PERMANENT_SESSION_LIFETIME=8 * 60 * 60,
    )
    if config:
        app.config.update(config)
    if len(app.config["SECRET_KEY"]) < 32 or len(app.config["ADMIN_PASSWORD"]) < 16:
        raise RuntimeError("Run ./lanpack setup to generate strong local secrets first.")
    public = urlsplit(app.config["PUBLIC_URL"])
    if (public.scheme not in ("http", "https") or not public.hostname
            or public.username or public.password or public.query or public.fragment
            or public.path not in ("", "/")):
        raise RuntimeError("LANPACK_PUBLIC_URL must be an http(s) origin, without a path.")
    app.config["PUBLIC_URL"] = f"{public.scheme}://{public.netloc}"
    app.config["TRUSTED_HOSTS"] = ["localhost", "127.0.0.1", public.hostname]
    app.config["SESSION_COOKIE_SECURE"] = public.scheme == "https"
    admin_hash = generate_password_hash(app.config.pop("ADMIN_PASSWORD"))
    # No credentials are stored in the participant database or public responses.
    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(app.config["DATABASE"]) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""CREATE TABLE IF NOT EXISTS players (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, nickname TEXT NOT NULL,
            steam_code TEXT NOT NULL UNIQUE, edit_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
    attempts = defaultdict(deque)
    rate_lock = threading.Lock()

    def database():
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DATABASE"], timeout=10)
            g.db.row_factory = sqlite3.Row
        return g.db

    @app.teardown_appcontext
    def close_db(_error):
        if "db" in g:
            g.db.close()

    def error(message, status=400):
        return jsonify(error=message), status

    def rate_limit(bucket, maximum, period=60):
        if app.config.get("DISABLE_RATE_LIMITS"):
            return False
        now = time.monotonic()
        with rate_lock:
            # Bound memory and discard inactive sources. No forwarded IPs are trusted.
            for key in list(attempts):
                if not attempts[key] or attempts[key][-1] <= now - period:
                    del attempts[key]
            key = (bucket, request.remote_addr)
            if len(attempts) >= 4096 and key not in attempts:
                return True
            queue = attempts[key]
            while queue and queue[0] <= now - period:
                queue.popleft()
            if len(queue) >= maximum:
                return True
            queue.append(now)
        return False

    def mine():
        token = request.cookies.get(COOKIE, "")
        if not token or len(token) > 128:
            return None
        return database().execute(
            f"SELECT {PUBLIC_FIELDS} FROM players WHERE edit_hash = ?",
            (hashlib.sha256(token.encode()).hexdigest(),),
        ).fetchone()

    @app.before_request
    def protect_request():
        # Force trusted-host validation even for endpoints that never read request.host.
        _ = request.host
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get("Origin") != request.host_url.rstrip("/"):
                return error("This request must come from this LANpack page. Refresh and try again.", 403)
            csrf = request.headers.get("X-CSRF-Token", "")
            expected = session.get("csrf", "")
            if not expected or not secrets.compare_digest(csrf, expected):
                return error("Your session expired. Refresh the page and try again.", 403)
            if not request.is_json:
                return error("Send JSON data.", 415)
            if rate_limit("write", 120):
                return error("Too many changes. Wait a minute and try again.", 429)
        if request.path.startswith("/api/admin/") and request.path != "/api/admin/login":
            if not session.get("organizer"):
                return error("Organizer access required.", 403)

    @app.after_request
    def security_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'self'; style-src 'self'; "
            "img-src 'self'; connect-src 'self'; base-uri 'none'; "
            "form-action 'self'; frame-ancestors 'none'"
        )
        return response

    @app.errorhandler(HTTPException)
    def http_error(exc):
        messages = {400: "Invalid request.", 404: "That entry was not found.",
                    405: "That action is not supported.", 413: "That request is too large."}
        return error(messages.get(exc.code, exc.description), exc.code)

    def payload():
        data = request.get_json()
        if not isinstance(data, dict):
            raise ValueError("Enter your name, nickname and Steam friend code.")
        result = {}
        for key, label in (("name", "First name"), ("nickname", "Nickname")):
            value = data.get(key)
            if not isinstance(value, str):
                raise ValueError(f"{label} is required.")
            value = " ".join(value.split())
            if not 1 <= len(value) <= 40 or any(ord(c) < 32 for c in value):
                raise ValueError(f"{label} must contain 1–40 characters.")
            result[key] = value
        code = data.get("steam_code")
        # Conservative input bound only, not Steam account verification. Do not
        # infer a profile or promise that a numeric string belongs to an account.
        if not isinstance(code, str) or not re.fullmatch(r"[0-9]{1,20}", code.strip()):
            raise ValueError("Paste the numeric friend code from Steam → Add a Friend (up to 20 digits).")
        code = code.strip().lstrip("0") or "0"
        if code == "0":
            raise ValueError("Paste your friend code from Steam → Add a Friend.")
        result["steam_code"] = code
        return result

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/health")
    def health():
        database().execute("SELECT 1")
        return jsonify(status="ok")

    @app.get("/api/state")
    def state():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        players = [dict(row) for row in database().execute(
            f"SELECT {PUBLIC_FIELDS} FROM players ORDER BY nickname COLLATE NOCASE, id"
        )]
        own = mine()
        return jsonify(players=players, me=dict(own) if own else None,
                       csrf=session["csrf"], organizer=bool(session.get("organizer")),
                       join_url=app.config["PUBLIC_URL"], expected=app.config["EXPECTED_PLAYERS"])

    @app.get("/join.svg")
    def join_qr():
        qr = qrcode.make(app.config["PUBLIC_URL"], image_factory=qrcode.image.svg.SvgPathImage,
                         box_size=8, border=3)
        buffer = io.BytesIO()
        qr.save(buffer)
        return app.response_class(buffer.getvalue(), mimetype="image/svg+xml")

    @app.post("/api/players")
    def register():
        if mine():
            return error("You already have an entry. Use Edit my details.", 409)
        # Docker Desktop or venue NAT may present the whole party as one IP.
        if rate_limit("register", 60):
            return error("Too many registrations from this device. Try again in a minute.", 429)
        try:
            data = payload()
        except ValueError as exc:
            return error(str(exc))
        token = secrets.token_urlsafe(32)
        player_id = secrets.token_hex(12)
        now = datetime.now(timezone.utc).isoformat()
        try:
            database().execute(
                "INSERT INTO players VALUES (?, ?, ?, ?, ?, ?, ?)",
                (player_id, data["name"], data["nickname"], data["steam_code"],
                 hashlib.sha256(token.encode()).hexdigest(), now, now),
            )
            database().commit()
        except sqlite3.IntegrityError:
            database().rollback()
            return error("That Steam code is already registered. Use the original browser to edit it, or ask the organizer.", 409)
        response = make_response(jsonify(id=player_id), 201)
        response.set_cookie(COOKIE, token, max_age=30 * 24 * 3600, httponly=True,
                            samesite="Strict", secure=app.config["SESSION_COOKIE_SECURE"])
        return response

    def edit_player(player_id):
        try:
            data = payload()
        except ValueError as exc:
            return error(str(exc))
        try:
            result = database().execute(
                "UPDATE players SET name=?, nickname=?, steam_code=?, updated_at=? WHERE id=?",
                (data["name"], data["nickname"], data["steam_code"],
                 datetime.now(timezone.utc).isoformat(), player_id),
            )
            database().commit()
        except sqlite3.IntegrityError:
            database().rollback()
            return error("That Steam code is already registered to another player.", 409)
        if not result.rowcount:
            return error("That entry no longer exists. Refresh the page.", 404)
        return jsonify(ok=True)

    @app.patch("/api/players/me")
    def update_me():
        own = mine()
        if not own:
            return error("No editable entry in this browser. Ask the organizer for help.", 403)
        return edit_player(own["id"])

    @app.delete("/api/players/me")
    def delete_me():
        own = mine()
        if not own:
            return error("No editable entry in this browser.", 403)
        database().execute("DELETE FROM players WHERE id=?", (own["id"],))
        database().commit()
        response = jsonify(ok=True)
        response.delete_cookie(COOKIE, httponly=True, samesite="Strict")
        return response

    @app.post("/api/admin/login")
    def login():
        if rate_limit("login", 5):
            return error("Too many sign-in attempts. Wait a minute.", 429)
        data = request.get_json()
        password = data.get("password") if isinstance(data, dict) else None
        if not isinstance(password, str) or not check_password_hash(admin_hash, password):
            return error("Incorrect organizer password.", 401)
        session.clear()
        session["csrf"] = secrets.token_urlsafe(32)
        session["organizer"] = True
        session.permanent = True
        return jsonify(ok=True, csrf=session["csrf"])

    @app.post("/api/admin/logout")
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.patch("/api/admin/players/<player_id>")
    def admin_edit(player_id):
        return edit_player(player_id)

    @app.delete("/api/admin/players/<player_id>")
    def admin_delete(player_id):
        result = database().execute("DELETE FROM players WHERE id=?", (player_id,))
        database().commit()
        if not result.rowcount:
            return error("That entry no longer exists.", 404)
        return jsonify(ok=True)

    @app.get("/api/admin/export")
    def export():
        # JSON avoids spreadsheet formula injection and excludes all edit tokens.
        players = [dict(row) for row in database().execute(f"SELECT {PUBLIC_FIELDS} FROM players")]
        response = jsonify(format="lanpack-directory-v1", exported_at=datetime.now(timezone.utc).isoformat(),
                           players=players)
        response.headers["Content-Disposition"] = 'attachment; filename="lanpack-directory.json"'
        return response

    return app


if __name__ == "__main__":
    from waitress import serve
    serve(create_app(), host="0.0.0.0", port=8080, threads=8,
          max_request_body_size=4096, clear_untrusted_proxy_headers=True)
