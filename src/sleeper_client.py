import json
import logging
import os
import time
from typing import Dict, List, Optional, Any
import httpx

from src.config import PLAYERS_CACHE_FILE, LEAGUE_ID

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 86400.0  # 24 Hours: Daily refresh to capture NFL trades, cuts, and team changes


class SleeperClient:
    def __init__(self, league_id: str = LEAGUE_ID):
        self.league_id = league_id
        self.client = httpx.AsyncClient(timeout=10.0)
        self.players_dict: Dict[str, Dict[str, Any]] = {}
        self._load_or_fetch_players()

    def _is_cache_stale(self) -> bool:
        """Check if local players cache is older than 24 hours."""
        if not PLAYERS_CACHE_FILE.exists():
            return True
        try:
            mtime = os.path.getmtime(PLAYERS_CACHE_FILE)
            return (time.time() - mtime) > CACHE_TTL_SECONDS
        except Exception:
            return True

    def get_cache_info(self) -> Dict[str, Any]:
        """Return cache metadata (size, age in hours, staleness) for admin inspection."""
        if PLAYERS_CACHE_FILE.exists():
            try:
                mtime = os.path.getmtime(PLAYERS_CACHE_FILE)
                age_hours = round((time.time() - mtime) / 3600.0, 1)
                return {
                    "cached": True,
                    "count": len(self.players_dict),
                    "last_updated": mtime,
                    "last_updated_str": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime)),
                    "age_hours": age_hours,
                    "is_stale": age_hours > 24.0
                }
            except Exception:
                pass
        return {
            "cached": False,
            "count": len(self.players_dict),
            "last_updated": 0,
            "last_updated_str": "Never",
            "age_hours": 999.0,
            "is_stale": True
        }

    def _load_or_fetch_players(self):
        """Load player database from local cache file."""
        if PLAYERS_CACHE_FILE.exists():
            try:
                with open(PLAYERS_CACHE_FILE, "r", encoding="utf-8") as f:
                    self.players_dict = json.load(f)
                age = round((time.time() - os.path.getmtime(PLAYERS_CACHE_FILE)) / 3600.0, 1)
                logger.info(f"Loaded {len(self.players_dict)} players from cache (Age: {age}h).")
                return
            except Exception as e:
                logger.warning(f"Failed to load cached players: {e}")

        logger.info("Player cache not found. Will fetch on startup.")

    async def ensure_players_cache(self) -> int:
        """Ensure players are loaded; auto-refresh if missing or older than 24h."""
        if not self.players_dict or self._is_cache_stale():
            logger.info("Player database is missing or older than 24h. Refreshing from Sleeper API...")
            return await self.fetch_and_cache_players()
        return len(self.players_dict)

    async def refresh_players_cache(self) -> int:
        """Force manual re-fetch of complete NFL players database from Sleeper."""
        return await self.fetch_and_cache_players()

    async def fetch_and_cache_players(self) -> int:
        """Download complete NFL players database from Sleeper."""
        try:
            url = "https://api.sleeper.app/v1/players/nfl"
            resp = await self.client.get(url)
            resp.raise_for_status()
            data = resp.json()
            self.players_dict = data
            PLAYERS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(PLAYERS_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f)
            logger.info(f"Successfully cached {len(data)} players to {PLAYERS_CACHE_FILE}")
            return len(data)
        except Exception as e:
            logger.error(f"Error downloading players database: {e}")
            return len(self.players_dict)

    async def get_nfl_state(self) -> Dict[str, Any]:
        """Fetch current NFL state (current week, season, leg, etc.)."""
        try:
            resp = await self.client.get("https://api.sleeper.app/v1/state/nfl")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Error fetching NFL state: {e}")
            return {"week": 1, "season": "2026", "season_type": "regular"}

    async def get_league(self, league_id: Optional[str] = None) -> Dict[str, Any]:
        """Fetch league metadata."""
        lid = league_id or self.league_id
        try:
            resp = await self.client.get(f"https://api.sleeper.app/v1/league/{lid}")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Error fetching league {lid}: {e}")
            return {"name": "NFL Fantasy League", "season": "2026", "total_rosters": 6}

    async def get_league_info(self, league_id: Optional[str] = None) -> Dict[str, Any]:
        """Alias for get_league."""
        return await self.get_league(league_id)

    async def get_users(self, league_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch league managers / users."""
        lid = league_id or self.league_id
        try:
            resp = await self.client.get(f"https://api.sleeper.app/v1/league/{lid}/users")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Error fetching users for league {lid}: {e}")
            return []

    async def get_league_users(self, league_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Alias for get_users."""
        return await self.get_users(league_id)

    async def get_rosters(self, league_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch league rosters."""
        lid = league_id or self.league_id
        try:
            resp = await self.client.get(f"https://api.sleeper.app/v1/league/{lid}/rosters")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Error fetching rosters for league {lid}: {e}")
            return []

    async def get_league_rosters(self, league_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Alias for get_rosters."""
        return await self.get_rosters(league_id)

    async def get_matchups(self, week: int, league_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch matchups for a given week."""
        lid = league_id or self.league_id
        try:
            resp = await self.client.get(f"https://api.sleeper.app/v1/league/{lid}/matchups/{week}")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Error fetching matchups for league {lid} week {week}: {e}")
            return []

    async def get_weekly_stats(self, season: str, week: int, season_type: str = "regular") -> Dict[str, Dict[str, Any]]:
        """Fetch weekly stats for all NFL players (including Free Agents)."""
        try:
            url = f"https://api.sleeper.app/v1/stats/nfl/{season_type}/{season}/{week}"
            resp = await self.client.get(url)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.warning(f"Error fetching weekly stats for {season} W{week}: {e}")
        return {}

    def get_player_info(self, player_id: str) -> Dict[str, Any]:
        """Retrieve player details by player_id from cached dictionary."""
        pid_str = str(player_id).strip()
        player = self.players_dict.get(pid_str, {})
        
        pos = player.get("position", "")
        # If it's a team defense (position is DEF or player_id is team abbreviation like 'MIN', 'BUF', 'KC')
        is_defense = (pos == "DEF") or (pid_str.isalpha() and len(pid_str) in [2, 3])

        if is_defense:
            team_abbr = player.get("team") or (pid_str.upper() if pid_str.isalpha() else "DEF")
            team_code = team_abbr.lower()
            first_name = player.get("first_name", "")
            last_name = player.get("last_name", "")
            full_name = f"{first_name} {last_name}".strip() or player.get("full_name") or f"{team_abbr} Defense"
            return {
                "player_id": pid_str,
                "name": full_name,
                "position": "DEF",
                "team": team_abbr.upper(),
                "injury_status": "Active",
                "headshot_url": f"https://sleepercdn.com/images/team_logos/nfl/{team_code}.png"
            }

        first_name = player.get("first_name", "")
        last_name = player.get("last_name", "")
        full_name = f"{first_name} {last_name}".strip() or player.get("full_name", f"Player {pid_str}")

        return {
            "player_id": pid_str,
            "name": full_name,
            "position": pos or "BN",
            "team": player.get("team") or "FA",
            "injury_status": player.get("injury_status") or "Active",
            "headshot_url": f"https://sleepercdn.com/content/nfl/players/{pid_str}.jpg"
        }

    # Backward compatibility alias
    get_cached_player = get_player_info
