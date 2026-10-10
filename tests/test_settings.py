import sqlite3
import unittest

from app import create_app
import test_app


class SettingsTests(unittest.TestCase):
    setUp = test_app.LANpackTests.setUp
    state = test_app.LANpackTests.state
    write = test_app.LANpackTests.write
    player = test_app.LANpackTests.player
    register = test_app.LANpackTests.register
    login = test_app.LANpackTests.login

    def test_default_edit_and_persistence(self):
        self.assertEqual(self.state()["expected"], 25)
        self.login()
        self.assertEqual(self.write("/api/admin/settings", {"expected_players": 18}, "PATCH").status_code, 200)
        other = self.app.test_client()
        self.assertEqual(self.state(other)["expected"], 18)
        restarted = create_app({**self.config, "EXPECTED_PLAYERS": 99}).test_client()
        self.assertEqual(self.state(restarted)["expected"], 18)

    def test_only_organizers_can_change_valid_headcount(self):
        self.assertEqual(self.write("/api/admin/settings", {"expected_players": 20}, "PATCH").status_code, 403)
        self.login()
        for value in (None, True, 0, -1, 1000, 2.5, "20"):
            self.assertEqual(self.write("/api/admin/settings", {"expected_players": value}, "PATCH").status_code, 400)
        self.assertEqual(self.state()["expected"], 25)
        with sqlite3.connect(self.config["DATABASE"]) as db:
            db.execute("UPDATE organizer SET setup_required=1")
        self.assertEqual(self.write("/api/admin/settings", {"expected_players": 20}, "PATCH").status_code, 403)

    def test_estimate_does_not_cap_or_change_players(self):
        self.register()
        other = self.app.test_client()
        self.register(other, "45678")
        before = self.state()["players"]
        self.login()
        self.assertEqual(self.write("/api/admin/settings", {"expected_players": 1}, "PATCH").status_code, 200)
        self.assertEqual(self.state()["players"], before)
        self.register(self.app.test_client(), "98765")
        self.assertEqual(len(self.state()["players"]), 3)


if __name__ == "__main__":
    unittest.main()
