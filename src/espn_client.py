"""
NFL Fantasy Live Game HUD — ESPN Fantasy Football API Client
Pulls league settings, members, teams, rosters and weekly matchups from ESPN Fantasy API (v3),
and maps players and scoring rules into the normalized HUD schema for live Sleeper stats polling.
"""

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .config import (
    ESPN_LEAGUE_ID,
    ESPN_SEASON,
    ESPN_S2,
    ESPN_SWID,
    PLAYERS_CACHE_FILE,
    CURRENT_SEASON,
)

logger = logging.getLogger("src.espn_client")

# Mapping ESPN stat IDs to Sleeper scoring keys
ESPN_STAT_MAP: Dict[int, str] = {
    3: "pass_yd",       # Passing Yards (e.g. 0.04)
    4: "pass_td",       # Passing Touchdown (4.0)
    19: "pass_2pt",     # 2-Point Conversion Pass (2.0)
    20: "pass_int",     # Pass Intercepted (-2.0)
    24: "rush_yd",      # Rushing Yards (0.1)
    25: "rush_td",      # Rushing Touchdown (6.0)
    26: "rush_2pt",     # 2-Point Conversion Rush (2.0)
    42: "rec_yd",       # Receiving Yards (0.1)
    43: "rec_td",       # Receiving Touchdown (6.0)
    44: "rec_2pt",      # 2-Point Conversion Reception (2.0)
    53: "rec",          # Reception / PPR (1.0 or 0.5)
    72: "fum_lost",     # Fumble Lost (-2.0)
    80: "fgm_0_19",     # Field Goal 1-19 Yards
    81: "fgm_20_29",    # Field Goal 20-29 Yards
    82: "fgm_30_39",    # Field Goal 30-39 Yards
    77: "fgm_40_49",    # Field Goal 40-49 Yards
    201: "fgm_50p",     # Field Goal 50+ Yards
    86: "xpm",          # Extra Point Made (1.0)
    85: "xpmiss",       # Extra Point Missed (-1.0)
    89: "def_pts_0",    # D/ST Points Allowed 0
    90: "def_pts_1_6",  # D/ST Points Allowed 1-6
    91: "def_pts_7_13", # D/ST Points Allowed 7-13
    92: "def_pts_14_17",# D/ST Points Allowed 14-17
    95: "def_sack",     # D/ST Sack (1.0)
    96: "def_int",      # D/ST Interception (2.0)
    97: "def_fr",       # D/ST Fumble Recovery (2.0)
    98: "def_safety",   # D/ST Safety (2.0)
    103: "def_td",      # D/ST Touchdown (6.0)
    104: "def_td",      # D/ST Touchdown (6.0)
}

# Mapping NFL team city/mascots to standard NFL abbreviations for D/ST
NFL_DST_MAP: Dict[str, str] = {
    "steelers": "PIT", "pittsburgh": "PIT",
    "colts": "IND", "indianapolis": "IND",
    "eagles": "PHI", "philadelphia": "PHI",
    "49ers": "SF", "san francisco": "SF",
    "dolphins": "MIA", "miami": "MIA",
    "vikings": "MIN", "minnesota": "MIN",
    "buccaneers": "TB", "tampa": "TB",
    "chiefs": "KC", "kansas": "KC",
    "chargers": "LAC",
    "cardinals": "ARI", "arizona": "ARI",
    "raiders": "LV", "las vegas": "LV",
    "bengals": "CIN", "cincinnati": "CIN",
    "ravens": "BAL", "baltimore": "BAL",
    "packers": "GB", "green bay": "GB",
    "seahawks": "SEA", "seattle": "SEA",
    "bills": "BUF", "buffalo": "BUF",
    "cowboys": "DAL", "dallas": "DAL",
    "lions": "DET", "detroit": "DET",
    "texans": "HOU", "houston": "HOU",
    "jaguars": "JAX", "jacksonville": "JAX",
    "rams": "LAR",
    "patriots": "NE", "new england": "NE",
    "saints": "NO", "new orleans": "NO",
    "giants": "NYG",
    "jets": "NYJ",
    "broncos": "DEN", "denver": "DEN",
    "bears": "CHI", "chicago": "CHI",
    "browns": "CLE", "cleveland": "CLE",
    "commanders": "WAS", "washington": "WAS",
    "panthers": "CAR", "carolina": "CAR",
    "falcons": "ATL", "atlanta": "ATL",
    "titans": "TEN", "tennessee": "TEN"
}


def normalize_name(name: str) -> str:
    """Normalize athlete name for resilient fuzzy matching."""
    if not name:
        return ""
    n = name.lower().strip()
    # Remove generation suffixes
    n = re.sub(r"\b(sr|jr|iii|ii|iv|v)\b\.?", "", n)
    # Remove punctuation & spaces
    return re.sub(r"[^a-z0-9]", "", n)


