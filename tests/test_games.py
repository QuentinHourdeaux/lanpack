import sqlite3
import unittest

from app import create_app
import test_app


class GamesTests(unittest.TestCase):
    setUp = test_app.LANpackTests.setUp
    state = test_app.LANpackTests.state
    write = test_app.LANpackTests.write
    player = test_app.LANpackTests.player
    register = test_app.LANpackTests.register
    login = test_app.LANpackTests.login

    def game(self, **overrides):
        return dict(dict(name="Trackmania", player_count=8, url="https://example.com/game",
                         price="€19.99", cracked=False, genre="Course"), **overrides)

    def add_game(self):
        self.login()
        response = self.write("/api/admin/games", self.game())
        self.assertEqual(response.status_code, 201)
        return response.get_json()["id"]

    def choose(self, game_id, owns=True, wants=False, client=None, **extras):
        return self.write(f"/api/games/{game_id}/interest",
                          dict(owns=owns, wants_to_play=wants, **extras), client=client)

    def test_organizer_crud_preserves_selections(self):
        game_id = self.add_game()
        player_id = self.register()
        self.assertEqual(self.choose(game_id).status_code, 200)
        updated = self.game(name="Trackmania Nations", player_count=12, cracked=True, price="Free")
        self.assertEqual(self.write(f"/api/admin/games/{game_id}", updated, "PATCH").status_code, 200)
        game = self.state()["games"][0]
        for key, value in updated.items():
            self.assertEqual(game[key], value)
        self.assertEqual(game["players"], [dict(player_id=player_id, owns=True, wants_to_play=False)])
        self.assertEqual(self.write(f"/api/admin/games/{game_id}", method="DELETE").status_code, 200)
        self.assertEqual(self.state()["games"], [])
        with sqlite3.connect(self.config["DATABASE"]) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM game_interests").fetchone()[0], 0)
        self.assertEqual(self.choose(game_id).status_code, 404)
        self.assertEqual(self.write(f"/api/admin/games/{game_id}", updated, "PATCH").status_code, 404)

    def test_player_can_only_change_own_selection_and_clear_it(self):
        game_id = self.add_game()
        self.assertEqual(self.choose(game_id).status_code, 403)  # Organizer must register too.
        me = self.register()
        other = self.app.test_client()
        other_id = self.register(other, "456789")
        self.assertEqual(self.choose(game_id, True, False).status_code, 200)
        self.assertEqual(self.choose(game_id, False, True, other, player_id=me).status_code, 200)
        selected = {p["player_id"]:p for p in self.state()["games"][0]["players"]}
        self.assertTrue(selected[me]["owns"])
        self.assertFalse(selected[me]["wants_to_play"])
        self.assertTrue(selected[other_id]["wants_to_play"])
        self.assertEqual(self.choose(game_id, True, True).status_code, 200)
        self.assertEqual(self.choose(game_id, False, False, other).status_code, 200)
        self.assertEqual(self.state()["games"][0]["players"], [dict(player_id=me, owns=True, wants_to_play=True)])
        self.assertEqual(self.write("/api/players/me", method="DELETE").status_code, 200)
        self.assertEqual(self.state(other)["games"][0]["players"], [])

    def test_catalog_permissions_and_csrf(self):
        game_id = self.add_game()
        guest = self.app.test_client()
        for path, method in (("/api/admin/games", "POST"), (f"/api/admin/games/{game_id}", "PATCH"),
                             (f"/api/admin/games/{game_id}", "DELETE")):
            self.assertEqual(self.write(path, self.game(), method, guest).status_code, 403)
        self.assertEqual(self.choose(game_id, client=guest).status_code, 403)
        self.register(guest)
        self.assertEqual(guest.post(f"/api/games/{game_id}/interest", json=dict(owns=True, wants_to_play=True)).status_code, 403)
        self.assertEqual(self.state(guest)["games"][0]["name"], "Trackmania")

    def test_validation_and_unsafe_urls(self):
        self.login()
        invalid = [dict(name=" "), dict(name="a"*81), dict(price="a"*41), dict(genre="a"*41), dict(genre=None), dict(cracked="false"),
                   dict(player_count=True), dict(player_count=0), dict(player_count=1000), dict(player_count=2.5)]
        for url in ("javascript:alert(1)", "data:text/html,hi", "//evil.example", "https://user:pass@example.com",
                    "https://example.com\\@evil.example", "https://[bad", "https://example.com:bad", "https://exam ple.com"):
            invalid.append(dict(url=url))
        for values in invalid:
            self.assertEqual(self.write("/api/admin/games", self.game(**values)).status_code, 400, values)
        self.assertEqual(self.write("/api/admin/games", []).status_code, 400)
        game_id = self.add_game()
        self.register()
        for owns, wants in ((1, False), (False, "true"), (None, True)):
            self.assertEqual(self.choose(game_id, owns, wants).status_code, 400)
        self.assertEqual(self.write("/api/admin/games", self.game(url="", price="", name="<b>Game</b>")).status_code, 201)
        self.assertNotIn("<b>Game</b>", self.client.get("/").get_data(as_text=True))

    def test_nullable_player_count_migration_keeps_games_and_selections(self):
        game_id = self.add_game()
        self.register()
        self.assertEqual(self.choose(game_id, True, True).status_code, 200)
        with sqlite3.connect(self.config["DATABASE"]) as db:
            db.execute("CREATE TABLE games_old (id TEXT PRIMARY KEY, name TEXT NOT NULL, player_count INTEGER NOT NULL, url TEXT NOT NULL, price TEXT NOT NULL, cracked INTEGER NOT NULL)")
            db.execute("INSERT INTO games_old SELECT id, name, player_count, url, price, cracked FROM games")
            db.execute("DROP TABLE games")
            db.execute("ALTER TABLE games_old RENAME TO games")
        restarted = create_app(self.config).test_client()
        game = self.state(restarted)["games"][0]
        self.assertEqual(game["id"], game_id)
        self.assertEqual(game["genre"], "")
        self.assertEqual(len(game["players"]), 1)
        self.login(restarted)
        self.assertEqual(self.write(f"/api/admin/games/{game_id}", self.game(player_count=None), "PATCH", restarted).status_code, 200)
        self.assertIsNone(self.state(restarted)["games"][0]["player_count"])
        self.assertEqual(self.state(restarted)["games"][0]["genre"], "Course")
        self.assertEqual(self.write("/api/admin/games", self.game(name="Unknown limit", player_count=None), client=restarted).status_code, 201)
        with sqlite3.connect(self.config["DATABASE"]) as db:
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(self.write(f"/api/admin/games/{game_id}", method="DELETE", client=restarted).status_code, 200)
        with sqlite3.connect(self.config["DATABASE"]) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM game_interests").fetchone()[0], 0)

    def test_genre_edit_clear_and_persistence(self):
        game_id = self.add_game()
        self.assertEqual(self.state()["games"][0]["genre"], "Course")
        self.assertEqual(self.write(f"/api/admin/games/{game_id}", self.game(genre="  FPS  "), "PATCH").status_code, 200)
        restarted = create_app(self.config).test_client()
        self.assertEqual(self.state(restarted)["games"][0]["genre"], "FPS")
        self.assertEqual(self.write(f"/api/admin/games/{game_id}", self.game(genre=""), "PATCH").status_code, 200)
        self.assertEqual(self.state()["games"][0]["genre"], "")

    def test_persistence_migration_and_setup_gate(self):
        # Simulate the prior release's schema with existing players and organizer.
        player_id = self.register()
        with sqlite3.connect(self.config["DATABASE"]) as db:
            db.execute("DROP TABLE game_interests")
            db.execute("DROP TABLE games")
        self.app = create_app(self.config)
        self.client = self.app.test_client()
        self.assertEqual(self.state()["players"][0]["id"], player_id)
        game_id = self.add_game()
        self.register(code="456789")
        self.assertEqual(self.choose(game_id, True, True).status_code, 200)
        restarted = create_app(self.config).test_client()
        self.assertEqual(len(self.state(restarted)["games"][0]["players"]), 1)
        with sqlite3.connect(self.config["DATABASE"]) as db:
            db.execute("UPDATE organizer SET setup_required=1")
        self.assertEqual(self.state()["games"], [])
        self.assertEqual(self.choose(game_id).status_code, 403)
        self.assertEqual(self.write("/api/admin/games", self.game()).status_code, 403)


if __name__ == "__main__":
    unittest.main()
