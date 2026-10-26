import unittest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from main import app, engine
from src.espn_client import ESPNFantasyClient, normalize_name


class TestESPNIntegration(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_normalize_name(self):
        self.assertEqual(normalize_name("Patrick Mahomes II"), "patrickmahomes")
        self.assertEqual(normalize_name("Anthony Richardson Sr."), "anthonyrichardson")
        self.assertEqual(normalize_name("Aaron Jones Sr."), "aaronjones")
        self.assertEqual(normalize_name("Travis Kelce"), "traviskelce")

    def test_player_mapping_dst(self):
        espn = ESPNFantasyClient(league_id="1162468", season="2024")
        # Test D/ST mapping
        dst_sample = {"fullName": "Steelers D/ST", "defaultPositionId": 16}
        self.assertEqual(espn.map_espn_player_to_sleeper(dst_sample), "PIT")
        
        dst_sample_sf = {"fullName": "49ers D/ST", "defaultPositionId": 16}
        self.assertEqual(espn.map_espn_player_to_sleeper(dst_sample_sf), "SF")

    @patch.object(ESPNFantasyClient, "get_raw_league_data")
    def test_espn_league_switch_api(self, mock_raw):
        mock_raw.return_value = {
            "settings": {
                "name": "Test ESPN League",
                "scoringSettings": {
                    "scoringItems": [
                        {"statId": 4, "points": 4.0},
                        {"statId": 24, "points": 0.1},
                        {"statId": 53, "points": 1.0}
                    ]
                }
            },
            "members": [
                {"id": "m1", "displayName": "Manager One"}
            ],
            "teams": [
                {
                    "id": 1,
                    "name": "Team Alpha",
                    "primaryOwner": "m1",
                    "logo": "http://espn.com/logo.png",
                    "roster": {
                        "entries": [
                            {
                                "lineupSlotId": 0,
                                "playerPoolEntry": {
                                    "player": {
                                        "id": "3139477",
                                        "fullName": "Patrick Mahomes",
                                        "defaultPositionId": 1
                                    }
                                }
                            }
                        ]
                    }
                }
            ],
            "schedule": [
                {
                    "id": 101,
                    "matchupPeriodId": 1,
                    "home": {"teamId": 1, "totalPoints": 88.5},
                    "away": {"teamId": 2, "totalPoints": 75.0}
                }
            ]
        }

        # 1. Switch to ESPN
        res = self.client.post("/api/settings/league", json={
            "league_id": "999999",
            "platform": "espn",
            "season": "2024"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["platform"], "espn")
        self.assertEqual(data["league_id"], "999999")
        self.assertEqual(data["league_name"], "Test ESPN League")

        # 2. Check /api/state returns platform espn
        st_res = self.client.get("/api/state")
        self.assertEqual(st_res.status_code, 200)
        state_data = st_res.json()
        self.assertEqual(state_data["platform"], "espn")
        self.assertEqual(state_data["league_id"], "999999")

        # 3. Switch back to Sleeper
        res_sleeper = self.client.post("/api/settings/league", json={
            "league_id": "1390344846723543040",
            "platform": "sleeper"
        })
        self.assertEqual(res_sleeper.status_code, 200)
        self.assertEqual(res_sleeper.json()["platform"], "sleeper")


if __name__ == "__main__":
    unittest.main()
