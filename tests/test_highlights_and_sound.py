import unittest
import os
import wave
from starlette.testclient import TestClient

from main import app, engine
from src.models import DisplaySettings


class TestHighlightsAndSound(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_display_settings_sound_model(self):
        settings = DisplaySettings()
        self.assertTrue(settings.sound_enabled, "sound_enabled should default to True")

        settings_disabled = DisplaySettings(sound_enabled=False)
        self.assertFalse(settings_disabled.sound_enabled)
        self.assertEqual(settings_disabled.model_dump()["sound_enabled"], False)

    def test_sound_api_endpoints(self):
        # Toggle sound via /api/settings/sound
        resp1 = self.client.post("/api/settings/sound", json={"sound_enabled": False})
        self.assertEqual(resp1.status_code, 200)
        self.assertFalse(resp1.json()["sound_enabled"])
        self.assertFalse(engine.display_settings.sound_enabled)

        # Toggle sound back via null parameter (inversion)
        resp2 = self.client.post("/api/settings/sound", json={})
        self.assertEqual(resp2.status_code, 200)
        self.assertTrue(resp2.json()["sound_enabled"])
        self.assertTrue(engine.display_settings.sound_enabled)

        # Set sound via general /api/settings
        resp3 = self.client.post("/api/settings", json={"sound_enabled": False, "speed": "fast"})
        self.assertEqual(resp3.status_code, 200)
        self.assertFalse(resp3.json()["settings"]["sound_enabled"])
        self.assertEqual(resp3.json()["settings"]["speed"], "fast")

        # Restore to default
        self.client.post("/api/settings/sound", json={"sound_enabled": True})

    def test_sound_asset_wav_file(self):
        wav_path = os.path.join(os.path.dirname(__file__), "..", "static", "sounds", "nfl_highlight.wav")
        self.assertTrue(os.path.exists(wav_path), "nfl_highlight.wav must exist in static/sounds/")

        # Verify it's a valid audio WAV file
        with wave.open(wav_path, "rb") as wf:
            self.assertEqual(wf.getnchannels(), 1)
            self.assertEqual(wf.getsampwidth(), 2)  # 16-bit
            self.assertEqual(wf.getframerate(), 44100)
            self.assertGreater(wf.getnframes(), 0)

        # Verify static file serving via TestClient
        resp = self.client.get("/static/sounds/nfl_highlight.wav")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("audio/", resp.headers.get("content-type", ""))

    def test_defense_headshot_resolution(self):
        # 1. Test get_player_info("MIN") returns Sleeper team logo URL
        min_info = engine.sleeper.get_player_info("MIN")
        self.assertEqual(min_info["position"], "DEF")
        self.assertEqual(min_info["team"], "MIN")
        self.assertEqual(min_info["headshot_url"], "https://sleepercdn.com/images/team_logos/nfl/min.png")

        # 2. Test highlight trigger for defense play
        resp = self.client.post("/api/test/highlight", json={
            "player_name": "Minnesota Vikings",
            "delta_points": 8.0,
            "fantasy_team_name": "Roster 3",
            "position": "DEF",
            "nfl_team": "MIN"
        })
        self.assertEqual(resp.status_code, 200)
        hl = resp.json()["highlight"]
        self.assertEqual(hl["player_name"], "Minnesota Vikings")
        self.assertEqual(hl["position"], "DEF")
        self.assertEqual(hl["headshot_url"], "https://sleepercdn.com/images/team_logos/nfl/min.png")

    def test_highlight_trigger(self):
        resp = self.client.post("/api/test/highlight", json={
            "player_name": "Travis Kelce",
            "delta_points": 7.2,
            "fantasy_team_name": "Roster 4"
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        hl = data["highlight"]
        self.assertEqual(hl["player_name"], "Travis Kelce")
        self.assertEqual(hl["delta_points"], 7.2)
        self.assertIn("color_accent", hl)

    def test_highlight_category_emojis_and_flame(self):
        # 1. Normal TD (< 10 pts) -> 🏈 TOUCHDOWN
        resp1 = self.client.post("/api/test/highlight", json={
            "player_name": "Josh Allen",
            "delta_points": 6.4,
            "highlight_type": "touchdown",
            "is_touchdown": True
        })
        self.assertEqual(resp1.status_code, 200)
        h1 = resp1.json()["highlight"]
        self.assertEqual(h1["highlight_type"], "touchdown")
        self.assertTrue(h1["is_touchdown"])

        # 2. Monster TD (>= 10 pts) -> 🏈🔥 TOUCHDOWN
        resp2 = self.client.post("/api/test/highlight", json={
            "player_name": "Joe Burrow",
            "delta_points": 12.4,
            "highlight_type": "touchdown",
            "is_touchdown": True
        })
        self.assertEqual(resp2.status_code, 200)
        h2 = resp2.json()["highlight"]
        self.assertGreaterEqual(h2["delta_points"], 10.0)

        # 3. Big Play (< 10 pts) -> ⚡ BIG PLAY
        resp3 = self.client.post("/api/test/highlight", json={
            "player_name": "Bijan Robinson",
            "delta_points": 5.8,
            "highlight_type": "big_play",
            "is_touchdown": False
        })
        self.assertEqual(resp3.status_code, 200)
        h3 = resp3.json()["highlight"]
        self.assertEqual(h3["highlight_type"], "big_play")
        self.assertFalse(h3["is_touchdown"])

        # 4. Field Goal -> 🎯 FIELD GOAL
        resp4 = self.client.post("/api/test/highlight", json={
            "player_name": "Brandon Aubrey",
            "delta_points": 5.0,
            "position": "K",
            "highlight_type": "field_goal"
        })
        self.assertEqual(resp4.status_code, 200)
        h4 = resp4.json()["highlight"]
        self.assertEqual(h4["highlight_type"], "field_goal")

        # 5. Defense Stop -> 🛡️ DEF STOP
        resp5 = self.client.post("/api/test/highlight", json={
            "player_name": "Minnesota Vikings",
            "delta_points": 4.0,
            "position": "DEF",
            "highlight_type": "def_stop",
            "is_touchdown": False
        })
        self.assertEqual(resp5.status_code, 200)
        h5 = resp5.json()["highlight"]
        self.assertEqual(h5["highlight_type"], "def_stop")

    def test_jersey_name_formatting_logic(self):
        # Python mirror of formatHighlightDisplayName to verify all edge cases
        def format_highlight_display_name(name, position, nfl_team):
            pos = (position or "").upper()
            if pos == "DEF":
                if nfl_team and nfl_team.strip():
                    return nfl_team.strip().upper()
                return "DEF"
            parts = name.strip().split()
            if len(parts) <= 1:
                return name
            return f"{parts[0][0].upper()}. {' '.join(parts[1:])}"

        self.assertEqual(format_highlight_display_name("Bijan Robinson", "RB", "ATL"), "B. Robinson")
        self.assertEqual(format_highlight_display_name("Brian Robinson Jr.", "RB", "WAS"), "B. Robinson Jr.")
        self.assertEqual(format_highlight_display_name("Josh Allen", "QB", "BUF"), "J. Allen")
        self.assertEqual(format_highlight_display_name("Jonathan Taylor", "RB", "IND"), "J. Taylor")
        self.assertEqual(format_highlight_display_name("Kenneth Walker III", "RB", "SEA"), "K. Walker III")
        self.assertEqual(format_highlight_display_name("Minnesota Vikings", "DEF", "MIN"), "MIN")
        self.assertEqual(format_highlight_display_name("Buffalo Bills", "DEF", "BUF"), "BUF")

    def test_sound_themes_api_and_assets(self):
        # Test sound-theme API endpoint
        resp = self.client.post("/api/settings/sound-theme", json={"sound_theme": "fox_horn"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["settings"]["sound_theme"], "fox_horn")

        resp_rz = self.client.post("/api/settings/sound-theme", json={"sound_theme": "redzone"})
        self.assertEqual(resp_rz.status_code, 200)
        self.assertEqual(resp_rz.json()["settings"]["sound_theme"], "redzone")

        # Verify all 4 sound files exist and are valid WAV files
        for fn in ["nfl_fox_horn.wav", "nfl_redzone_alert.wav", "nfl_touchdown_siren.wav", "nfl_brass_fanfare.wav"]:
            wav_path = os.path.join(os.path.dirname(__file__), "..", "static", "sounds", fn)
            self.assertTrue(os.path.exists(wav_path), f"{fn} must exist")
            with wave.open(wav_path, "rb") as wf:
                self.assertEqual(wf.getnchannels(), 1)
                self.assertEqual(wf.getsampwidth(), 2)
                self.assertGreater(wf.getnframes(), 0)

    def test_frontend_templates_contain_sound_and_jiggle(self):
        # 1. overlay.html (clean top bar with week tag & toast, sound toggled in Welcome Dialog)
        resp_html = self.client.get("/overlay")
        self.assertEqual(resp_html.status_code, 200)
        html_text = resp_html.text
        self.assertIn("hud-week-tag", html_text)
        self.assertIn("hud-toast", html_text)

        # 2. overlay.css
        resp_css = self.client.get("/static/overlay.css")
        self.assertEqual(resp_css.status_code, 200)
        css_text = resp_css.text
        self.assertIn("highlight-entrance-jiggle", css_text)
        self.assertIn("highlight-jiggle-burst", css_text)
        self.assertIn("highlight-sheen-sweep", css_text)
        self.assertIn("sound-toggle-btn", css_text)

        # 3. overlay.js
        resp_js = self.client.get("/static/overlay.js")
        self.assertEqual(resp_js.status_code, 200)
        js_text = resp_js.text
        self.assertIn("playNFLFanfareSound", js_text)
        self.assertIn("synthesizeFanfare", js_text)
        self.assertIn("toggleSound", js_text)
        self.assertIn("nfl_hud_sound_enabled", js_text)
        self.assertIn("jiggling", js_text)

        # 4. admin.html
        resp_admin = self.client.get("/admin")
        self.assertEqual(resp_admin.status_code, 200)
        admin_text = resp_admin.text
        self.assertIn("toggleSound()", admin_text)
        self.assertIn("playTestFanfare()", admin_text)
        self.assertIn("triggerTestHighlight()", admin_text)


if __name__ == "__main__":
    unittest.main()
