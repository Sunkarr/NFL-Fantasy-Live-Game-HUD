import unittest
from starlette.testclient import TestClient

from main import app, engine


class TestActivePlayersRotation(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_mock_league_active_players_structure(self):
        """Verify mock league generates active players overview with starters & bench in correct position order."""
        state = engine.generate_mock_league(12)
        spotlights = state.idle_spotlights

        self.assertGreater(len(spotlights), 5, "Should have multiple active players in mock league")

        # 1. No player with 0.0 points and crown emoji only for leader
        for p in spotlights:
            self.assertNotEqual(p.points, 0.0, f"Player {p.player_name} has 0.0 points")
            self.assertIn(p.roster_slot, ["STARTER", "BENCH"])
            self.assertIsInstance(p.is_starter, bool)
            self.assertIsNotNone(p.rank)
            self.assertGreaterEqual(p.rank, 1)

            # Crown only for leader (rank 1), other than that only rank, position, owner
            if p.rank == 1:
                self.assertTrue(p.title.startswith("👑 #1"), f"Leader {p.player_name} must have crown: {p.title}")
            else:
                self.assertFalse(p.title.startswith("👑"), f"Non-leader {p.player_name} must not have crown: {p.title}")
                self.assertTrue(p.title.startswith(f"#{p.rank}"), f"Player {p.player_name} must start with #{p.rank}: {p.title}")
            self.assertNotIn("STARTER", p.title)
            self.assertNotIn("BENCH", p.title)

        # 2. Both starters and bench players present
        has_starter = any(p.is_starter is True for p in spotlights)
        has_bench = any(p.is_starter is False for p in spotlights)
        self.assertTrue(has_starter, "Should contain starters")
        self.assertTrue(has_bench, "Should contain bench players")

        # 3. Position grouping order: QB -> RB -> WR -> TE -> K -> DEF
        pos_order = ["QB", "RB", "WR", "TE", "K", "DEF"]
        seen_positions = []
        for p in spotlights:
            if not seen_positions or seen_positions[-1] != p.position:
                seen_positions.append(p.position)

        # Ensure positions appear in non-decreasing order relative to pos_order index
        pos_indices = [pos_order.index(p) for p in seen_positions if p in pos_order]
        self.assertEqual(pos_indices, sorted(pos_indices), "Positions must follow standard positional order")

        # 4. Within each position, sorted by points descending
        by_pos = {}
        for p in spotlights:
            by_pos.setdefault(p.position, []).append(p)

        for pos, players in by_pos.items():
            pts = [p.points for p in players]
            self.assertEqual(pts, sorted(pts, reverse=True), f"Position {pos} players should be sorted descending by points")
            ranks = [p.rank for p in players]
            self.assertEqual(ranks, list(range(1, len(players) + 1)), f"Ranks for {pos} should be sequential from 1")

    def test_api_state_contains_active_players_metadata(self):
        """Ensure /api/state returns idle_spotlights with is_starter, roster_slot, and rank."""
        engine.generate_mock_league(12)
        resp = self.client.get("/api/state")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertIn("idle_spotlights", data)
        spotlights = data["idle_spotlights"]
        self.assertIsInstance(spotlights, list)
        self.assertGreater(len(spotlights), 0)

        first = spotlights[0]
        self.assertIn("is_starter", first)
        self.assertIn("roster_slot", first)
        self.assertIn("rank", first)
        self.assertIn("color_accent", first)
