import unittest
import time
from unittest.mock import AsyncMock, patch, MagicMock
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
        mock_data_matchups = [{"matchup_id": 1, "roster_id": 1, "points": 105.4}]

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

    def test_sleeper_matchups_caching_and_404_resilience(self):
        client = SleeperClient(league_id="1390344846723543040")
        mock_matchups = [{"matchup_id": 1, "roster_id": 1, "points": 88.5}]

        client.client.get = AsyncMock()
        client.client.get.return_value.status_code = 200
        client.client.get.return_value.json = lambda: mock_matchups

        import asyncio
        loop = asyncio.new_event_loop()

        # 1. Initial fetch caches matchups
        res1 = loop.run_until_complete(client.get_matchups(week=8))
        self.assertEqual(len(res1), 1)
        self.assertEqual(res1[0]["points"], 88.5)
        self.assertEqual(client.client.get.call_count, 1)

        # 2. Second fetch within TTL hits memory cache
        res2 = loop.run_until_complete(client.get_matchups(week=8))
        self.assertEqual(res2, mock_matchups)
        self.assertEqual(client.client.get.call_count, 1)

        # 3. Simulate API 404 error (e.g. Sleeper weekly rollover or Cloudflare caching)
        # Should gracefully serve cached matchups instead of raising or returning []
        client._matchups_cache_time.clear()  # Expire TTL
        client.client.get.return_value.status_code = 404
        client.client.get.return_value.json = lambda: None

        res_404 = loop.run_until_complete(client.get_matchups(week=8))
        self.assertEqual(len(res_404), 1, "Should gracefully return cached matchups on 404")
        self.assertEqual(res_404[0]["points"], 88.5)

        # 4. Simulate Network Exception
        client._matchups_cache_time.clear()  # Expire TTL
        client.client.get.side_effect = Exception("Connection timeout")

        res_err = loop.run_until_complete(client.get_matchups(week=8))
        self.assertEqual(len(res_err), 1, "Should gracefully return cached matchups on network error")
        self.assertEqual(res_err[0]["points"], 88.5)

        # 5. Clear cache and verify empty return when no cache exists
        client.clear_cache("1390344846723543040")
        res_empty = loop.run_until_complete(client.get_matchups(week=8))
        self.assertEqual(res_empty, [])

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
