import uuid
import time
import random
import logging
from typing import List, Dict, Optional, Any

from src.models import (
    HUDState, MatchupData, TeamScore, PlayerInfo,
    HighlightEvent, IdleSpotlight, DisplaySettings
)
from src.sleeper_client import SleeperClient
from src.nfl_game_tracker import NFLGameTracker
from src.ws_manager import ConnectionManager
from src.config import (
    LEAGUE_ID, TEAM_NAME, HIGHLIGHT_THRESHOLD,
    HIGHLIGHT_DISPLAY_SECONDS, MANAGER_COLORS, COLOR_FREE_AGENT, DEFAULT_PALETTE
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


class HUDStateEngine:
    """
    Central orchestration engine for NFL Fantasy Live Game HUD.
    Maintains active matchup trees, player points history, delta detections,
    position MVP spotlight rotation (including Free Agents), and multi-matchup display modes.
    """

    def __init__(self, ws_manager: ConnectionManager):
        self.ws_manager = ws_manager
        self.sleeper = SleeperClient()
        self.nfl_tracker = NFLGameTracker()

        self.current_state: Optional[HUDState] = None
        self.prev_player_points: Dict[str, float] = {}  # pid -> last seen points
        self.prev_player_stats: Dict[str, Dict[str, Any]] = {}
        self.highlight_queue: List[HighlightEvent] = []
        self.is_bootstrapped: bool = False
        self.user_team_name: str = TEAM_NAME.lower()
        self.player_to_roster: Dict[str, Dict[str, Any]] = {}
        self.rosters_map: Dict[int, Dict[str, Any]] = {}

        # Multi-Matchup Display & Animation Settings
        # Default: normal (10s cycle for MVPs, Highlights, and Matchup Shifts)
        self.display_settings = DisplaySettings(
            mode="auto",
            speed="normal",
            step_interval_seconds=10,
            ticker_speed=35
        )

        # Simulation & Testing
        self.simulation_mode: bool = False
        self.mock_league_active: bool = False
        self.week_override: Optional[int] = None

    async def initialize(self):
        """Bootstrap player database and initial matchup state."""
        await self.sleeper.ensure_players_cache()
        await self.refresh_state(is_initial=True)
        self.is_bootstrapped = True
        logger.info("HUD State Engine initialized successfully.")

    def set_week(self, week: Optional[int]):
        """Override active game week for testing."""
        self.week_override = week
        self.mock_league_active = False
        logger.info(f"Week override set to: {week}")

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
        sound_enabled: Optional[bool] = None,
        sound_theme: Optional[str] = None
    ) -> DisplaySettings:
        """Update display mode and animation speed parameters."""
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
        if sound_enabled is not None:
            self.display_settings.sound_enabled = sound_enabled
        if sound_theme in ["fox_horn", "redzone", "td_siren", "brass_fanfare"]:
            self.display_settings.sound_theme = sound_theme

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

            t_a = TeamScore(
                roster_id=idx_a + 1,
                owner_id=f"user_{idx_a}",
                team_name=m_a[0],
                manager_name=m_a[0],
                avatar_url=m_a[2],
                points=pts_a,
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
                title="WEEK 3 · TOP QB",
                color_accent="#00f0ff",
                is_free_agent=False
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
                title="WEEK 3 · TOP RB",
                color_accent="#ff00aa",
                is_free_agent=False
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
                title="WEEK 3 · TOP WR",
                color_accent="#a855f7",
                is_free_agent=False
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
                title="WEEK 3 · TOP TE",
                color_accent="#ffaa00",
                is_free_agent=False
            ),
            IdleSpotlight(
                player_id="CAR",
                player_name="Carolina Panthers",
                position="DEF",
                nfl_team="CAR",
                fantasy_team_name="FREE AGENT",
                manager_name="Free Agent",
                points=26.0,
                headshot_url="https://sleepercdn.com/images/team_logos/nfl/car.png",
                title="WEEK 3 · TOP DEF",
                color_accent=COLOR_FREE_AGENT,
                is_free_agent=True
            )
        ]

        self.current_state = HUDState(
            league_id=str(self.sleeper.league_id),
            league_name=f"Mock {teams_count}-Team League",
            season="2026",
            week=3,
            is_live=True,
            last_updated=time.time(),
            matchups=matchup_models,
            highlight_queue=self.highlight_queue[-5:],
            idle_spotlight=mock_spotlights[0],
            idle_spotlights=mock_spotlights,
            active_connections=self.ws_manager.count,
            simulation_mode=True,
            display_settings=self.display_settings
        )
        return self.current_state

    async def refresh_state(self, is_initial: bool = False) -> HUDState:
        """Fetch latest live data from Sleeper and NFL APIs and compute deltas."""
        if self.mock_league_active and self.current_state:
            return self.current_state

        try:
            # 1. Fetch current NFL State
            nfl_state = await self.sleeper.get_nfl_state()
            current_week = self.week_override if self.week_override is not None else nfl_state.get("week", 1)
            season_type = nfl_state.get("season_type", "regular")
            season = nfl_state.get("season", "2026")

            # 2. Fetch League, Users, Rosters, Matchups, and League-wide NFL Stats (incl. Free Agents)
            league_info = await self.sleeper.get_league_info()
            scoring_settings = league_info.get("scoring_settings", {})
            users = await self.sleeper.get_league_users()
            rosters = await self.sleeper.get_league_rosters()
            raw_matchups = await self.sleeper.get_matchups(current_week)
            weekly_stats = await self.sleeper.get_weekly_stats(season=season, week=current_week, season_type=season_type)

            # 3. Refresh live ESPN scoreboard
            await self.nfl_tracker.fetch_scoreboard()

            # Map users: user_id -> display_name, avatar
            users_map: Dict[str, Dict[str, str]] = {}
            for u in users:
                uid = u.get("user_id")
                meta = u.get("metadata", {})
                dname = meta.get("team_name") or u.get("display_name") or f"Manager {uid}"
                avatar_id = u.get("avatar")
                avatar_url = f"https://sleepercdn.com/avatars/thumbs/{avatar_id}" if avatar_id else "https://sleepercdn.com/images/v2/icons/player_default.webp"
                users_map[uid] = {
                    "manager_name": u.get("display_name", dname),
                    "team_name": dname,
                    "avatar_url": avatar_url
                }

            # Map rosters: roster_id -> user metadata & assigned accent color
            rosters_map: Dict[int, Dict[str, Any]] = {}
            player_to_roster: Dict[str, Dict[str, Any]] = {}

            for idx, r in enumerate(rosters):
                rid = r.get("roster_id")
                oid = r.get("owner_id")
                u_info = users_map.get(oid, {
                    "manager_name": f"Team {rid}",
                    "team_name": f"Team {rid}",
                    "avatar_url": "https://sleepercdn.com/images/v2/icons/player_default.webp"
                })

                mgr_lower = u_info["manager_name"].lower()
                is_user_team = (mgr_lower == self.user_team_name) or (u_info["team_name"].lower() == self.user_team_name)

                # Determine color accent (Preset override, or deterministic roster palette)
                color = None
                for key, val in MANAGER_COLORS.items():
                    if key.lower() == mgr_lower or key.lower() == u_info["team_name"].lower():
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
                    "manager_name": u_info["manager_name"],
                    "team_name": u_info["team_name"],
                    "avatar_url": u_info["avatar_url"],
                    "is_user_team": is_user_team,
                    "color_accent": color
                }
                rosters_map[rid] = r_dict

                # Map each rostered player back to their fantasy team
                for pid in (r.get("players") or []):
                    player_to_roster[str(pid)] = r_dict

            self.rosters_map = rosters_map
            self.player_to_roster = player_to_roster

            # Group matchups by matchup_id
            matchup_groups: Dict[int, List[Dict[str, Any]]] = {}
            for m in raw_matchups:
                mid = m.get("matchup_id")
                if mid is not None:
                    matchup_groups.setdefault(mid, []).append(m)

            matchup_models: List[MatchupData] = []
            duration_sec = self.get_speed_seconds()
            new_highlights: List[HighlightEvent] = []

            # Track top fantasy performer for each position across ALL NFL players
            top_by_position: Dict[str, Dict[str, Any]] = {}

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
                    starters = m_entry.get("starters") or []
                    players_pts = m_entry.get("players_points") or {}

                    starters_detail: List[PlayerInfo] = []
                    starters_played_count = 0
                    starters_in_progress_count = 0
                    total_progress_sum = 0.0

                    for pid in starters:
                        p_info = self.sleeper.get_player_info(str(pid))
                        pts = float(players_pts.get(str(pid), 0.0))
                        p_stats = (weekly_stats.get(str(pid)) if weekly_stats else None) or (m_entry.get("players_stats") or {}).get(str(pid), {})
                        team_abbr = p_info["team"]

                        game_info = self.nfl_tracker.get_game_for_team(team_abbr)
                        status = "pre"
                        clock = ""
                        progress_pct = 0.0

                        if game_info:
                            status = game_info.status
                            clock = game_info.clock
                            progress_pct = game_info.progress_pct

                        if status == "in":
                            starters_in_progress_count += 1
                        elif status == "post":
                            starters_played_count += 1

                        total_progress_sum += progress_pct

                        player_model = PlayerInfo(
                            player_id=str(pid),
                            name=p_info["name"],
                            position=p_info["position"],
                            team=team_abbr,
                            points=pts,
                            game_status=status,
                            game_clock=clock,
                            game_progress_pct=progress_pct,
                            headshot_url=p_info["headshot_url"],
                            fantasy_team_name=r_meta["team_name"],
                            color_accent=r_meta["color_accent"]
                        )
                        starters_detail.append(player_model)

                        # Check for Position MVP candidate
                        pos = p_info["position"]
                        if pos in ["QB", "RB", "WR", "TE", "DEF", "K"]:
                            current_top = top_by_position.get(pos)
                            if current_top is None or pts > current_top["points"]:
                                top_by_position[pos] = {
                                    "player_id": str(pid),
                                    "player_name": p_info["name"],
                                    "position": pos,
                                    "nfl_team": p_info["team"],
                                    "fantasy_team_name": r_meta["team_name"],
                                    "manager_name": r_meta["manager_name"],
                                    "points": round(pts, 2),
                                    "headshot_url": p_info["headshot_url"],
                                    "title": f"WK {current_week} · TOP {pos}",
                                    "color_accent": r_meta["color_accent"],
                                    "is_free_agent": False
                                }

                        # Delta check for Highlight Queue
                        if self.is_bootstrapped and not is_initial:
                            prev_pts = self.prev_player_points.get(str(pid), pts)
                            delta = pts - prev_pts
                            if delta >= HIGHLIGHT_THRESHOLD:
                                logger.info(f"🔥 HIGHLIGHT DETECTED! {p_info['name']} +{delta:.1f} FPTS for {r_meta['manager_name']}")
                                
                                # Action type classification (Touchdown, Field Goal, Defense Stop, Big Play)
                                cur_pstats = p_stats or {}
                                old_pstats = self.prev_player_stats.get(str(pid), {})
                                pos = p_info["position"]
                                
                                td_keys = ["rush_td", "rec_td", "pass_td", "def_td", "td"]
                                has_td = any(
                                    float(cur_pstats.get(k, 0) or 0) > float(old_pstats.get(k, 0) or 0)
                                    for k in td_keys
                                )
                                if not has_td and delta >= 6.0 and pos in ["QB", "RB", "WR", "TE"] and not old_pstats:
                                    has_td = True

                                if has_td:
                                    hl_type = "touchdown"
                                    desc = f"Touchdown (+{round(delta, 1)} pts)"
                                elif pos == "K" or any(float(cur_pstats.get(k, 0) or 0) > float(old_pstats.get(k, 0) or 0) for k in ["fgm", "fgm_50p", "fgm_40_49"]):
                                    hl_type = "field_goal"
                                    desc = f"Field Goal (+{round(delta, 1)} pts)"
                                elif pos == "DEF":
                                    hl_type = "touchdown" if has_td else "def_stop"
                                    desc = f"{'Defensive TD' if has_td else 'Defensive Stop'} (+{round(delta, 1)} pts)"
                                else:
                                    hl_type = "big_play"
                                    desc = f"Big Play (+{round(delta, 1)} pts)"

                                highlight = HighlightEvent(
                                    id=str(uuid.uuid4())[:8],
                                    player_id=str(pid),
                                    player_name=p_info["name"],
                                    position=p_info["position"],
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
                                    is_touchdown=has_td
                                )
                                new_highlights.append(highlight)
                                self.highlight_queue.append(highlight)

                        # Update previous points tracking
                        self.prev_player_points[str(pid)] = pts
                        self.prev_player_stats[str(pid)] = p_stats or {}

                    # Calculate overall team game time played %
                    num_starters = max(len(starters_detail), 1)
                    avg_time_pct = (total_progress_sum / num_starters) * 100.0

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
                        time_played_pct=round(avg_time_pct, 1),
                        is_user_team=r_meta["is_user_team"],
                        color_accent=r_meta["color_accent"],
                        starters_detail=starters_detail
                    )
                    teams.append(team_score)

                if len(teams) >= 2:
                    t_a = teams[0]
                    t_b = teams[1]
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

            # Build list of Position MVPs (ordered: QB, RB, WR, TE, DEF, K) - ONLY players with > 0.0 points
            idle_spotlights: List[IdleSpotlight] = []
            for pos in ["QB", "RB", "WR", "TE", "DEF", "K"]:
                cand = top_by_position.get(pos)
                if cand and cand["points"] > 0.0:
                    idle_spotlights.append(IdleSpotlight(**cand))

            # Update Current State (idle_spotlights is empty if no games have started yet)
            self.current_state = HUDState(
                league_id=str(self.sleeper.league_id),
                league_name=league_info.get("name", "NFL Fantasy League"),
                season=league_info.get("season", "2026"),
                week=current_week,
                is_live=(season_type == "regular"),
                last_updated=time.time(),
                matchups=matchup_models,
                highlight_queue=self.highlight_queue[-5:],
                idle_spotlight=idle_spotlights[0] if idle_spotlights else None,
                idle_spotlights=idle_spotlights,
                active_connections=self.ws_manager.count,
                simulation_mode=self.simulation_mode,
                display_settings=self.display_settings
            )

            # Broadcast new highlights if any occurred
            for hl in new_highlights:
                await self.ws_manager.broadcast({
                    "type": "PUSH_HIGHLIGHT",
                    "highlight": hl.model_dump()
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

    def trigger_test_highlight(
        self,
        player_name: str = "Josh Allen",
        delta_points: float = 6.4,
        fantasy_team_name: str = "auto",
        position: str = "QB",
        nfl_team: str = "BUF",
        headshot_url: Optional[str] = None,
        highlight_type: Optional[str] = None,
        is_touchdown: Optional[bool] = None
    ) -> HighlightEvent:
        """Trigger an instant test highlight play with auto player/defense lookup and accurate manager color."""
        p_lower = player_name.lower().strip()
        resolved_headshot = headshot_url
        resolved_pid = None

        # Resolve player / defense identification
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
            # Query sleeper cache
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

        # Determine if this play should be associated with the detected roster or an explicit selection
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
            # Explicit fantasy team or manager specified
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

        # Determine action category (touchdown, field_goal, def_stop, big_play)
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
            is_touchdown=hl_is_td
        )
        self.highlight_queue.append(hl)
        return hl
