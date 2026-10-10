import json
import sqlite3
import unittest
from unittest.mock import patch

import test_app


class TeamsTests(unittest.TestCase):
    setUp = test_app.LANpackTests.setUp
    state = test_app.LANpackTests.state
    write = test_app.LANpackTests.write
    player = test_app.LANpackTests.player
    register = test_app.LANpackTests.register

    def roster(self, count):
        return [self.register(self.app.test_client(), str(20000+i)) for i in range(count)]

    def shuffle(self, ids, mode="team_count", amount=2):
        return self.write("/api/teams/shuffle", dict(player_ids=ids, mode=mode, amount=amount))

    def test_balanced_teams_include_only_selected_players_once(self):
        ids = self.roster(8)
        selected = ids[:7]
        with patch("app.secrets.SystemRandom") as random:
            random.return_value.shuffle.side_effect = lambda players: players.reverse()
            response = self.shuffle(selected, amount=3)
            random.return_value.shuffle.assert_called_once()
        self.assertEqual(response.status_code, 200)
        teams = response.json["teams"]
        self.assertEqual([len(team["players"]) for team in teams], [3, 2, 2])
        assigned = [player["id"] for team in teams for player in team["players"]]
        self.assertCountEqual(assigned, selected)
        self.assertEqual(len(set(assigned)), len(selected))
        self.assertNotIn(ids[-1], assigned)
        self.assertNotIn("steam_code", json.dumps(teams))
        self.assertNotIn("edit_hash", json.dumps(teams))

    def test_maximum_team_size_balances_remainder_without_benching(self):
        ids = self.roster(7)
        teams = self.shuffle(ids, "team_size", 3).json["teams"]
        self.assertEqual([len(t["players"]) for t in teams], [3, 2, 2])
        self.assertEqual(sum(len(t["players"]) for t in teams), 7)
        self.assertEqual(len(self.shuffle(ids, "team_size", 1).json["teams"]), 7)

    def test_invalid_selection_and_split(self):
        ids = self.roster(3)
        for selection in (None, [], ids[:1], [ids[0], ids[0]], [ids[0], 123], [ids[0], "bogus"], ids*34):
            self.assertEqual(self.shuffle(selection).status_code, 400)
        for mode, amount in (("other", 2), ("team_count", True), ("team_count", 2.5),
                             ("team_count", 0), ("team_count", 1), ("team_count", 4),
                             ("team_size", 3), ("team_size", 101)):
            self.assertEqual(self.shuffle(ids, mode, amount).status_code, 400)
        self.assertEqual(self.write("/api/teams/shuffle", []).status_code, 400)

    def test_missing_player_is_rejected_and_draw_does_not_write_shared_data(self):
        ids = self.roster(4)
        with sqlite3.connect(self.config["DATABASE"]) as db:
            before = list(db.iterdump())
        self.assertEqual(self.shuffle(ids).status_code, 200)
        self.assertEqual(self.shuffle(ids).status_code, 200)
        with sqlite3.connect(self.config["DATABASE"]) as db:
            self.assertEqual(list(db.iterdump()), before)
            db.execute("DELETE FROM players WHERE id=?", (ids[0],))
        self.assertEqual(self.shuffle(ids).status_code, 409)

    def test_csrf_and_first_run_gate(self):
        ids = self.roster(2)
        self.assertEqual(self.client.post("/api/teams/shuffle", json=dict(player_ids=ids,mode="team_count",amount=2)).status_code, 403)
        with sqlite3.connect(self.config["DATABASE"]) as db:
            db.execute("UPDATE organizer SET setup_required=1")
        self.assertEqual(self.shuffle(ids).status_code, 403)


if __name__ == "__main__":
    unittest.main()
