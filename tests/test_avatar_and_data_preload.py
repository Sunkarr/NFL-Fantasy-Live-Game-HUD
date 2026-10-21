import unittest
from starlette.testclient import TestClient

from main import app, engine
from src.state_engine import resolve_avatar_url


class TestAvatarAndDataPreload(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_resolve_avatar_url(self):
        # 1. Custom uploaded avatars (Direct URL)
        upload_url = "https://sleepercdn.com/uploads/679b72754dd5f7c97564921841740621.png"
        self.assertEqual(resolve_avatar_url(upload_url), upload_url)

        # 2. Standard Sleeper avatar hashes -> full-res CDN URL
        hash_id = "4f9417c504f57a8ebfb9588586f8d5c3"
        self.assertEqual(
            resolve_avatar_url(hash_id),
            f"https://sleepercdn.com/avatars/{hash_id}"
        )

        # 3. None / empty / null handling
        self.assertIsNone(resolve_avatar_url(None))
        self.assertIsNone(resolve_avatar_url(""))
        self.assertIsNone(resolve_avatar_url("   "))
        self.assertIsNone(resolve_avatar_url("none"))
        self.assertIsNone(resolve_avatar_url("null"))

    def test_state_managers_have_newest_avatars(self):
        resp = self.client.get("/api/state")
        self.assertEqual(resp.status_code, 200)
        state = resp.json()
        matchups = state.get("matchups", [])
        self.assertGreater(len(matchups), 0, "State must contain active matchups")

        for m in matchups:
            for team_key in ["team_a", "team_b"]:
                t = m.get(team_key)
                if not t:
                    continue
                avatar = t.get("avatar_url")
                self.assertTrue(
                    avatar.startswith("https://sleepercdn.com/"),
                    f"Avatar URL must point to valid Sleeper CDN: {avatar}"
                )
                # Verify that low-res thumb is NOT used when full CDN / upload is available
                self.assertNotIn("/avatars/thumbs/", avatar, f"Should use full-resolution avatar, got: {avatar}")

    def test_avatar_priority_hierarchy(self):
        # Test simulated user & roster structure to verify metadata override priority
        mock_user = {
            "user_id": "test_u1",
            "display_name": "OriginalName",
            "avatar": "account_avatar_hash",
            "metadata": {
                "team_name": "LeagueCustomTeam",
                "avatar": "https://sleepercdn.com/uploads/custom_team_avatar.png"
            }
        }
        mock_roster = {
            "roster_id": 1,
            "owner_id": "test_u1",
            "metadata": {
                "team_name": "RosterOverrideTeam",
                "avatar": "https://sleepercdn.com/uploads/roster_override_avatar.png"
            }
        }

        # 1. Roster metadata has highest priority
        roster_avatar = (
            resolve_avatar_url(mock_roster["metadata"].get("avatar"))
            or resolve_avatar_url(mock_user["metadata"].get("avatar"))
            or resolve_avatar_url(mock_user.get("avatar"))
        )
        self.assertEqual(roster_avatar, "https://sleepercdn.com/uploads/roster_override_avatar.png")

        # 2. When roster has no avatar, user metadata avatar is prioritized over global avatar
        user_meta_avatar = (
            resolve_avatar_url(None)
            or resolve_avatar_url(mock_user["metadata"].get("avatar"))
            or resolve_avatar_url(mock_user.get("avatar"))
        )
        self.assertEqual(user_meta_avatar, "https://sleepercdn.com/uploads/custom_team_avatar.png")

        # 3. When no custom upload exists, global avatar hash resolves to full CDN
        global_avatar = (
            resolve_avatar_url(None)
            or resolve_avatar_url(None)
            or resolve_avatar_url(mock_user.get("avatar"))
        )
        self.assertEqual(global_avatar, "https://sleepercdn.com/avatars/account_avatar_hash")

    def test_frontend_overlay_contains_preloader_and_error_guard(self):
        resp = self.client.get("/static/overlay.js")
        self.assertEqual(resp.status_code, 200)
        js_text = resp.text
        self.assertIn("preloadMedia", js_text)
        self.assertIn("preloadedMedia", js_text)
        self.assertIn("handleTeamAvatarError", js_text)
        self.assertIn("fallbackApplied", js_text)


if __name__ == "__main__":
    unittest.main()
