import asyncio
import uuid
import time
import random
import logging
from typing import List, Dict, Optional, Any, Tuple, Set

from src.models import (
    HUDState, MatchupData, TeamScore, PlayerInfo,
    HighlightEvent, IdleSpotlight, DisplaySettings, InjuryAlertEvent
)
from src.sleeper_client import SleeperClient
from src.espn_client import ESPNFantasyClient
from src.nfl_game_tracker import NFLGameTracker
from src.ws_manager import ConnectionManager
from src.config import (
    LEAGUE_ID, TEAM_NAME, HIGHLIGHT_THRESHOLD,
    HIGHLIGHT_DISPLAY_SECONDS, MANAGER_COLORS, COLOR_FREE_AGENT, DEFAULT_PALETTE,
    FANTASY_PLATFORM, ESPN_LEAGUE_ID, ESPN_SEASON, ESPN_S2, ESPN_SWID, CURRENT_SEASON
)

logger = logging.getLogger("src.state_engine")


def calculate_fantasy_points(stats: Dict[str, Any], rules: Dict[str, float]) -> float:
    """Calculate fantasy points for player stats using league scoring settings."""
    if not stats:
        return 0.0
    pts = 0.0
    if rules:
        for stat_k, mult in rules.items():
            if stat_k in stats:
                try:
                    pts += float(stats[stat_k]) * float(mult)
                except (ValueError, TypeError):
                    pass
    if pts == 0.0:
        pts = stats.get("pts_ppr") or stats.get("pts_half_ppr") or stats.get("pts_std") or 0.0
    return round(float(pts), 2)

def resolve_avatar_url(raw_val: Optional[Any]) -> Optional[str]:
    """
    Resolve Sleeper avatar string, upload URL, or hash to full high-res avatar URL.
    Handles:
    - Direct image URLs (e.g., custom uploaded team avatars: https://sleepercdn.com/uploads/...)
    - Sleeper avatar hash/ID strings (e.g., 4f9417c504f57a8ebfb9588586f8d5c3) -> https://sleepercdn.com/avatars/{hash}
    """
    if not raw_val:
        return None
    val = str(raw_val).strip()
    if not val or val.lower() in ('none', 'null', 'undefined'):
        return None
    if val.startswith('http://') or val.startswith('https://'):
        return val
    return f'https://sleepercdn.com/avatars/{val}'



