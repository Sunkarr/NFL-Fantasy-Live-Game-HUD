import unittest
import time
from unittest.mock import AsyncMock, patch
from starlette.testclient import TestClient

from main import app, engine
from src.sleeper_client import SleeperClient


class TestCachingAndPerformance(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_sleeper_client_ttl_caching(self):
        client = SleeperClient(league_id="1390344846723543040")

        # Mock http calls
        mock_data_league = {"name": "Cached League", "total_rosters": 10}
        mock_data_users = [{"user_id": "u1", "display_name": "Manager 1"}]
        mock_data_rosters = [{"roster_id": 1, "owner_id": "u1", "players": ["4984"]}]
        mock_data_nfl = {"week": 7, "season": "2024", "season_type": "regular"}

        client.client.get = AsyncMock()

        # 1. Test get_league TTL cache
        client.client.get.return_value.status_code = 200
        client.client.get.return_value.json = lambda: mock_data_league

        import asyncio
        loop = asyncio.new_event_loop()
        
        # First call hits network
        res1 = loop.run_until_complete(client.get_league("1390344846723543040"))
        self.assertEqual(res1["name"], "Cached League")
        self.assertEqual(client.client.get.call_count, 1)

        # Second call within TTL hits cache (call_count stays 1)
        res2 = loop.run_until_complete(client.get_league("1390344846723543040"))
        self.assertEqual(res2["name"], "Cached League")
        self.assertEqual(client.client.get.call_count, 1)

        # Force refresh hits network again
        res3 = loop.run_until_complete(client.get_league("1390344846723543040", force_refresh=True))
        self.assertEqual(client.client.get.call_count, 2)

        # 2. Test clear_cache
        client.clear_cache("1390344846723543040")
        res4 = loop.run_until_complete(client.get_league("1390344846723543040"))
        self.assertEqual(client.client.get.call_count, 3)

        loop.close()

    def test_state_engine_fast_path_reuse(self):
        import asyncio
        loop = asyncio.new_event_loop()

        # Call refresh_state twice
        s1 = loop.run_until_complete(engine.refresh_state())
        rosters_map_ref1 = engine.rosters_map

        # Second call: rosters_map reference must be identical (fast-path reuse, zero recomputation)
        s2 = loop.run_until_complete(engine.refresh_state())
        rosters_map_ref2 = engine.rosters_map

        self.assertIs(rosters_map_ref1, rosters_map_ref2, "Rosters map should be reused directly via cached fingerprint")
        loop.close()


if __name__ == "__main__":
    unittest.main()
