from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field
import time


class PlayerInfo(BaseModel):
    player_id: str
    name: str
    position: str
    team: Optional[str] = "FA"
    injury_status: Optional[str] = "Healthy"
    headshot_url: str
    points: float = 0.0
    projected_points: float = 0.0
    game_status: Optional[str] = "PRE"  # PRE, IN_PROGRESS, HALFTIME, FINAL
    game_clock: Optional[str] = ""
    game_progress_pct: float = 0.0      # 0.0 - 1.0


class TeamScore(BaseModel):
    roster_id: int
    owner_id: str
    team_name: str
    manager_name: str
    avatar_url: str
    points: float = 0.0
    projected_points: float = 0.0
    starters_count: int = 9
    starters_played_count: int = 0
    starters_in_progress_count: int = 0
    starters_yet_to_play_count: int = 9
    time_played_pct: float = 0.0
    is_user_team: bool = False
    color_accent: str = "#00f0ff"
    starters_detail: List[PlayerInfo] = Field(default_factory=list)


class MatchupData(BaseModel):
    matchup_id: int
    team_a: TeamScore
    team_b: Optional[TeamScore] = None
    diff: float = 0.0
    leader_roster_id: Optional[int] = None
    win_probability_a: float = 50.0


class HighlightEvent(BaseModel):
    id: str
    player_id: str
    player_name: str
    position: str
    nfl_team: str
    fantasy_team_name: str
    manager_name: str
    delta_points: float
    total_points: float
    headshot_url: str
    color_accent: str = "#94a3b8"  # Team color or #94a3b8 for Free Agent
    is_free_agent: bool = False
    play_description: str = "Big Play / Score"
    timestamp: float = Field(default_factory=time.time)
    duration_seconds: int = 6
    is_user_team: bool = False
    highlight_type: str = "big_play"  # "touchdown", "big_play", "field_goal", "def_stop"
    is_touchdown: bool = False


class IdleSpotlight(BaseModel):
    player_id: str
    player_name: str
    position: str
    nfl_team: str
    fantasy_team_name: str
    manager_name: str
    points: float
    headshot_url: str
    title: str = "ACTIVE PLAYER"
    color_accent: str = "#94a3b8"
    is_free_agent: bool = False
    is_starter: bool = True
    roster_slot: str = "STARTER"  # "STARTER" or "BENCH"
    rank: Optional[int] = None    # Position rank sorted by FPTS descending (1, 2, 3...)


class DisplaySettings(BaseModel):
    mode: Literal["auto", "ticker", "step", "paged"] = "auto"
    speed: Literal["normal", "fast", "slow"] = "normal"
    step_interval_seconds: int = 6
    ticker_speed: int = 35  # pixels per second
    sound_enabled: bool = True
    sound_theme: Literal["fox_horn", "redzone", "td_siren", "brass_fanfare"] = "fox_horn" 


class HUDState(BaseModel):
    league_id: str
    league_name: str
    season: str
    week: int
    is_live: bool = False
    last_updated: float = Field(default_factory=time.time)
    matchups: List[MatchupData] = Field(default_factory=list)
    highlight_queue: List[HighlightEvent] = Field(default_factory=list)
    idle_spotlight: Optional[IdleSpotlight] = None
    idle_spotlights: List[IdleSpotlight] = Field(default_factory=list)
    active_connections: int = 0
    simulation_mode: bool = False
    display_settings: DisplaySettings = Field(default_factory=DisplaySettings)