class HUDStateEngine:
    """
    Central orchestration engine for NFL Fantasy Live Game HUD.
    Maintains active matchup trees, player points history, delta detections,
    live in-game injury alerts for owned players, position-by-position active
    roster players rotation (starters and bench), and multi-matchup display modes.
    """

    def __init__(self, ws_manager: ConnectionManager):
        self.ws_manager = ws_manager
        self.platform: str = FANTASY_PLATFORM
        self.sleeper = SleeperClient()
        self.espn = ESPNFantasyClient(
            league_id=ESPN_LEAGUE_ID,
            season=ESPN_SEASON,
            espn_s2=ESPN_S2,
            swid=ESPN_SWID
        )
        self.nfl_tracker = NFLGameTracker()

        self.current_state: Optional[HUDState] = None
        self.prev_player_points: Dict[str, float] = {}  # pid -> last seen points
        self.prev_player_stats: Dict[str, Dict[str, Any]] = {}
        self.prev_injury_statuses: Dict[str, str] = {}  # pid -> last known injury status ("Healthy", "Questionable", "Out", etc.)
        self.highlight_queue: List[HighlightEvent] = []
        self.injury_queue: List[InjuryAlertEvent] = []
        self.is_bootstrapped: bool = False
        self.user_team_name: str = TEAM_NAME.lower()
        self.player_to_roster: Dict[str, Dict[str, Any]] = {}
        self.rosters_map: Dict[int, Dict[str, Any]] = {}
        self.starters_set: Set[str] = set()

        # Multi-Tier In-Memory Cache Fingerprints (Avoids rebuilding manager & roster dicts on unchanged ticks)
        self._cached_users_fingerprint: Optional[int] = None
        self._cached_rosters_fingerprint: Optional[int] = None
        self._cached_roster_players_map: Dict[int, List[str]] = {}

        # Multi-Matchup Display & Animation Settings
        # Default: normal (10s cycle for Spotlight, Highlights, and Matchup Shifts)
        self.display_settings = DisplaySettings(
            mode="auto",
            speed="normal",
            step_interval_seconds=10,
            ticker_speed=35,
            highlights_enabled=True,
            sound_enabled=True,
            sound_theme="fox_horn",
            injuries_enabled=True,
            injury_sound_enabled=True,
            injury_sound_theme="whistle_blow"
        )

        # Simulation & Testing
        self.simulation_mode: bool = False
        self.mock_league_active: bool = False
        self.week_override: Optional[int] = None
        self.mock_redzone_overrides: Dict[Tuple[int, str], Tuple[int, List[str]]] = {}
        self.mock_minutes_overrides: Dict[Tuple[int, str], float] = {}

    async def initialize(self):
        """Bootstrap player database and initial matchup state before start."""
        logger.info("Bootstrap: verifying NFL players cache...")
        await self.sleeper.ensure_players_cache()
        if hasattr(self, "espn"):
            self.espn._load_player_index()
        logger.info("Bootstrap: loading newest manager avatars, team rosters, and live league state...")
        await self.refresh_state(is_initial=True)
        self.is_bootstrapped = True
        mgr_count = len(self.rosters_map) if self.rosters_map else 0
        l_name = self.current_state.league_name if self.current_state else "Unknown"
        logger.info(f"HUD State Engine successfully initialized. Loaded {mgr_count} managers with newest avatars for '{l_name}'.")

    def set_week(self, week: Optional[int]):
        """Override active game week for testing."""
        self.week_override = week
        self.mock_league_active = False
        logger.info(f"Week override set to: {week}")

    def set_league_id(
        self,
        league_id: str,
        platform: Optional[str] = None,
        season: Optional[str] = None,
        espn_s2: Optional[str] = None,
        espn_swid: Optional[str] = None
    ):
        """Dynamically switch active League ID and Platform (Sleeper or ESPN)."""
        if platform:
            self.platform = platform.lower().strip()
        cleaned_id = str(league_id).strip()
        if self.platform == "espn":
            self.espn.update_credentials(
                league_id=cleaned_id,
                season=season,
                espn_s2=espn_s2,
                swid=espn_swid
            )
            logger.info(f"Switched to ESPN League ID: {cleaned_id} (season: {self.espn.season})")
        else:
            self.sleeper.league_id = cleaned_id
            self.sleeper.clear_cache(cleaned_id)
            logger.info(f"Switched to Sleeper League ID: {cleaned_id}")

        self.mock_league_active = False
        self.league_meta_cache = {}
        self._cached_users_fingerprint = None
        self._cached_rosters_fingerprint = None
        self._cached_roster_players_map = {}
        self.prev_player_points = {}
        self.prev_player_stats = {}
        self.prev_injury_statuses = {}
        self.highlight_queue.clear()
        self.injury_queue.clear()
        self.starters_set.clear()
        self.clear_mock_overrides()

    def get_speed_seconds(self) -> int:
        """Return interval in seconds for the current speed preset."""
        if self.display_settings.speed == "slow":
            return 20
        elif self.display_settings.speed == "fast":
            return 5
        return 10  # normal

    def set_display_settings(
        self,
        mode: Optional[str] = None,
        speed: Optional[str] = None,
        interval: Optional[int] = None,
        ticker_speed: Optional[int] = None,
        highlights_enabled: Optional[bool] = None,
        sound_enabled: Optional[bool] = None,
        sound_theme: Optional[str] = None,
        injuries_enabled: Optional[bool] = None,
        injury_sound_enabled: Optional[bool] = None,
        injury_sound_theme: Optional[str] = None
    ) -> DisplaySettings:
        """Update display mode, animation speed, highlight and injury alert parameters."""
        if mode in ["auto", "ticker", "step", "paged"]:
            self.display_settings.mode = "step" if mode == "paged" else mode
        
        if speed in ["normal", "fast", "slow"]:
            self.display_settings.speed = speed
            if speed == "fast":
                self.display_settings.step_interval_seconds = 5
                self.display_settings.ticker_speed = 65
            elif speed == "slow":
                self.display_settings.step_interval_seconds = 20
                self.display_settings.ticker_speed = 18
            else:  # normal
                self.display_settings.step_interval_seconds = 10
                self.display_settings.ticker_speed = 35

        if interval and interval >= 3:
            self.display_settings.step_interval_seconds = interval
        if ticker_speed and ticker_speed >= 10:
            self.display_settings.ticker_speed = ticker_speed
        if highlights_enabled is not None:
            self.display_settings.highlights_enabled = highlights_enabled
        if sound_enabled is not None:
            self.display_settings.sound_enabled = sound_enabled
        if sound_theme in ["fox_horn", "redzone", "td_siren", "brass_fanfare"]:
            self.display_settings.sound_theme = sound_theme
        if injuries_enabled is not None:
            self.display_settings.injuries_enabled = injuries_enabled
        if injury_sound_enabled is not None:
            self.display_settings.injury_sound_enabled = injury_sound_enabled
        if injury_sound_theme in ["whistle_blow", "buzzer_flat", "flatline", "record_scratch"]:
            self.display_settings.injury_sound_theme = injury_sound_theme

        logger.info(f"Display settings updated: {self.display_settings.model_dump()}")
        return self.display_settings

    def toggle_simulation(self, enable: Optional[bool] = None) -> bool:
        """Toggle or set simulation mode."""
        if enable is None:
            self.simulation_mode = not self.simulation_mode
        else:
            self.simulation_mode = enable
        logger.info(f"Simulation mode is now: {self.simulation_mode}")
        return self.simulation_mode

    def generate_mock_league(self, teams_count: int = 12) -> HUDState:
        """Generate a realistic mock league with any team size (6, 8, 10, 12, 14, 16)."""
        self.mock_league_active = True
        num_matchups = teams_count // 2
        
        # Maximally distinct glowy neon colors with zero lookalike tones
        managers = [
            ("Cyber Blitz", "#00f0ff", "https://sleepercdn.com/images/v2/icons/player_default.webp"),
            ("Neon Titans", "#ff00aa", "https://sleepercdn.com/images/v2/icons/player_default.webp"),
            ("Quantum Knights", "#a855f7", "https://sleepercdn.com/images/v2/icons/player_default.webp"),
            ("Golden Strikers", "#ffaa00", "https://sleepercdn.com/images/v2/icons/player_default.webp"),
            ("Emerald Vipers", "#00e676", "https://sleepercdn.com/images/v2/icons/player_default.webp"),
            ("Crimson Phoenix", "#ef4444", "https://sleepercdn.com/images/v2/icons/player_default.webp"),
            ("Thunderbolts", "#387aff", "https://sleepercdn.com/images/v2/icons/player_default.webp"),
            ("GridironKings", "#a3e635", "https://sleepercdn.com/images/v2/icons/player_default.webp"),
            ("VortexRiders", "#ff6b00", "https://sleepercdn.com/images/v2/icons/player_default.webp"),
            ("BlizzardBlitz", "#00f5d4", "https://sleepercdn.com/images/v2/icons/player_default.webp"),
            ("ApexPredators", "#facc15", "https://sleepercdn.com/images/v2/icons/player_default.webp"),
            ("PhantomForce", "#6366f1", "https://sleepercdn.com/images/v2/icons/player_default.webp"),
            ("RedlineDynasty", "#e024c3", "https://sleepercdn.com/images/v2/icons/player_default.webp"),
            ("TitaniumTacklers", "#14b8a6", "https://sleepercdn.com/images/v2/icons/player_default.webp"),
            ("SolarFlares", "#f43f8e", "https://sleepercdn.com/images/v2/icons/player_default.webp"),
            ("IronClad", "#94a3b8", "https://sleepercdn.com/images/v2/icons/player_default.webp"),
        ]

        matchup_models = []
        for i in range(num_matchups):
            m_id = i + 1
            idx_a = (i * 2) % len(managers)
            idx_b = (i * 2 + 1) % len(managers)
            
            m_a = managers[idx_a]
            m_b = managers[idx_b]
            
            pts_a = round(random.uniform(90.0, 165.0), 1)
            pts_b = round(random.uniform(90.0, 165.0), 1)

            # Test presets for minutes and red zone to demonstrate features clearly
            if i == 0:
                # Matchup 1: In progress with 1 Red Zone on Team A
                min_a, rz_a, rz_pls_a = 380.0, 1, ["Josh Allen"]
                min_b, rz_b, rz_pls_b = 270.0, 0, []
            elif i == 1:
                # Matchup 2: Both teams finished all minutes (meet in center at 50% / 50%)
                min_a, rz_a, rz_pls_a = 540.0, 0, []
                min_b, rz_b, rz_pls_b = 540.0, 0, []
            elif i == 2:
                # Matchup 3: Team A has 2 Red Zone players, Team B has 4 (badge '3+')
                min_a, rz_a, rz_pls_a = 195.0, 2, ["Justin Jefferson", "Saquon Barkley"]
                min_b, rz_b, rz_pls_b = 135.0, 4, ["Trey McBride", "CeeDee Lamb", "Lamar Jackson", "Jonathan Taylor"]
            else:
                min_a = round(random.uniform(60.0, 520.0), 1)
                min_b = round(random.uniform(60.0, 520.0), 1)
                rz_a = random.choice([0, 0, 1, 2, 3])
                rz_pls_a = [f"Star {x+1}" for x in range(rz_a)]
                rz_b = random.choice([0, 0, 0, 1])
                rz_pls_b = [f"Star {x+1}" for x in range(rz_b)]

            pct_a = round((min_a / 540.0) * 100.0, 1)
            pct_b = round((min_b / 540.0) * 100.0, 1)

            t_a = TeamScore(
                roster_id=idx_a + 1,
                owner_id=f"user_{idx_a}",
                team_name=m_a[0],
                manager_name=m_a[0],
                avatar_url=m_a[2],
                points=pts_a,
                starters_count=9,
                minutes_played=min_a,
                total_minutes=540.0,
                time_played_pct=pct_a,
                redzone_count=rz_a,
                redzone_players=rz_pls_a,
                is_user_team=(m_a[0].lower() == self.user_team_name),
                color_accent=m_a[1]
            )

            t_b = TeamScore(
                roster_id=idx_b + 1,
                owner_id=f"user_{idx_b}",
                team_name=m_b[0],
                manager_name=m_b[0],
                avatar_url=m_b[2],
                points=pts_b,
                starters_count=9,
                minutes_played=min_b,
                total_minutes=540.0,
                time_played_pct=pct_b,
                redzone_count=rz_b,
                redzone_players=rz_pls_b,
                is_user_team=(m_b[0].lower() == self.user_team_name),
                color_accent=m_b[1]
            )

            diff = round(abs(pts_a - pts_b), 1)
            leader_id = (idx_a + 1) if pts_a >= pts_b else (idx_b + 1)

            matchup_models.append(MatchupData(
                matchup_id=m_id,
                team_a=t_a,
                team_b=t_b,
                diff=diff,
                leader_roster_id=leader_id,
                win_probability_a=round(50 + (pts_a - pts_b) * 1.5, 1)
            ))

        mock_spotlights = [
            IdleSpotlight(
                player_id="4984",
                player_name="Josh Allen",
                position="QB",
                nfl_team="BUF",
                fantasy_team_name="Cyber Blitz",
                manager_name="Cyber Blitz",
                points=34.6,
                headshot_url="https://sleepercdn.com/content/nfl/players/4984.jpg",
                title="👑 #1 QB · CYBER BLITZ",
                color_accent="#00f0ff",
                is_free_agent=False,
                is_starter=True,
                roster_slot="STARTER",
                rank=1
            ),
            IdleSpotlight(
                player_id="4881",
                player_name="Lamar Jackson",
                position="QB",
                nfl_team="BAL",
                fantasy_team_name="Neon Titans",
                manager_name="Neon Titans",
                points=28.4,
                headshot_url="https://sleepercdn.com/content/nfl/players/4881.jpg",
                title="#2 QB · NEON TITANS",
                color_accent="#ff00aa",
                is_free_agent=False,
                is_starter=True,
                roster_slot="STARTER",
                rank=2
            ),
            IdleSpotlight(
                player_id="6813",
                player_name="Jonathan Taylor",
                position="RB",
                nfl_team="IND",
                fantasy_team_name="Neon Titans",
                manager_name="Neon Titans",
                points=29.4,
                headshot_url="https://sleepercdn.com/content/nfl/players/6813.jpg",
                title="👑 #1 RB · NEON TITANS",
                color_accent="#ff00aa",
                is_free_agent=False,
                is_starter=True,
                roster_slot="STARTER",
                rank=1
            ),
            IdleSpotlight(
                player_id="9226",
                player_name="Bijan Robinson",
                position="RB",
                nfl_team="ATL",
                fantasy_team_name="Cyber Blitz",
                manager_name="Cyber Blitz",
                points=22.4,
                headshot_url="https://sleepercdn.com/content/nfl/players/9226.jpg",
                title="#2 RB · CYBER BLITZ",
                color_accent="#00f0ff",
                is_free_agent=False,
                is_starter=False,
                roster_slot="BENCH",
                rank=2
            ),
            IdleSpotlight(
                player_id="6794",
                player_name="Justin Jefferson",
                position="WR",
                nfl_team="MIN",
                fantasy_team_name="Quantum Knights",
                manager_name="Quantum Knights",
                points=27.2,
                headshot_url="https://sleepercdn.com/content/nfl/players/6794.jpg",
                title="👑 #1 WR · QUANTUM KNIGHTS",
                color_accent="#a855f7",
                is_free_agent=False,
                is_starter=True,
                roster_slot="STARTER",
                rank=1
            ),
            IdleSpotlight(
                player_id="6786",
                player_name="CeeDee Lamb",
                position="WR",
                nfl_team="DAL",
                fantasy_team_name="Cyber Blitz",
                manager_name="Cyber Blitz",
                points=18.6,
                headshot_url="https://sleepercdn.com/content/nfl/players/6786.jpg",
                title="#2 WR · CYBER BLITZ",
                color_accent="#00f0ff",
                is_free_agent=False,
                is_starter=False,
                roster_slot="BENCH",
                rank=2
            ),
            IdleSpotlight(
                player_id="1466",
                player_name="Travis Kelce",
                position="TE",
                nfl_team="KC",
                fantasy_team_name="Golden Strikers",
                manager_name="Golden Strikers",
                points=19.8,
                headshot_url="https://sleepercdn.com/content/nfl/players/1466.jpg",
                title="👑 #1 TE · GOLDEN STRIKERS",
                color_accent="#ffaa00",
                is_free_agent=False,
                is_starter=True,
                roster_slot="STARTER",
                rank=1
            ),
            IdleSpotlight(
                player_id="11533",
                player_name="Brandon Aubrey",
                position="K",
                nfl_team="DAL",
                fantasy_team_name="Cyber Blitz",
                manager_name="Cyber Blitz",
                points=15.0,
                headshot_url="https://sleepercdn.com/content/nfl/players/11533.jpg",
                title="👑 #1 K · CYBER BLITZ",
                color_accent="#00f0ff",
                is_free_agent=False,
                is_starter=True,
                roster_slot="STARTER",
                rank=1
            ),
            IdleSpotlight(
                player_id="MIN",
                player_name="Minnesota Vikings",
                position="DEF",
                nfl_team="MIN",
                fantasy_team_name="Emerald Vipers",
                manager_name="Emerald Vipers",
                points=18.0,
                headshot_url="https://sleepercdn.com/images/team_logos/nfl/min.png",
                title="👑 #1 DEF · EMERALD VIPERS",
                color_accent="#00e676",
                is_free_agent=False,
                is_starter=True,
                roster_slot="STARTER",
                rank=1
            )
        ]

        active_id = str(self.espn.league_id) if self.platform == "espn" else str(self.sleeper.league_id)
        self.current_state = HUDState(
            platform=self.platform,
            league_id=active_id,
            league_name=f"Mock {teams_count}-Team League",
            season=CURRENT_SEASON,
            week=3,
            is_live=True,
            last_updated=time.time(),
            matchups=matchup_models,
            highlight_queue=self.highlight_queue[-5:],
            injury_queue=self.injury_queue[-5:],
            idle_spotlight=mock_spotlights[0],
            idle_spotlights=mock_spotlights,
            active_connections=self.ws_manager.count,
            simulation_mode=True,
            display_settings=self.display_settings
        )
        return self.current_state

    async def refresh_state(self, is_initial: bool = False) -> HUDState:
        """Fetch latest live data from Sleeper and NFL APIs, compute score deltas, and detect live injuries."""
        if self.mock_league_active and self.current_state:
            return self.current_state

        try:
            # 1. Fetch current NFL State (utilizing 60s in-memory TTL)
            nfl_state = await self.sleeper.get_nfl_state(force_refresh=is_initial)
            current_week = self.week_override if self.week_override is not None else nfl_state.get("week", 1)
            season_type = nfl_state.get("season_type", "regular")
            season = (self.espn.season if (self.platform == "espn" and self.espn.season) else None) or nfl_state.get("season") or CURRENT_SEASON

            # 2. Concurrently fetch League, Users, Rosters, Matchups, Weekly Stats, ESPN Scoreboard, and ESPN Injuries
            # Note: league_info, users, and rosters resolve from in-memory cache in 0ms when fresh
            if self.platform == "espn":
                (league_info, users, rosters, raw_matchups), weekly_stats, _, espn_injuries = await asyncio.gather(
                    self.espn.get_league_bundle(current_week, season=season),
                    self.sleeper.get_weekly_stats(season=season, week=current_week, season_type=season_type),
                    self.nfl_tracker.fetch_scoreboard(),
                    self.nfl_tracker.fetch_injuries()
                )
            else:
                league_info, users, rosters, raw_matchups, weekly_stats, _, espn_injuries = await asyncio.gather(
                    self.sleeper.get_league_info(force_refresh=is_initial),
                    self.sleeper.get_league_users(force_refresh=is_initial),
                    self.sleeper.get_league_rosters(force_refresh=is_initial),
                    self.sleeper.get_matchups(current_week),
                    self.sleeper.get_weekly_stats(season=season, week=current_week, season_type=season_type),
                    self.nfl_tracker.fetch_scoreboard(),
                    self.nfl_tracker.fetch_injuries()
                )
            scoring_settings = league_info.get("scoring_settings", {}) if isinstance(league_info, dict) else {}

            # Fast-path: Check if users and rosters match cached fingerprints
            users_fp = id(users)
            rosters_fp = id(rosters)
            if (
                users_fp != self._cached_users_fingerprint
                or rosters_fp != self._cached_rosters_fingerprint
                or not self.rosters_map
            ):
                users_map: Dict[str, Dict[str, str]] = {}
                for u in (users or []):
                    uid = u.get("user_id")
                    meta = u.get("metadata") or {}
                    dname = meta.get("team_name") or u.get("display_name") or f"Manager {uid}"
                    avatar_url = (
                        resolve_avatar_url(meta.get("avatar"))
                        or resolve_avatar_url(u.get("avatar"))
                        or "https://sleepercdn.com/images/v2/icons/player_default.webp"
                    )
                    users_map[uid] = {
                        "manager_name": u.get("display_name", dname),
                        "team_name": dname,
                        "avatar_url": avatar_url
                    }

                rosters_map: Dict[int, Dict[str, Any]] = {}
                roster_players_map: Dict[int, List[str]] = {}
                player_to_roster: Dict[str, Dict[str, Any]] = {}
                starters_set_all: Set[str] = set()

                for idx, r in enumerate(rosters or []):
                    rid = r.get("roster_id")
                    oid = r.get("owner_id")
                    r_meta = r.get("metadata") or {}
                    u_info = users_map.get(oid, {
                        "manager_name": f"Team {rid}",
                        "team_name": f"Team {rid}",
                        "avatar_url": "https://sleepercdn.com/images/v2/icons/player_default.webp"
                    })

                    roster_avatar = resolve_avatar_url(r_meta.get("avatar"))
                    avatar_url = roster_avatar or u_info["avatar_url"]
                    team_name = r_meta.get("team_name") or u_info["team_name"]
                    manager_name = u_info["manager_name"]

                    mgr_lower = manager_name.lower()
                    team_lower = team_name.lower()
                    is_user_team = (mgr_lower == self.user_team_name) or (team_lower == self.user_team_name)

                    # Determine color accent
                    color = None
                    for key, val in MANAGER_COLORS.items():
                        if key.lower() == mgr_lower or key.lower() == team_lower:
                            color = val
                            break
                    if not color:
                        if is_user_team:
                            color = "#00f0ff"
                        else:
                            r_idx = (rid - 1) if (isinstance(rid, int) and rid > 0) else idx
                            color = DEFAULT_PALETTE[r_idx % len(DEFAULT_PALETTE)]

                    r_dict = {
                        "roster_id": rid,
                        "owner_id": oid or "",
                        "manager_name": manager_name,
                        "team_name": team_name,
                        "avatar_url": avatar_url,
                        "is_user_team": is_user_team,
                        "color_accent": color
                    }
                    rosters_map[rid] = r_dict

                    r_starters = set(str(pid) for pid in (r.get("starters") or []))
                    starters_set_all.update(r_starters)

                    r_pids = [str(pid) for pid in (r.get("players") or [])]
                    roster_players_map[rid] = r_pids
                    for pid in r_pids:
                        is_st = pid in r_starters
                        player_to_roster[str(pid)] = {
                            **r_dict,
                            "is_starter": is_st,
                            "roster_slot": "STARTER" if is_st else "BENCH"
                        }

                self._cached_users_fingerprint = users_fp
                self._cached_rosters_fingerprint = rosters_fp
                self._cached_roster_players_map = roster_players_map
                self.rosters_map = rosters_map
                self.player_to_roster = player_to_roster
                self.starters_set = starters_set_all
            else:
                rosters_map = self.rosters_map
                roster_players_map = self._cached_roster_players_map
                player_to_roster = self.player_to_roster
                starters_set_all = self.starters_set

            # Group matchups by matchup_id
            matchup_groups: Dict[int, List[Dict[str, Any]]] = {}
            for m in raw_matchups:
                mid = m.get("matchup_id")
                if mid is not None:
                    matchup_groups.setdefault(mid, []).append(m)

            matchup_models: List[MatchupData] = []
            duration_sec = self.get_speed_seconds()
            new_highlights: List[HighlightEvent] = []
            new_injuries: List[InjuryAlertEvent] = []

            # Track active players per position across all fantasy managers
            active_by_position: Dict[str, List[Dict[str, Any]]] = {}
            pregame_starters_by_pos: Dict[str, List[Dict[str, Any]]] = {}

            # Process all matchups
            for mid, m_list in matchup_groups.items():
                teams: List[TeamScore] = []
                for m_entry in m_list:
                    rid = m_entry.get("roster_id")
                    r_meta = rosters_map.get(rid, {
                        "roster_id": rid,
                        "owner_id": "",
                        "manager_name": f"Team {rid}",
                        "team_name": f"Team {rid}",
                        "avatar_url": "https://sleepercdn.com/images/v2/icons/player_default.webp",
                        "is_user_team": False,
                        "color_accent": "#00f0ff"
                    })

                    total_points = float(m_entry.get("points") or 0.0)
                    starters = [str(s) for s in (m_entry.get("starters") or [])]
                    starters_set = set(starters)
                    players_pts = m_entry.get("players_points") or {}

                    starters_detail: List[PlayerInfo] = []
                    starters_played_count = 0
                    starters_in_progress_count = 0
                    total_minutes_played = 0.0
                    redzone_players: List[str] = []

                    # 1. Process Starters for matchup scorecard, minutes, and red zone
                    for pid in starters:
                        p_info = self.sleeper.get_player_info(str(pid))
                        pts = float(players_pts.get(str(pid), 0.0))
                        team_abbr = p_info["team"]

                        game_info = self.nfl_tracker.get_game_for_team(team_abbr)
                        status = "pre"
                        clock = ""
                        progress_pct = 0.0
                        minutes_elapsed = 0.0
                        is_redzone = False

                        if game_info:
                            status = game_info.status
                            clock = game_info.clock
                            progress_pct = game_info.progress_pct
                            minutes_elapsed = getattr(game_info, "minutes_elapsed", 0.0)
                            # Red zone alert: active offensive starters whose NFL team is in Red Zone
                            def_positions = {"DEF", "D/ST", "DL", "LB", "DB", "DE", "DT", "CB", "S", "SS", "FS", "P"}
                            pos_upper = p_info.get("position", "").upper()
                            if pos_upper and pos_upper not in def_positions:
                                is_redzone = getattr(game_info, "is_redzone", False)

                        if status == "in":
                            starters_in_progress_count += 1
                        elif status == "post":
                            starters_played_count += 1

                        total_minutes_played += minutes_elapsed
                        if is_redzone:
                            redzone_players.append(p_info["name"])

                        # Determine starter injury status from live ESPN injuries
                        p_norm = p_info["name"].lower().strip()
                        p_t_norm = (team_abbr or "").lower().strip()
                        espn_rec = espn_injuries.get(f"{p_norm}_{p_t_norm}") or espn_injuries.get(p_norm)
                        starter_inj_status = "Healthy"
                        if espn_rec:
                            st = espn_rec.get("status", "")
                            if st.lower() in ["questionable", "out", "doubtful", "injured reserve", "ir"]:
                                starter_inj_status = st

                        player_model = PlayerInfo(
                            player_id=str(pid),
                            name=p_info["name"],
                            position=p_info["position"],
                            team=team_abbr,
                            injury_status=starter_inj_status,
                            points=pts,
                            game_status=status,
                            game_clock=clock,
                            game_progress_pct=progress_pct,
                            minutes_played=round(minutes_elapsed, 1),
                            is_redzone=is_redzone,
                            headshot_url=p_info["headshot_url"]
                        )
                        starters_detail.append(player_model)

                    # 2. Process ALL rostered players (starters + bench)
                    roster_all_pids = [str(p) for p in (m_entry.get("players") or roster_players_map.get(rid, []))]
                    combined_pids = list(starters)
                    for pid in roster_all_pids:
                        if pid not in starters_set:
                            combined_pids.append(pid)

                    for pid in combined_pids:
                        pts = float(players_pts.get(str(pid), 0.0))
                        p_info = self.sleeper.get_player_info(str(pid))
                        pos = p_info.get("position", "FA")
                        is_starter = (pid in starters_set)
                        roster_slot = "STARTER" if is_starter else "BENCH"
                        p_stats = (weekly_stats.get(str(pid)) if weekly_stats else None) or (m_entry.get("players_stats") or {}).get(str(pid), {})

                        # Active players overview: Exclude players that haven't played (fpts == 0)
                        if round(pts, 2) != 0.0:
                            active_by_position.setdefault(pos, []).append({
                                "player_id": str(pid),
                                "player_name": p_info["name"],
                                "position": pos,
                                "nfl_team": p_info["team"],
                                "fantasy_team_name": r_meta["team_name"],
                                "manager_name": r_meta["manager_name"],
                                "points": round(pts, 2),
                                "headshot_url": p_info["headshot_url"],
                                "color_accent": r_meta["color_accent"],
                                "is_free_agent": False,
                                "is_starter": is_starter,
                                "roster_slot": roster_slot
                            })

                        # Collect starting players for pregame fallback
                        if is_starter:
                            pregame_starters_by_pos.setdefault(pos, []).append({
                                "player_id": str(pid),
                                "player_name": p_info["name"],
                                "position": pos,
                                "nfl_team": p_info["team"],
                                "fantasy_team_name": r_meta["team_name"],
                                "manager_name": r_meta["manager_name"],
                                "points": round(pts, 2),
                                "headshot_url": p_info["headshot_url"],
                                "color_accent": r_meta["color_accent"],
                                "is_free_agent": False,
                                "is_starter": True,
                                "roster_slot": "STARTER"
                            })

                        # Live In-Game Injury Detection for Owned Fantasy Players
                        p_norm = p_info["name"].lower().strip()
                        p_t_norm = (p_info.get("team") or "").lower().strip()
                        espn_inj_rec = espn_injuries.get(f"{p_norm}_{p_t_norm}") or espn_injuries.get(p_norm)
                        
                        live_inj_status = "Healthy"
                        live_inj_detail = ""
                        if espn_inj_rec:
                            raw_st = espn_inj_rec.get("status", "")
                            if raw_st.lower() in ["questionable", "out", "doubtful", "injured reserve", "ir"]:
                                live_inj_status = raw_st
                                live_inj_detail = espn_inj_rec.get("detail", raw_st)

                        prev_inj_status = self.prev_injury_statuses.get(str(pid), "Healthy")
                        if live_inj_status != prev_inj_status:
                            self.prev_injury_statuses[str(pid)] = live_inj_status
                            # If transitioned into an injured state (e.g. Questionable or Out) during live tracking
                            if self.is_bootstrapped and not is_initial and live_inj_status != "Healthy":
                                if self.display_settings.injuries_enabled:
                                    logger.info(f"🚑 INJURY DETECTED! {p_info['name']} ({roster_slot}) -> {live_inj_status} for {r_meta['manager_name']}")
                                    inj_accent = "#ef4444" if live_inj_status.lower() in ["out", "ir", "injured reserve"] else "#f59e0b"
                                    inj_event = InjuryAlertEvent(
                                        id=str(uuid.uuid4())[:8],
                                        player_id=str(pid),
                                        player_name=p_info["name"],
                                        position=pos,
                                        nfl_team=p_info["team"],
                                        fantasy_team_name=r_meta["team_name"],
                                        manager_name=r_meta["manager_name"],
                                        injury_status=live_inj_status,
                                        injury_detail=live_inj_detail,
                                        headshot_url=p_info["headshot_url"],
                                        color_accent=inj_accent,
                                        is_free_agent=False,
                                        duration_seconds=duration_sec,
                                        is_user_team=r_meta["is_user_team"],
                                        points=round(pts, 1),
                                        is_starter=is_starter,
                                        roster_slot=roster_slot
                                    )
                                    new_injuries.append(inj_event)
                                    self.injury_queue.append(inj_event)

                        # Delta check for Highlight Queue
                        if self.is_bootstrapped and not is_initial:
                            prev_pts = self.prev_player_points.get(str(pid), pts)
                            delta = pts - prev_pts
                            if delta >= HIGHLIGHT_THRESHOLD and self.display_settings.highlights_enabled:
                                logger.info(f"🔥 HIGHLIGHT DETECTED! {p_info['name']} ({roster_slot}) +{delta:.1f} FPTS for {r_meta['manager_name']}")
                                
                                cur_pstats = p_stats or {}
                                old_pstats = self.prev_player_stats.get(str(pid), {})
                                
                                td_keys = ["rush_td", "rec_td", "pass_td", "def_td", "td"]
                                has_td = any(
                                    float(cur_pstats.get(k, 0) or 0) > float(old_pstats.get(k, 0) or 0)
                                    for k in td_keys
                                )
                                if not has_td and delta >= 6.0 and pos in ["QB", "RB", "WR", "TE"] and not old_pstats:
                                    has_td = True

                                bench_suffix = " (Bench)" if not is_starter else ""
                                if has_td:
                                    hl_type = "touchdown"
                                    desc = f"Touchdown{bench_suffix} (+{round(delta, 1)} pts)"
                                elif pos == "K" or any(float(cur_pstats.get(k, 0) or 0) > float(old_pstats.get(k, 0) or 0) for k in ["fgm", "fgm_50p", "fgm_40_49"]):
                                    hl_type = "field_goal"
                                    desc = f"Field Goal{bench_suffix} (+{round(delta, 1)} pts)"
                                elif pos == "DEF":
                                    hl_type = "touchdown" if has_td else "def_stop"
                                    desc = f"{'Defensive TD' if has_td else 'Defensive Stop'}{bench_suffix} (+{round(delta, 1)} pts)"
                                else:
                                    hl_type = "big_play"
                                    desc = f"Big Play{bench_suffix} (+{round(delta, 1)} pts)"

                                highlight = HighlightEvent(
                                    id=str(uuid.uuid4())[:8],
                                    player_id=str(pid),
                                    player_name=p_info["name"],
                                    position=pos,
                                    nfl_team=p_info["team"],
                                    fantasy_team_name=r_meta["team_name"],
                                    manager_name=r_meta["manager_name"],
                                    delta_points=round(delta, 1),
                                    total_points=round(pts, 1),
                                    headshot_url=p_info["headshot_url"],
                                    color_accent=r_meta["color_accent"],
                                    is_free_agent=False,
                                    play_description=desc,
                                    duration_seconds=duration_sec,
                                    is_user_team=r_meta["is_user_team"],
                                    highlight_type=hl_type,
                                    is_touchdown=has_td,
                                    is_starter=is_starter,
                                    roster_slot=roster_slot
                                )
                                new_highlights.append(highlight)
                                self.highlight_queue.append(highlight)

                        # Update previous points tracking
                        self.prev_player_points[str(pid)] = pts
                        self.prev_player_stats[str(pid)] = p_stats or {}

                    # Calculate total minutes played & percentage across starting roster
                    starters_cnt = len(starters_detail) if starters_detail else 9
                    total_max_minutes = float(starters_cnt * 60)
                    time_pct = (total_minutes_played / total_max_minutes * 100.0) if total_max_minutes > 0 else 0.0

                    team_score = TeamScore(
                        roster_id=rid,
                        owner_id=r_meta["owner_id"],
                        team_name=r_meta["team_name"],
                        manager_name=r_meta["manager_name"],
                        avatar_url=r_meta["avatar_url"],
                        points=round(total_points, 2),
                        starters_count=len(starters_detail),
                        starters_played_count=starters_played_count,
                        starters_in_progress_count=starters_in_progress_count,
                        starters_yet_to_play_count=max(0, len(starters_detail) - starters_played_count - starters_in_progress_count),
                        minutes_played=round(total_minutes_played, 1),
                        total_minutes=total_max_minutes,
                        time_played_pct=round(time_pct, 1),
                        redzone_count=len(redzone_players),
                        redzone_players=redzone_players,
                        is_user_team=r_meta["is_user_team"],
                        color_accent=r_meta["color_accent"],
                        starters_detail=starters_detail
                    )
                    teams.append(team_score)

                if len(teams) >= 2:
                    t_a = teams[0]
                    t_b = teams[1]

                    # Apply persistent mock redzone overrides if any
                    if (mid, "a") in self.mock_redzone_overrides:
                        rz_c, rz_p = self.mock_redzone_overrides[(mid, "a")]
                        t_a.redzone_count = rz_c
                        t_a.redzone_players = rz_p
                    if (mid, "b") in self.mock_redzone_overrides:
                        rz_c, rz_p = self.mock_redzone_overrides[(mid, "b")]
                        t_b.redzone_count = rz_c
                        t_b.redzone_players = rz_p

                    # Apply persistent mock minutes overrides if any
                    if (mid, "a") in self.mock_minutes_overrides:
                        m_val = self.mock_minutes_overrides[(mid, "a")]
                        t_a.minutes_played = m_val
                        t_a.time_played_pct = round((m_val / t_a.total_minutes) * 100.0, 1) if t_a.total_minutes > 0 else 0.0
                    if (mid, "b") in self.mock_minutes_overrides:
                        m_val = self.mock_minutes_overrides[(mid, "b")]
                        t_b.minutes_played = m_val
                        t_b.time_played_pct = round((m_val / t_b.total_minutes) * 100.0, 1) if t_b.total_minutes > 0 else 0.0

                    diff = round(abs(t_a.points - t_b.points), 2)
                    leader = t_a.roster_id if t_a.points >= t_b.points else t_b.roster_id
                    
                    # Compute dynamic win probability
                    tot = t_a.points + t_b.points
                    win_prob = round((t_a.points / tot) * 100.0, 1) if tot > 0 else 50.0

                    matchup_models.append(MatchupData(
                        matchup_id=mid,
                        team_a=t_a,
                        team_b=t_b,
                        diff=diff,
                        leader_roster_id=leader,
                        win_probability_a=win_prob
                    ))
                elif len(teams) == 1:
                    matchup_models.append(MatchupData(
                        matchup_id=mid,
                        team_a=teams[0],
                        team_b=None,
                        diff=0.0,
                        leader_roster_id=teams[0].roster_id,
                        win_probability_a=100.0
                    ))

            # Build list of Active Players ordered position-by-position: QB -> RB -> WR -> TE -> K -> DEF
            idle_spotlights: List[IdleSpotlight] = []
            pos_order = ["QB", "RB", "WR", "TE", "K", "DEF"]

            for pos in pos_order:
                pos_players = [p for p in active_by_position.get(pos, []) if round(p.get("points", 0.0), 2) != 0.0]
                pos_players.sort(key=lambda p: p["points"], reverse=True)
                for rank, p in enumerate(pos_players, start=1):
                    crown = "👑 " if rank == 1 else ""
                    p_title = f"{crown}#{rank} {pos} · {p['manager_name'].upper()}"

                    idle_spotlights.append(IdleSpotlight(
                        player_id=p["player_id"],
                        player_name=p["player_name"],
                        position=p["position"],
                        nfl_team=p["nfl_team"],
                        fantasy_team_name=p["fantasy_team_name"],
                        manager_name=p["manager_name"],
                        points=p["points"],
                        headshot_url=p["headshot_url"],
                        title=p_title,
                        color_accent=p["color_accent"],
                        is_free_agent=False,
                        is_starter=p["is_starter"],
                        roster_slot=p["roster_slot"],
                        rank=rank
                    ))

            # Include any non-standard positions if present
            for pos, pos_raw in active_by_position.items():
                if pos not in pos_order:
                    pos_players = [p for p in pos_raw if round(p.get("points", 0.0), 2) != 0.0]
                    pos_players.sort(key=lambda p: p["points"], reverse=True)
                    for rank, p in enumerate(pos_players, start=1):
                        crown = "👑 " if rank == 1 else ""
                        p_title = f"{crown}#{rank} {pos} · {p['manager_name'].upper()}"

                        idle_spotlights.append(IdleSpotlight(
                            player_id=p["player_id"],
                            player_name=p["player_name"],
                            position=p["position"],
                            nfl_team=p["nfl_team"],
                            fantasy_team_name=p["fantasy_team_name"],
                            manager_name=p["manager_name"],
                            points=p["points"],
                            headshot_url=p["headshot_url"],
                            title=p_title,
                            color_accent=p["color_accent"],
                            is_free_agent=False,
                            is_starter=p["is_starter"],
                            roster_slot=p["roster_slot"],
                            rank=rank
                        ))

            active_id = str(self.espn.league_id) if self.platform == "espn" else str(self.sleeper.league_id)
            # Update Current State
            self.current_state = HUDState(
                platform=self.platform,
                league_id=active_id,
                league_name=league_info.get("name", "NFL Fantasy League"),
                season=league_info.get("season", season),
                week=current_week,
                is_live=(season_type == "regular"),
                last_updated=time.time(),
                matchups=matchup_models,
                highlight_queue=self.highlight_queue[-5:],
                injury_queue=self.injury_queue[-5:],
                idle_spotlight=idle_spotlights[0] if idle_spotlights else None,
                idle_spotlights=idle_spotlights,
                active_connections=self.ws_manager.count,
                simulation_mode=self.simulation_mode,
                display_settings=self.display_settings
            )

            # Broadcast new highlights if enabled and any occurred
            if self.display_settings.highlights_enabled:
                for hl in new_highlights:
                    await self.ws_manager.broadcast({
                        "type": "PUSH_HIGHLIGHT",
                        "highlight": hl.model_dump()
                    })

            # Broadcast new live injury alerts if enabled and any occurred
            if self.display_settings.injuries_enabled:
                for inj in new_injuries:
                    await self.ws_manager.broadcast({
                        "type": "PUSH_INJURY",
                        "injury": inj.model_dump()
                    })

            # Broadcast updated state
            await self.ws_manager.broadcast({
                "type": "UPDATE_MATCHUPS",
                "state": self.current_state.model_dump()
            })

            return self.current_state

        except Exception as e:
            logger.error(f"Failed to refresh HUD state: {e}", exc_info=True)
            raise e

    def set_mock_redzone(self, matchup_id: int, team_side: str, count: int, player_names: Optional[List[str]] = None) -> bool:
        """Dynamically set the Red Zone count on a matchup team for testing."""
        side_key = "a" if team_side.lower() in ["a", "team_a", "left"] else "b"
        p_names = player_names or [f"Player {i+1}" for i in range(count)]
        if count <= 0:
            self.mock_redzone_overrides.pop((matchup_id, side_key), None)
        else:
            self.mock_redzone_overrides[(matchup_id, side_key)] = (count, p_names)

        if self.current_state and self.current_state.matchups:
            for m in self.current_state.matchups:
                if m.matchup_id == matchup_id:
                    target_team = m.team_a if side_key == "a" else m.team_b
                    if target_team:
                        target_team.redzone_count = max(0, count)
                        target_team.redzone_players = p_names if count > 0 else []
                        return True
        return False

    def set_mock_minutes(self, matchup_id: int, team_side: str, minutes: float) -> bool:
        """Dynamically set minutes played on a matchup team for testing."""
        side_key = "a" if team_side.lower() in ["a", "team_a", "left"] else "b"
        self.mock_minutes_overrides[(matchup_id, side_key)] = float(minutes)

        if self.current_state and self.current_state.matchups:
            for m in self.current_state.matchups:
                if m.matchup_id == matchup_id:
                    target_team = m.team_a if side_key == "a" else m.team_b
                    if target_team:
                        mins = max(0.0, min(float(target_team.total_minutes), float(minutes)))
                        target_team.minutes_played = mins
                        target_team.time_played_pct = round((mins / target_team.total_minutes) * 100.0, 1)
                        return True
        return False

    def clear_mock_overrides(self):
        """Clear all active test/simulation overrides and return to live tracking."""
        self.mock_redzone_overrides.clear()
        self.mock_minutes_overrides.clear()

    def trigger_test_highlight(
        self,
        player_name: str = "Josh Allen",
        delta_points: float = 6.4,
        fantasy_team_name: str = "auto",
        position: str = "QB",
        nfl_team: str = "BUF",
        headshot_url: Optional[str] = None,
        highlight_type: Optional[str] = None,
        is_touchdown: Optional[bool] = None,
        is_starter: Optional[bool] = None,
        roster_slot: Optional[str] = None
    ) -> HighlightEvent:
        """Trigger an instant test highlight play with auto player/defense lookup and accurate manager color."""
        p_lower = player_name.lower().strip()
        resolved_headshot = headshot_url
        resolved_pid = None

        if "viking" in p_lower or nfl_team.upper() == "MIN" or (position == "DEF" and "min" in p_lower):
            team_c = "min"
            resolved_headshot = resolved_headshot or f"https://sleepercdn.com/images/team_logos/nfl/{team_c}.png"
            resolved_pid = "MIN"
            position = "DEF"
            nfl_team = "MIN"
        elif "taylor" in p_lower:
            resolved_headshot = resolved_headshot or "https://sleepercdn.com/content/nfl/players/6813.jpg"
            resolved_pid = "6813"
            position = "RB"
            nfl_team = "IND"
        elif "allen" in p_lower:
            resolved_headshot = resolved_headshot or "https://sleepercdn.com/content/nfl/players/4984.jpg"
            resolved_pid = "4984"
            position = "QB"
            nfl_team = "BUF"
        elif "burrow" in p_lower:
            resolved_headshot = resolved_headshot or "https://sleepercdn.com/content/nfl/players/6770.jpg"
            resolved_pid = "6770"
            position = "QB"
            nfl_team = "CIN"
        elif "evans" in p_lower:
            resolved_headshot = resolved_headshot or "https://sleepercdn.com/content/nfl/players/2216.jpg"
            resolved_pid = "2216"
            position = "WR"
            nfl_team = "TB"
        elif "nabers" in p_lower:
            resolved_headshot = resolved_headshot or "https://sleepercdn.com/content/nfl/players/11632.jpg"
            resolved_pid = "11632"
            position = "WR"
            nfl_team = "NYG"
        elif "daniels" in p_lower:
            resolved_headshot = resolved_headshot or "https://sleepercdn.com/content/nfl/players/11560.jpg"
            resolved_pid = "11560"
            position = "QB"
            nfl_team = "WAS"
        elif "rice" in p_lower:
            resolved_headshot = resolved_headshot or "https://sleepercdn.com/content/nfl/players/10222.jpg"
            resolved_pid = "10222"
            position = "WR"
            nfl_team = "KC"
        elif "mcbride" in p_lower:
            resolved_headshot = resolved_headshot or "https://sleepercdn.com/content/nfl/players/8130.jpg"
            resolved_pid = "8130"
            position = "TE"
            nfl_team = "ARI"
        elif "smith-njigba" in p_lower or "njigba" in p_lower:
            resolved_headshot = resolved_headshot or "https://sleepercdn.com/content/nfl/players/9488.jpg"
            resolved_pid = "9488"
            position = "WR"
            nfl_team = "SEA"
        elif "aubrey" in p_lower:
            resolved_headshot = resolved_headshot or "https://sleepercdn.com/content/nfl/players/11533.jpg"
            resolved_pid = "11533"
            position = "K"
            nfl_team = "DAL"
        elif position == "DEF" or (nfl_team and len(nfl_team) in [2, 3] and nfl_team.isalpha() and position == "DEF"):
            team_c = (nfl_team or "min").lower()
            resolved_headshot = resolved_headshot or f"https://sleepercdn.com/images/team_logos/nfl/{team_c}.png"
            resolved_pid = team_c.upper()
        else:
            if hasattr(self.sleeper, "players_cache") and self.sleeper.players_cache:
                for pid, pdata in self.sleeper.players_cache.items():
                    if pdata.get("name", "").lower().strip() == p_lower:
                        resolved_pid = pid
                        position = position or pdata.get("position", "WR")
                        nfl_team = nfl_team or pdata.get("team", "NFL")
                        resolved_headshot = resolved_headshot or pdata.get("headshot_url")
                        break
            if not resolved_pid:
                resolved_pid = "4984"
                resolved_headshot = resolved_headshot or "https://sleepercdn.com/content/nfl/players/4984.jpg"

        # Check player_to_roster mapping to find the actual fantasy manager owner
        detected_roster = None
        if hasattr(self, "player_to_roster") and self.player_to_roster:
            if resolved_pid and str(resolved_pid) in self.player_to_roster:
                detected_roster = self.player_to_roster[str(resolved_pid)]
            else:
                for pid, r_data in self.player_to_roster.items():
                    p_info = self.sleeper.get_player_info(pid)
                    if p_info.get("name", "").lower().strip() == p_lower:
                        detected_roster = r_data
                        resolved_pid = pid
                        break

        is_fa = (fantasy_team_name.lower() in ["free agent", "unowned", "none", "fa"])
        
        if fantasy_team_name.lower() in ["auto", "detect", ""] or not fantasy_team_name:
            if detected_roster:
                fantasy_team_name = detected_roster["team_name"]
                manager_name = detected_roster["manager_name"]
                color = detected_roster["color_accent"]
                is_fa = False
            else:
                fantasy_team_name = "Free Agent"
                manager_name = "Free Agent"
                color = COLOR_FREE_AGENT
                is_fa = True
        elif is_fa:
            color = COLOR_FREE_AGENT
            manager_name = "Free Agent"
            fantasy_team_name = "Free Agent"
        else:
            color = None
            manager_name = fantasy_team_name
            if hasattr(self, "rosters_map") and self.rosters_map:
                for rid, r in self.rosters_map.items():
                    if (r["team_name"].lower() == fantasy_team_name.lower() or 
                        r["manager_name"].lower() == fantasy_team_name.lower()):
                        color = r["color_accent"]
                        fantasy_team_name = r["team_name"]
                        manager_name = r["manager_name"]
                        break
            if not color:
                for key, val in MANAGER_COLORS.items():
                    if key.lower() == fantasy_team_name.lower():
                        color = val
                        break
            if not color and detected_roster:
                color = detected_roster["color_accent"]
                fantasy_team_name = detected_roster["team_name"]
                manager_name = detected_roster["manager_name"]
            if not color:
                color = "#00f0ff"

        hl_type = (highlight_type or "").lower().strip()
        p_desc = player_name.lower()

        if not hl_type:
            if is_touchdown is True or "touchdown" in p_desc or " td" in p_desc or "pick-6" in p_desc:
                hl_type = "touchdown"
            elif position == "K" or "field goal" in p_desc or " fg" in p_desc:
                hl_type = "field_goal"
            elif position == "DEF":
                hl_type = "touchdown" if (is_touchdown or "td" in p_desc or "pick-6" in p_desc) else "def_stop"
            elif is_touchdown is False or "big play" in p_desc or "catch" in p_desc or "run" in p_desc:
                hl_type = "big_play"
            else:
                hl_type = "touchdown" if delta_points >= 6.0 else "big_play"

        hl_is_td = (is_touchdown if is_touchdown is not None else (hl_type == "touchdown"))
        action_label = "Touchdown" if hl_is_td else ("Field Goal" if hl_type == "field_goal" else ("Def Stop" if hl_type == "def_stop" else "Big Play"))

        if is_starter is None:
            if detected_roster and "is_starter" in detected_roster:
                is_starter = bool(detected_roster["is_starter"])
            elif hasattr(self, "starters_set") and resolved_pid:
                is_starter = (str(resolved_pid) in self.starters_set)
            else:
                is_starter = True
        if roster_slot is None:
            roster_slot = "STARTER" if is_starter else "BENCH"

        duration_sec = self.get_speed_seconds()

        hl = HighlightEvent(
            id=str(uuid.uuid4())[:8],
            player_id=resolved_pid or "4984",
            player_name=player_name,
            position=position,
            nfl_team=nfl_team,
            fantasy_team_name=fantasy_team_name,
            manager_name=manager_name,
            delta_points=delta_points,
            total_points=round(delta_points * 2.2, 1),
            headshot_url=resolved_headshot,
            color_accent=color,
            is_free_agent=is_fa,
            play_description=f"{action_label} (+{delta_points:.1f} pts)",
            duration_seconds=duration_sec,
            is_user_team=(fantasy_team_name.lower() == self.user_team_name),
            highlight_type=hl_type,
            is_touchdown=hl_is_td,
            is_starter=is_starter,
            roster_slot=roster_slot
        )
        self.highlight_queue.append(hl)
        if self.current_state:
            self.current_state.highlight_queue = self.highlight_queue[-5:]
        return hl

    def trigger_test_injury(
        self,
        player_name: str = "CeeDee Lamb",
        injury_status: str = "Out",
        injury_detail: str = "Shoulder - Out for game",
        fantasy_team_name: str = "auto",
        position: str = "WR",
        nfl_team: str = "DAL",
        headshot_url: Optional[str] = None,
        points: Optional[float] = None,
        is_starter: Optional[bool] = None,
        roster_slot: Optional[str] = None
    ) -> InjuryAlertEvent:
        """Trigger an instant test injury alert for a player with manager lookup and negative styling."""
        p_lower = player_name.lower().strip()
        resolved_headshot = headshot_url
        resolved_pid = None

        if "lamb" in p_lower:
            resolved_headshot = resolved_headshot or "https://sleepercdn.com/content/nfl/players/6786.jpg"
            resolved_pid = "6786"
            position = "WR"
            nfl_team = "DAL"
        elif "allen" in p_lower:
            resolved_headshot = resolved_headshot or "https://sleepercdn.com/content/nfl/players/4984.jpg"
            resolved_pid = "4984"
            position = "QB"
            nfl_team = "BUF"
        elif "barkley" in p_lower:
            resolved_headshot = resolved_headshot or "https://sleepercdn.com/content/nfl/players/4866.jpg"
            resolved_pid = "4866"
            position = "RB"
            nfl_team = "PHI"
        elif "jefferson" in p_lower:
            resolved_headshot = resolved_headshot or "https://sleepercdn.com/content/nfl/players/6794.jpg"
            resolved_pid = "6794"
            position = "WR"
            nfl_team = "MIN"
        else:
            if hasattr(self.sleeper, "players_cache") and self.sleeper.players_cache:
                for pid, pdata in self.sleeper.players_cache.items():
                    if pdata.get("name", "").lower().strip() == p_lower:
                        resolved_pid = pid
                        position = position or pdata.get("position", "WR")
                        nfl_team = nfl_team or pdata.get("team", "NFL")
                        resolved_headshot = resolved_headshot or pdata.get("headshot_url")
                        break
            if not resolved_pid:
                resolved_pid = "6786"
                resolved_headshot = resolved_headshot or "https://sleepercdn.com/content/nfl/players/6786.jpg"

        # Check player_to_roster mapping to find the actual fantasy manager owner
        detected_roster = None
        if hasattr(self, "player_to_roster") and self.player_to_roster:
            if resolved_pid and str(resolved_pid) in self.player_to_roster:
                detected_roster = self.player_to_roster[str(resolved_pid)]
            else:
                for pid, r_data in self.player_to_roster.items():
                    p_info = self.sleeper.get_player_info(pid)
                    if p_info.get("name", "").lower().strip() == p_lower:
                        detected_roster = r_data
                        resolved_pid = pid
                        break

        is_fa = (fantasy_team_name.lower() in ["free agent", "unowned", "none", "fa"])
        if fantasy_team_name.lower() in ["auto", "detect", ""] or not fantasy_team_name:
            if detected_roster:
                fantasy_team_name = detected_roster["team_name"]
                manager_name = detected_roster["manager_name"]
                is_fa = False
            else:
                fantasy_team_name = "Free Agent"
                manager_name = "Free Agent"
                is_fa = True
        elif is_fa:
            manager_name = "Free Agent"
            fantasy_team_name = "Free Agent"
        else:
            manager_name = fantasy_team_name
            if hasattr(self, "rosters_map") and self.rosters_map:
                for rid, r in self.rosters_map.items():
                    if (r["team_name"].lower() == fantasy_team_name.lower() or 
                        r["manager_name"].lower() == fantasy_team_name.lower()):
                        fantasy_team_name = r["team_name"]
                        manager_name = r["manager_name"]
                        break

        if is_starter is None:
            if detected_roster and "is_starter" in detected_roster:
                is_starter = bool(detected_roster["is_starter"])
            elif hasattr(self, "starters_set") and resolved_pid:
                is_starter = (str(resolved_pid) in self.starters_set)
            else:
                is_starter = True
        if roster_slot is None:
            roster_slot = "STARTER" if is_starter else "BENCH"
        if points is None:
            points = float(self.prev_player_points.get(str(resolved_pid), 0.0))

        duration_sec = self.get_speed_seconds()
        accent = "#ef4444" if injury_status.lower() in ["out", "ir", "injured reserve"] else "#f59e0b"

        inj = InjuryAlertEvent(
            id=str(uuid.uuid4())[:8],
            player_id=resolved_pid or "6786",
            player_name=player_name,
            position=position,
            nfl_team=nfl_team,
            fantasy_team_name=fantasy_team_name,
            manager_name=manager_name,
            injury_status=injury_status,
            injury_detail=injury_detail or f"{injury_status} during game",
            headshot_url=resolved_headshot,
            color_accent=accent,
            is_free_agent=is_fa,
            duration_seconds=duration_sec,
            is_user_team=(fantasy_team_name.lower() == self.user_team_name),
            points=round(points, 1),
            is_starter=is_starter,
            roster_slot=roster_slot
        )
        self.injury_queue.append(inj)
        if self.current_state:
            self.current_state.injury_queue = self.injury_queue[-5:]
        return inj

    def simulate_random_delta(self) -> HighlightEvent:
        """Pick a random active star and trigger a highlight play."""
        candidates = [
            ("Josh Allen", "QB", "BUF", 6.4, True, "touchdown", True),
            ("Justin Jefferson", "WR", "MIN", 8.2, True, "touchdown", True),
            ("Saquon Barkley", "RB", "PHI", 5.5, False, "big_play", True),
            ("CeeDee Lamb", "WR", "DAL", 7.1, True, "touchdown", False),
            ("Bijan Robinson", "RB", "ATL", 6.0, True, "touchdown", False),
            ("Trey McBride", "TE", "ARI", 4.8, False, "big_play", True),
            ("Brandon Aubrey", "K", "DAL", 3.0, False, "field_goal", True),
            ("Minnesota Vikings", "DEF", "MIN", 6.0, True, "touchdown", True),
        ]
        chosen = random.choice(candidates)
        return self.trigger_test_highlight(
            player_name=chosen[0],
            position=chosen[1],
            nfl_team=chosen[2],
            delta_points=chosen[3],
            is_touchdown=chosen[4],
            highlight_type=chosen[5],
            is_starter=chosen[6]
        )

    def simulate_random_injury(self) -> InjuryAlertEvent:
        """Pick a random active star and trigger an injury alert."""
        candidates = [
            ("CeeDee Lamb", "Out", "Shoulder - Out for game", "WR", "DAL", False, 18.6),
            ("Josh Allen", "Questionable", "Ankle - Questionable to return", "QB", "BUF", True, 24.2),
            ("Saquon Barkley", "Out", "Knee - Ruled out for remainder of game", "RB", "PHI", True, 14.8),
            ("Bijan Robinson", "Out", "Hamstring - Ruled out", "RB", "ATL", False, 12.4),
            ("Justin Jefferson", "Questionable", "Hamstring - Questionable to return", "WR", "MIN", True, 22.0),
            ("Trey McBride", "Questionable", "Ribs - Questionable to return", "TE", "ARI", True, 9.4),
        ]
        chosen = random.choice(candidates)
        return self.trigger_test_injury(
            player_name=chosen[0],
            injury_status=chosen[1],
            injury_detail=chosen[2],
            position=chosen[3],
            nfl_team=chosen[4],
            is_starter=chosen[5],
            points=chosen[6]
        )
