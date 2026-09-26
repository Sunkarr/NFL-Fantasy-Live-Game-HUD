import time
import logging
from typing import Dict, Any, Optional
import httpx

logger = logging.getLogger(__name__)


class TeamGameInfo(dict):
    """Represents live game progress and status for an NFL team, supporting both attribute and dict access."""

    def __init__(self, team: str, state: str, raw_state: str, clock: str, progress_pct: float, detail: str, period: int = 0):
        super().__init__(
            team=team,
            state=state,
            raw_state=raw_state,
            status=raw_state,
            clock=clock,
            progress_pct=progress_pct,
            detail=detail,
            period=period
        )
        self.team = team
        self.state = state
        self.raw_state = raw_state
        self.status = raw_state  # "pre", "in", "post"
        self.clock = clock
        self.progress_pct = progress_pct
        self.detail = detail
        self.period = period


class NFLGameTracker:
    """Tracks live NFL game statuses, clocks, and completion percentages."""

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=8.0)
        self.team_status_cache: Dict[str, TeamGameInfo] = {}
        self.last_fetched: float = 0.0
        self.cache_ttl: float = 15.0  # 15 seconds TTL for ESPN API

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

                # Calculate progress percentage (0.0 to 1.0)
                progress_pct = 0.0
                if state == "post":
                    progress_pct = 1.0
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
                    progress_pct = min(1.0, max(0.0, total_sec_elapsed / (60.0 * 60.0)))
                    
                    if period == 2 and clock_sec == 0:
                        game_state_str = "HALFTIME"
                    else:
                        game_state_str = "IN_PROGRESS"
                else:
                    progress_pct = 0.0
                    game_state_str = "PRE"

                competitors = comp.get("competitors", [])
                for team_entry in competitors:
                    abbr = team_entry.get("team", {}).get("abbreviation", "").upper()
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
                            period=period
                        )

            self.team_status_cache = team_lookup
            self.last_fetched = now
            return team_lookup

        except Exception as e:
            logger.warning(f"Error fetching ESPN NFL scoreboard: {e}")
            return self.team_status_cache

    def get_team_game_status(self, team_abbr: Optional[str]) -> TeamGameInfo:
        """Get game progress and status for an NFL team abbreviation."""
        if not team_abbr or team_abbr.upper() in ["FA", "FREE AGENT", "UNK", "NONE"]:
            return TeamGameInfo(
                team="FA",
                state="PRE",
                raw_state="pre",
                detail="No Game",
                period=0,
                clock="",
                progress_pct=0.0
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
            progress_pct=0.0
        )

    # Alias for state engine compatibility
    get_game_for_team = get_team_game_status

    async def close(self):
        await self.client.aclose()
