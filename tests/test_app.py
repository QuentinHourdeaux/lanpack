import concurrent.futures
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import COOKIE, create_app


class LANpackTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.config = dict(TESTING=True, SECRET_KEY="s" * 48,
                           ADMIN_PASSWORD="host-password-for-tests-only",
                           DATABASE=str(Path(self.folder.name) / "test.sqlite"),
                           PUBLIC_URL="http://localhost", DISABLE_RATE_LIMITS=True)
        self.app = create_app(self.config)
        self.client = self.app.test_client()

    def state(self, client=None):
        return (client or self.client).get("/api/state").get_json()

    def write(self, path, data=None, method="POST", client=None, **kwargs):
        client = client or self.client
        csrf = self.state(client)["csrf"]
        headers = {"Origin": "http://localhost", "X-CSRF-Token": csrf}
        headers.update(kwargs.pop("headers", {}))
        return client.open(path, method=method, json=data if data is not None else {}, headers=headers, **kwargs)

    def player(self, code="123456789", **kwargs):
        return dict(name="Alex", nickname="PixelPilot", steam_code=code, **kwargs)

    def register(self, client=None, code="123456789"):
        response = self.write("/api/players", self.player(code), client=client)
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["id"]

    def login(self, client=None):
        response = self.write("/api/admin/login", {"password": self.config["ADMIN_PASSWORD"]}, client=client)
        self.assertEqual(response.status_code, 200)

    def test_register_edit_and_private_token(self):
        player_id = self.register()
        state = self.state()
        self.assertEqual(state["me"]["id"], player_id)
        self.assertEqual(len(state["players"]), 1)
        self.assertNotIn("edit_hash", json.dumps(state))
        cookie = self.client.get_cookie(COOKIE)
        self.assertTrue(cookie.http_only)
        self.assertEqual(cookie.same_site, "Strict")
        with sqlite3.connect(self.config["DATABASE"]) as db:
            stored = db.execute("SELECT edit_hash FROM players").fetchone()[0]
        self.assertEqual(stored, hashlib.sha256(cookie.value.encode()).hexdigest())
        response = self.write("/api/players/me", dict(name="A", nickname="NewNick", steam_code="234567890"), "PATCH")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.state()["me"]["nickname"], "NewNick")

    def test_other_browser_cannot_edit_delete_or_export(self):
        player_id = self.register()
        stranger = self.app.test_client()
        self.assertIsNone(self.state(stranger)["me"])
        for path, method in (("/api/players/me", "PATCH"), ("/api/players/me", "DELETE"),
                             (f"/api/admin/players/{player_id}", "PATCH"),
                             (f"/api/admin/players/{player_id}", "DELETE")):
            self.assertEqual(self.write(path, self.player(), method, stranger).status_code, 403)
        self.assertEqual(stranger.get("/api/admin/export").status_code, 403)
        self.assertEqual(len(self.state()["players"]), 1)

    def test_invalid_input_and_duplicate_codes(self):
        for code in ("", "0", "000", "12abc", "1" * 21, 123, None, "１２３"):
            self.assertEqual(self.write("/api/players", self.player(code)).status_code, 400)
        for data in ({}, [], {"name": " ", "nickname": "ok", "steam_code": "123"},
                     {"name": "x" * 41, "nickname": "ok", "steam_code": "123"}):
            self.assertEqual(self.write("/api/players", data).status_code, 400)
        self.register(code="00123456")
        stranger = self.app.test_client()
        self.assertEqual(self.write("/api/players", self.player("123456"), client=stranger).status_code, 409)
        self.assertEqual(self.write("/api/players", self.player("987654")).status_code, 409)
        self.register(stranger, "234567")  # Same name and nickname are allowed.
        self.assertEqual(len(self.state()["players"]), 2)

    def test_csrf_host_origin_and_request_size(self):
        csrf = self.state()["csrf"]
        for headers in ({}, {"Origin": "http://localhost"},
                        {"Origin": "http://evil.test", "X-CSRF-Token": csrf},
                        {"Origin": "null", "X-CSRF-Token": csrf},
                        {"Origin": "http://localhost", "X-CSRF-Token": "wrong"}):
            self.assertEqual(self.client.post("/api/players", json=self.player(), headers=headers).status_code, 403)
        self.assertEqual(self.client.get("/api/state", headers={"Host": "evil.test"}).status_code, 400)
        self.assertEqual(self.write("/api/players", {"name": "a" * 5000}).status_code, 413)
        response = self.client.get("/")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_organizer_controls_and_logout(self):
        player_id = self.register()
        admin = self.app.test_client()
        self.assertEqual(self.write("/api/admin/login", {"password": "incorrect"}, client=admin).status_code, 401)
        self.login(admin)
        response = self.write(f"/api/admin/players/{player_id}", self.player("345678"), "PATCH", admin)
        self.assertEqual(response.status_code, 200)
        exported = admin.get("/api/admin/export")
        self.assertEqual(exported.status_code, 200)
        self.assertIn("attachment", exported.headers["Content-Disposition"])
        self.assertEqual(exported.get_json()["players"][0]["steam_code"], "345678")
        self.assertNotIn("edit_hash", exported.get_data(as_text=True))
        self.assertNotIn(self.config["ADMIN_PASSWORD"], exported.get_data(as_text=True))
        self.assertEqual(self.write(f"/api/admin/players/{player_id}", method="DELETE", client=admin).status_code, 200)
        self.assertEqual(self.write("/api/admin/logout", client=admin).status_code, 200)
        self.assertEqual(admin.get("/api/admin/export").status_code, 403)
        self.assertEqual(self.state()["players"], [])

    def test_restart_keeps_entries_and_edit_access(self):
        self.register()
        cookie = self.client.get_cookie(COOKIE).value
        restarted = create_app(self.config).test_client()
        restarted.set_cookie(COOKIE, cookie)
        self.assertEqual(self.state(restarted)["me"]["nickname"], "PixelPilot")
        self.assertEqual(self.write("/api/players/me", self.player("4321"), "PATCH", restarted).status_code, 200)

    def test_simultaneous_registrations_and_unique_constraint(self):
        self.app.config["DISABLE_RATE_LIMITS"] = False
        def register(code):
            client = self.app.test_client()
            return self.write("/api/players", self.player(code), client=client).status_code
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(register, [str(100000 + i) for i in range(27)]))
        self.assertEqual(results, [201] * 27)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            duplicates = list(pool.map(register, ["999999"] * 8))
        self.assertEqual(duplicates.count(201), 1)
        self.assertEqual(duplicates.count(409), 7)
        self.assertEqual(len(self.state()["players"]), 28)  # Expected count is not a hard cap.

    def test_html_is_data_and_database_queries_are_parameterized(self):
        name = "<img src=x onerror=alert(1)>"
        nickname = "Robert'); DROP TABLE players;--"
        response = self.write("/api/players", dict(name=name, nickname=nickname, steam_code="234567"))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.state()["players"][0]["name"], name)
        self.assertNotIn(name, self.client.get("/").get_data(as_text=True))

    def test_delete_own_entry_clears_edit_cookie(self):
        self.register()
        self.assertEqual(self.write("/api/players/me", method="DELETE").status_code, 200)
        self.assertIsNone(self.client.get_cookie(COOKIE))
        self.assertIsNone(self.state()["me"])

    def test_qr_and_health(self):
        self.assertEqual(self.client.get("/api/health").get_json(), {"status": "ok"})
        qr = self.client.get("/join.svg")
        self.assertEqual(qr.status_code, 200)
        self.assertEqual(qr.mimetype, "image/svg+xml")
        self.assertIn(b"<svg", qr.data)

    def test_login_rate_limit(self):
        self.app.config["DISABLE_RATE_LIMITS"] = False
        for _ in range(5):
            self.assertEqual(self.write("/api/admin/login", {"password": "wrong"}).status_code, 401)
        self.assertEqual(self.write("/api/admin/login", {"password": "wrong"}).status_code, 429)

    def test_missing_secrets_fail_closed(self):
        with self.assertRaises(RuntimeError):
            create_app({**self.config, "SECRET_KEY": "short"})


if __name__ == "__main__":
    unittest.main()
