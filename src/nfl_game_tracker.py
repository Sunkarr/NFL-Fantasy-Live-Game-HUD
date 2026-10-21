import time
import logging
from typing import Dict, Any, Optional
import httpx

logger = logging.getLogger(__name__)


class TeamGameInfo(dict):
    """Represents live game progress, minutes elapsed, and redzone status for an NFL team."""

    def __init__(
        self,
        team: str,
        state: str,
        raw_state: str,
        clock: str,
        progress_pct: float,
        detail: str,
        period: int = 0,
        minutes_elapsed: float = 0.0,
        is_redzone: bool = False
    ):
        super().__init__(
            team=team,
            state=state,
            raw_state=raw_state,
            status=raw_state,
            clock=clock,
            progress_pct=progress_pct,
            detail=detail,
            period=period,
            minutes_elapsed=minutes_elapsed,
            is_redzone=is_redzone
        )
        self.team = team
        self.state = state
        self.raw_state = raw_state
        self.status = raw_state  # "pre", "in", "post"
        self.clock = clock
        self.progress_pct = progress_pct
        self.detail = detail
        self.period = period
        self.minutes_elapsed = minutes_elapsed
        self.is_redzone = is_redzone


class NFLGameTracker:
    """Tracks live NFL game statuses, clocks, completion percentages, red zone states, and player injuries."""

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=8.0)
        self.team_status_cache: Dict[str, TeamGameInfo] = {}
        self.last_fetched: float = 0.0
        self.cache_ttl: float = 15.0  # 15 seconds TTL for ESPN Scoreboard

        self.injury_cache: Dict[str, Dict[str, Any]] = {}
        self.last_injury_fetched: float = 0.0
        self.injury_cache_ttl: float = 30.0  # 30 seconds TTL for ESPN Injuries

    async def fetch_scoreboard(self) -> Dict[str, TeamGameInfo]:
        """Alias for update_nfl_games."""
        return await self.update_nfl_games()

    async def update_nfl_games(self) -> Dict[str, TeamGameInfo]:
        """Fetch live scoreboard from ESPN API and build team lookup."""
        now = time.time()
        if now - self.last_fetched < self.cache_ttl and self.team_status_cache:
            return self.team_status_cache

        try:
            url = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
            resp = await self.client.get(url)
            resp.raise_for_status()
            data = resp.json()

            team_lookup: Dict[str, TeamGameInfo] = {}
            events = data.get("events", [])

            for ev in events:
                comps = ev.get("competitions", [])
                if not comps:
                    continue
                comp = comps[0]
                status = comp.get("status", {})
                status_type = status.get("type", {})
                state = status_type.get("state", "pre")  # "pre", "in", "post"
                detail = status_type.get("shortDetail", "")
                period = status.get("period", 0)
                display_clock = status.get("displayClock", "0:00")

                # Situation (Possession & Red Zone)
                situation = comp.get("situation", {}) or {}
                is_redzone_raw = bool(situation.get("isRedZone", False) or situation.get("redZone", False))
                possession_id = str(situation.get("possession", "")).strip()

                # Calculate progress percentage (0.0 to 1.0) and minutes elapsed (0.0 to 60.0)
                progress_pct = 0.0
                minutes_elapsed = 0.0

                if state == "post":
                    progress_pct = 1.0
                    minutes_elapsed = 60.0
                    game_state_str = "FINAL"
                elif state == "in":
                    # In game: calculate based on quarter and clock
                    clock_parts = display_clock.split(":")
                    clock_sec = 0
                    if len(clock_parts) == 2:
                        try:
                            clock_sec = int(clock_parts[0]) * 60 + int(clock_parts[1])
                        except ValueError:
                            clock_sec = 0

                    q_elapsed = (15 * 60) - clock_sec
                    quarter_idx = min(max(period - 1, 0), 3)
                    total_sec_elapsed = (quarter_idx * 15 * 60) + max(0, q_elapsed)
                    
                    minutes_elapsed = min(60.0, max(0.0, total_sec_elapsed / 60.0))
                    progress_pct = min(1.0, max(0.0, minutes_elapsed / 60.0))

                    if period == 2 and clock_sec == 0:
                        game_state_str = "HALFTIME"
                    else:
                        game_state_str = "IN_PROGRESS"
                else:
                    progress_pct = 0.0
                    minutes_elapsed = 0.0
                    game_state_str = "PRE"

                competitors = comp.get("competitors", [])
                for team_entry in competitors:
                    team_obj = team_entry.get("team", {}) or {}
                    t_id = str(team_entry.get("id", "")).strip()
                    sub_id = str(team_obj.get("id", "")).strip()
                    abbr = team_obj.get("abbreviation", "").upper()
                    if not abbr:
                        continue

                    # Check if this team currently has possession in the redzone
                    has_possession = bool(possession_id and (possession_id == t_id or possession_id == sub_id))
                    team_in_redzone = bool(has_possession and is_redzone_raw)

                    # Handle team abbreviation normalizations (e.g. WSH/WAS, JAX/JAC)
                    aliases = [abbr]
                    if abbr == "WSH": aliases.append("WAS")
                    if abbr == "WAS": aliases.append("WSH")
                    if abbr == "JAX": aliases.append("JAC")
                    if abbr == "JAC": aliases.append("JAX")

                    for alias in aliases:
                        team_lookup[alias] = TeamGameInfo(
                            team=alias,
                            state=game_state_str,
                            raw_state=state,
                            clock=display_clock,
                            progress_pct=progress_pct,
                            detail=detail,
                            period=period,
                            minutes_elapsed=round(minutes_elapsed, 1),
                            is_redzone=team_in_redzone
                        )

            self.team_status_cache = team_lookup
            self.last_fetched = now
            return team_lookup

        except Exception as e:
            logger.warning(f"Error fetching ESPN NFL scoreboard: {e}")
            return self.team_status_cache

    async def fetch_injuries(self) -> Dict[str, Dict[str, Any]]:
        """
        Fetch real-time NFL player injury reports from ESPN across all 32 teams.
        Returns a dict mapping normalized player names and (name, team) keys to injury details.
        """
        now = time.time()
        if now - self.last_injury_fetched < self.injury_cache_ttl and self.injury_cache:
            return self.injury_cache

        try:
            url = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"
            resp = await self.client.get(url)
            resp.raise_for_status()
            data = resp.json()

            injury_lookup: Dict[str, Dict[str, Any]] = {}
            team_entries = data.get("injuries", [])

            for team_item in team_entries:
                for inj in team_item.get("injuries", []):
                    ath = inj.get("athlete", {}) or {}
                    p_name = ath.get("displayName", "").strip()
                    if not p_name:
                        continue

                    status = str(inj.get("status", "Questionable")).strip()
                    team_obj = ath.get("team", {}) or {}
                    t_abbr = str(team_obj.get("abbreviation", "")).upper().strip()
                    pos_obj = ath.get("position", {}) or {}
                    pos_abbr = str(pos_obj.get("abbreviation", "")).upper().strip()

                    details = inj.get("details", {}) or {}
                    injury_type = str(details.get("type", "")).strip()
                    detail_desc = str(details.get("detail", "")).strip()
                    comment = str(inj.get("shortComment", "") or inj.get("longComment", "")).strip()

                    # Format clear injury detail
                    if injury_type and injury_type.lower() not in ["not specified", "unknown"]:
                        detail_str = f"{injury_type} ({status})"
                    else:
                        detail_str = status

                    if comment:
                        # Extract first sentence or snippet
                        first_sentence = comment.split(".")[0].strip()
                        if first_sentence and len(first_sentence) < 80:
                            detail_str = f"{detail_str} - {first_sentence}"

                    headshot = ath.get("headshot", {}) or {}
                    headshot_url = headshot.get("href", "")

                    record = {
                        "player_name": p_name,
                        "nfl_team": t_abbr,
                        "position": pos_abbr,
                        "status": status,
                        "detail": detail_str,
                        "comment": comment,
                        "headshot_url": headshot_url,
                        "date": inj.get("date", "")
                    }

                    norm_name = p_name.lower().strip()
                    injury_lookup[norm_name] = record
                    if t_abbr:
                        injury_lookup[f"{norm_name}_{t_abbr.lower()}"] = record

            self.injury_cache = injury_lookup
            self.last_injury_fetched = now
            return injury_lookup

        except Exception as e:
            logger.warning(f"Error fetching ESPN NFL injuries: {e}")
            return self.injury_cache

    def get_team_game_status(self, team_abbr: Optional[str]) -> TeamGameInfo:
        """Get game progress, minutes elapsed, and redzone status for an NFL team abbreviation."""
        if not team_abbr or team_abbr.upper() in ["FA", "FREE AGENT", "UNK", "NONE"]:
            return TeamGameInfo(
                team="FA",
                state="PRE",
                raw_state="pre",
                detail="No Game",
                period=0,
                clock="",
                progress_pct=0.0,
                minutes_elapsed=0.0,
                is_redzone=False
            )

        abbr = team_abbr.upper().strip()
        if abbr in self.team_status_cache:
            return self.team_status_cache[abbr]

        return TeamGameInfo(
            team=abbr,
            state="PRE",
            raw_state="pre",
            detail="Scheduled",
            period=0,
            clock="",
            progress_pct=0.0,
            minutes_elapsed=0.0,
            is_redzone=False
        )

    # Alias for state engine compatibility
    get_game_for_team = get_team_game_status

    async def close(self):
        await self.client.aclose()