class ESPNFantasyClient:
    """
    Asynchronous client for ESPN Fantasy Football API v3.
    Extracts league structure and maps it seamlessly into Sleeper-compatible models.
    """

    def __init__(
        self,
        league_id: str = ESPN_LEAGUE_ID,
        season: str = ESPN_SEASON,
        espn_s2: str = ESPN_S2,
        swid: str = ESPN_SWID,
    ):
        self.league_id = str(league_id).strip()
        self.season = str(season).strip() if (season and str(season).strip() != "auto") else CURRENT_SEASON
        self.espn_s2 = str(espn_s2).strip()
        self.swid = str(swid).strip()
        self.client = httpx.AsyncClient(timeout=10.0)

        # Player matching indexes
        self.espn_id_to_sleeper: Dict[str, str] = {}
        self.name_to_sleeper: Dict[str, str] = {}
        self._load_player_index()

    def _load_player_index(self):
        """Build bidirectional mapping from cached Sleeper NFL players."""
        if not PLAYERS_CACHE_FILE.exists():
            return
        try:
            with open(PLAYERS_CACHE_FILE, "r", encoding="utf-8") as f:
                players = json.load(f)
            for pid, p in players.items():
                if not isinstance(p, dict):
                    continue
                # Index by ESPN Athlete ID
                eid = p.get("espn_id")
                if eid:
                    self.espn_id_to_sleeper[str(eid)] = pid
                # Index by cleaned full name
                fn = p.get("full_name")
                if fn:
                    norm = normalize_name(fn)
                    if norm and norm not in self.name_to_sleeper:
                        self.name_to_sleeper[norm] = pid
            logger.info(
                f"ESPN Player Index ready: {len(self.espn_id_to_sleeper)} by espn_id, "
                f"{len(self.name_to_sleeper)} by normalized name."
            )
        except Exception as e:
            logger.warning(f"Could not load player cache for ESPN client: {e}")

    def update_credentials(
        self,
        league_id: Optional[str] = None,
        season: Optional[str] = None,
        espn_s2: Optional[str] = None,
        swid: Optional[str] = None,
    ):
        """Update active ESPN league parameters dynamically."""
        if league_id is not None:
            self.league_id = str(league_id).strip()
        if season is not None:
            self.season = str(season).strip() if (season and str(season).strip() != "auto") else CURRENT_SEASON
        if espn_s2 is not None:
            self.espn_s2 = str(espn_s2).strip()
        if swid is not None:
            self.swid = str(swid).strip()

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "application/json",
        }
        cookies = []
        if self.espn_s2:
            cookies.append(f"espn_s2={self.espn_s2}")
        if self.swid:
            cookies.append(f"SWID={self.swid}")
        if cookies:
            headers["Cookie"] = "; ".join(cookies)
        return headers

    def map_espn_player_to_sleeper(self, espn_player: Dict[str, Any]) -> str:
        """Resolve ESPN player dictionary to corresponding Sleeper player_id."""
        eid = str(espn_player.get("id", "")).strip()
        if eid and eid in self.espn_id_to_sleeper:
            return self.espn_id_to_sleeper[eid]

        pname = espn_player.get("fullName", "").strip()
        pos_id = espn_player.get("defaultPositionId")

        # Position 16 is Team Defense / Special Teams
        if pos_id == 16:
            p_lower = pname.lower()
            for key, abbr in NFL_DST_MAP.items():
                if key in p_lower:
                    return abbr

        # Match by normalized name
        norm = normalize_name(pname)
        if norm in self.name_to_sleeper:
            return self.name_to_sleeper[norm]

        # Fallback to namespaced ESPN ID if completely unknown
        return f"espn_{eid}" if eid else f"unknown_{pname}"

    async def get_raw_league_data(self) -> Dict[str, Any]:
        """Fetch all required views from ESPN Fantasy API."""
        if not self.league_id:
            return {}
        url = (
            f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{self.season}/"
            f"segments/0/leagues/{self.league_id}"
            f"?view=mSettings&view=mTeam&view=mRoster&view=mMatchup"
        )
        try:
            resp = await self.client.get(url, headers=self._get_headers())
            if resp.status_code == 401:
                logger.error("ESPN API 401 Unauthorized: Private league requires espn_s2 and SWID cookies.")
                return {}
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Failed to fetch ESPN league {self.league_id}: {e}")
            return {}

    async def get_league_bundle(
        self, week: int, season: Optional[str] = None
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Fetch ESPN league data and translate into Sleeper-compatible structures:
        Returns (league_info, users, rosters, raw_matchups).
        """
        if season:
            self.season = str(season).strip() if (season and str(season).strip() != "auto") else CURRENT_SEASON
        elif not self.season:
            self.season = CURRENT_SEASON

        # Re-index if player cache was refreshed
        if not self.name_to_sleeper and PLAYERS_CACHE_FILE.exists():
            self._load_player_index()

        raw = await self.get_raw_league_data()
        if not raw:
            return {}, [], [], []

        settings = raw.get("settings", {})
        members = raw.get("members", [])
        teams = raw.get("teams", [])
        schedule = raw.get("schedule", [])
        current_period = raw.get("scoringPeriodId") or week

        # 1. League Info & Scoring Settings
        scoring_settings: Dict[str, float] = {}
        for item in settings.get("scoringSettings", {}).get("scoringItems", []):
            sid = item.get("statId")
            pts = item.get("points")
            if sid in ESPN_STAT_MAP and pts is not None:
                scoring_settings[ESPN_STAT_MAP[sid]] = float(pts)

        league_info = {
            "league_id": str(self.league_id),
            "name": settings.get("name", "ESPN Fantasy League"),
            "total_rosters": len(teams),
            "season": str(self.season),
            "status": "in_season",
            "scoring_settings": scoring_settings,
        }

        # 2. Users (Members)
        members_map: Dict[str, Dict[str, Any]] = {}
        users: List[Dict[str, Any]] = []
        for m in members:
            mid = str(m.get("id", ""))
            first = m.get("firstName", "")
            last = m.get("lastName", "")
            dname = m.get("displayName") or f"{first} {last}".strip() or f"Manager {mid}"
            user_dict = {
                "user_id": mid,
                "display_name": dname,
                "avatar": None,
                "metadata": {"team_name": dname},
            }
            members_map[mid] = user_dict
            users.append(user_dict)

        # 3. Rosters & Teams
        rosters: List[Dict[str, Any]] = []
        team_starters_map: Dict[int, List[str]] = {}
        team_players_map: Dict[int, List[str]] = {}

        for t in teams:
            tid = int(t.get("id", 0))
            owner_id = str(t.get("primaryOwner") or (t.get("owners", [""])[0] if t.get("owners") else f"owner_{tid}"))
            t_name = t.get("name") or f"{t.get('location', '')} {t.get('nickname', '')}".strip() or f"Team {tid}"
            logo_url = t.get("logo")

            # Extract roster players and active starters
            entries = t.get("roster", {}).get("entries", [])
            all_players: List[str] = []
            starters: List[str] = []

            for entry in entries:
                p_obj = entry.get("playerPoolEntry", {}).get("player", {})
                slot_id = entry.get("lineupSlotId", 20)  # 20 = Bench, 21 = IR
                sleeper_id = self.map_espn_player_to_sleeper(p_obj)
                all_players.append(sleeper_id)

                # Starter slots are 0-19 and 23 (FLEX)
                if slot_id not in (20, 21):
                    starters.append(sleeper_id)

            team_starters_map[tid] = starters
            team_players_map[tid] = all_players

            # If user exists in members, attach team name
            if owner_id in members_map:
                members_map[owner_id]["metadata"]["team_name"] = t_name
                if logo_url and not members_map[owner_id]["avatar"]:
                    members_map[owner_id]["avatar"] = logo_url

            rosters.append({
                "roster_id": tid,
                "owner_id": owner_id,
                "league_id": str(self.league_id),
                "players": all_players,
                "starters": starters,
                "metadata": {
                    "team_name": t_name,
                    "avatar": logo_url,
                },
            })

        # 4. Weekly Matchups
        target_week = week or current_period
        raw_matchups: List[Dict[str, Any]] = []
        matchup_idx = 1

        for match in schedule:
            m_period = match.get("matchupPeriodId")
            if m_period != target_week:
                continue

            m_id = match.get("id", matchup_idx)
            matchup_idx += 1

            home = match.get("home") or {}
            away = match.get("away") or {}

            if home and home.get("teamId"):
                h_tid = int(home["teamId"])
                raw_matchups.append({
                    "roster_id": h_tid,
                    "matchup_id": m_id,
                    "starters": team_starters_map.get(h_tid, []),
                    "players": team_players_map.get(h_tid, []),
                    "custom_points": home.get("totalPoints"),
                })

            if away and away.get("teamId"):
                a_tid = int(away["teamId"])
                raw_matchups.append({
                    "roster_id": a_tid,
                    "matchup_id": m_id,
                    "starters": team_starters_map.get(a_tid, []),
                    "players": team_players_map.get(a_tid, []),
                    "custom_points": away.get("totalPoints"),
                })

        logger.info(
            f"Successfully processed ESPN league '{league_info['name']}': "
            f"{len(rosters)} teams, {len(raw_matchups)} matchup entries for Week {target_week}."
        )
        return league_info, users, rosters, raw_matchups
