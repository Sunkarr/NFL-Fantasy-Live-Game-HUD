import os
from pathlib import Path
from dotenv import load_dotenv

# Base directory paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = STATIC_DIR
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

# Load environment variables
ENV_FILE = BASE_DIR / ".env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)
else:
    load_dotenv()

# Sleeper League Configuration
LEAGUE_ID = os.getenv("LEAGUE_ID", "1390344846723543040")
TEAM_NAME = os.getenv("TEAM_NAME", "")
SEASON = os.getenv("SEASON", "2026")
TZ = os.getenv("TZ", "Europe/Berlin")

# Server & Poller Configuration
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8080"))
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "5.0"))
POLL_INTERVAL_SECONDS = POLL_INTERVAL
HIGHLIGHT_THRESHOLD = float(os.getenv("HIGHLIGHT_THRESHOLD", "5.0"))
HIGHLIGHT_DISPLAY_SECONDS = int(os.getenv("HIGHLIGHT_DISPLAY_SECONDS", "6"))

# File paths
PLAYERS_CACHE_FILE = DATA_DIR / "players_cache.json"

# Optional custom team color overrides (empty by default, assigned dynamically via DEFAULT_PALETTE)
MANAGER_COLORS = {}

COLOR_FREE_AGENT = "#94a3b8"  # Slate Gray for Free Agents / Unowned players

# Dynamic broadcast neon palette assigned deterministically by roster order
DEFAULT_PALETTE = [
    "#00f0ff",  # 1. Electric Cyan (Signature User Color)
    "#ff00aa",  # 2. Neon Hot Pink / Fuchsia
    "#a855f7",  # 3. Electric Purple
    "#ffaa00",  # 4. Electric Amber / Gold
    "#00e676",  # 5. Neon Spring Green
    "#ef4444",  # 6. Cardinal Red
    "#387aff",  # 7. Royal Azure Blue
    "#a3e635",  # 8. Electric Lime
    "#ff6b00",  # 9. Blaze Orange
    "#00f5d4",  # 10. Seafoam Mint
    "#e024c3",  # 11. Deep Magenta
    "#6366f1",  # 12. Electric Indigo
    "#facc15",  # 13. Cyber Yellow
    "#f43f8e",  # 14. Rose Quartz Pink
    "#14b8a6",  # 15. Bright Teal
    "#94a3b8",  # 16. Slate Gray
]
