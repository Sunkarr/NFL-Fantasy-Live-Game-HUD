import unittest
from starlette.testclient import TestClient
from main import app, engine as state_engine

class TestInjuriesAndToggles(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_settings_highlights_toggle(self):
        # Disable highlights
        res = self.client.post("/api/settings/highlights", json={"highlights_enabled": False})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["highlights_enabled"])

        # Enable highlights
        res = self.client.post("/api/settings/highlights", json={"highlights_enabled": True})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["highlights_enabled"])

    def test_settings_injuries_toggle(self):
        # Disable injuries
        res = self.client.post("/api/settings/injuries", json={"injuries_enabled": False})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["injuries_enabled"])

        # Enable injuries
        res = self.client.post("/api/settings/injuries", json={"injuries_enabled": True})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["injuries_enabled"])

    def test_settings_injury_sound_and_theme(self):
        # Toggle injury sound
        res = self.client.post("/api/settings/injury-sound", json={"injury_sound_enabled": False})
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()["injury_sound_enabled"])

        res = self.client.post("/api/settings/injury-sound", json={"injury_sound_enabled": True})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["injury_sound_enabled"])

        # Change injury sound theme
        themes = ["whistle_blow", "buzzer_flat", "flatline", "record_scratch"]
        for t in themes:
            res = self.client.post("/api/settings/injury-sound-theme", json={"injury_sound_theme": t})
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["injury_sound_theme"], t)

    def test_trigger_test_injury(self):
        # Push test injury alert
        payload = {
            "player_name": "CeeDee Lamb",
            "injury_status": "Out",
            "injury_detail": "Shoulder - Out for remainder of game",
            "position": "WR",
            "nfl_team": "DAL",
            "fantasy_team_name": "Roster 1"
        }
        res = self.client.post("/api/test/injury", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "ok")
        self.assertIsNotNone(data["injury"])
        self.assertEqual(data["injury"]["player_name"], "CeeDee Lamb")
        self.assertEqual(data["injury"]["injury_status"], "Out")

        # Verify it appears in state
        res_state = self.client.get("/api/state")
        self.assertEqual(res_state.status_code, 200)
        state_data = res_state.json()
        self.assertTrue(any(inj["player_name"] == "CeeDee Lamb" for inj in state_data.get("injury_queue", [])))

    def test_simulate_random_injury(self):
        # Trigger randomized injury
        res = self.client.post("/api/test/simulate-injury")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "ok")

    def test_negative_sound_files_exist(self):
        # Verify 4 negative audio files are served via static files
        files = [
            "injury_whistle.wav",
            "injury_buzzer.wav",
            "injury_flatline.wav",
            "injury_record_scratch.wav"
        ]
        for f in files:
            res = self.client.get(f"/static/sounds/{f}")
            self.assertEqual(res.status_code, 200, f"Sound file {f} must return HTTP 200")
            self.assertGreater(len(res.content), 100, f"Sound file {f} must have non-empty audio content")

if __name__ == "__main__":
    unittest.main()
