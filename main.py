import os
import sys
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Body, Response
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from src.config import (
    LEAGUE_ID, TEAM_NAME, POLL_INTERVAL_SECONDS, HOST, PORT,
    STATIC_DIR, TEMPLATES_DIR
)
from src.ws_manager import ConnectionManager
from src.state_engine import HUDStateEngine

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("HUDServer")

# Initialize WebSocket Manager & State Engine
ws_manager = ConnectionManager()
engine = HUDStateEngine(ws_manager)

# Background Polling Task Loop
polling_task: Optional[asyncio.Task] = None


async def background_poller():
    """Continuously poll Sleeper and ESPN every POLL_INTERVAL_SECONDS."""
    while True:
        try:
            await engine.refresh_state()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in background polling cycle: {e}")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle startup and shutdown handler."""
    global polling_task
    logger.info("Initializing NFL Fantasy Live Game HUD...")
    try:
        await engine.initialize()
    except Exception as e:
        logger.warning(f"Engine bootstrap warning: {e}. Will retry during background polling.")

    logger.info(f"Starting background poller (Interval: {POLL_INTERVAL_SECONDS}s)...")
    polling_task = asyncio.create_task(background_poller())
    
    yield

    # Shutdown
    if polling_task:
        polling_task.cancel()
        try:
            await polling_task
        except asyncio.CancelledError:
            pass
    logger.info("HUD Server shut down gracefully.")


app = FastAPI(title="NFL Fantasy Live Game HUD", lifespan=lifespan)

# Mount Static Files (CSS, JS, Assets)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ==============================================================================
# Health & Status Endpoints
# ==============================================================================

@app.get("/health")
async def health():
    """Health check endpoint for native macOS app and monitoring."""
    return {"status": "ok", "version": "1.0", "engine": "running"}


@app.get("/api/health")
async def api_health():
    """API health alias."""
    return {"status": "ok", "version": "1.0", "engine": "running"}


# ==============================================================================
# HTTP Endpoints (HTML Pages)
# ==============================================================================

@app.get("/favicon.ico")
async def favicon():
    """Silence favicon 404s."""
    return Response(status_code=204)


@app.get("/", response_class=HTMLResponse)
async def get_index():
    """Redirect or serve overlay."""
    for candidate in [STATIC_DIR / "overlay.html", TEMPLATES_DIR / "overlay.html"]:
        if candidate.exists():
            return FileResponse(candidate)
    return HTMLResponse("<h1>NFL Fantasy Live Game HUD</h1><p>Navigate to <a href='/overlay'>/overlay</a> or <a href='/admin'>/admin</a></p>")


@app.get("/overlay", response_class=HTMLResponse)
async def get_overlay():
    """Full-screen transparent HUD overlay."""
    for candidate in [STATIC_DIR / "overlay.html", TEMPLATES_DIR / "overlay.html"]:
        if candidate.exists():
            return FileResponse(candidate)
    raise HTTPException(status_code=404, detail="Overlay template not found.")


@app.get("/admin", response_class=HTMLResponse)
async def get_admin():
    """Control & Testing Dashboard."""
    admin_file = STATIC_DIR / "admin.html"
    if not admin_file.exists():
        raise HTTPException(status_code=404, detail="Admin panel file not found.")
    return FileResponse(admin_file)


# ==============================================================================
# API Endpoints
# ==============================================================================

@app.get("/api/state")
async def get_state():
    """Get full JSON snapshot of current HUD state."""
    if not engine.current_state:
        await engine.refresh_state(is_initial=True)
    return engine.current_state.model_dump() if engine.current_state else {}


@app.post("/api/settings/week")
@app.post("/api/week")
async def set_week(week: Optional[int] = Body(None, embed=True)):
    """Override or reset the active NFL week."""
    engine.set_week(week)
    await engine.refresh_state()
    return {"status": "ok", "week": engine.week_override or "auto"}


@app.post("/api/settings/display")
@app.post("/api/settings")
async def set_display_settings(
    mode: Optional[str] = Body(None, embed=True),
    speed: Optional[str] = Body(None, embed=True),
    interval: Optional[int] = Body(None, embed=True),
    ticker_speed: Optional[int] = Body(None, embed=True),
    sound_enabled: Optional[bool] = Body(None, embed=True),
    sound_theme: Optional[str] = Body(None, embed=True)
):
    """Set matchup display mode, animation speed, and sound settings."""
    settings = engine.set_display_settings(
        mode=mode,
        speed=speed,
        interval=interval,
        ticker_speed=ticker_speed,
        sound_enabled=sound_enabled,
        sound_theme=sound_theme
    )
    if engine.current_state:
        engine.current_state.display_settings = settings
        await ws_manager.broadcast({
            "type": "UPDATE_DISPLAY_SETTINGS",
            "settings": settings.model_dump()
        })
    return {"status": "ok", "settings": settings.model_dump()}


@app.post("/api/settings/sound-theme")
async def set_sound_theme(sound_theme: str = Body("fox_horn", embed=True)):
    """Set highlight sound effect theme (fox_horn, redzone, td_siren, brass_fanfare)."""
    settings = engine.set_display_settings(sound_theme=sound_theme)
    if engine.current_state:
        engine.current_state.display_settings = settings
        await ws_manager.broadcast({
            "type": "UPDATE_DISPLAY_SETTINGS",
            "settings": settings.model_dump()
        })
    return {"status": "ok", "settings": settings.model_dump()}


@app.post("/api/settings/sound")
async def toggle_sound(sound_enabled: Optional[bool] = Body(None, embed=True)):
    """Toggle or set highlight sound enabled state."""
    new_val = (not engine.display_settings.sound_enabled) if sound_enabled is None else sound_enabled
    settings = engine.set_display_settings(sound_enabled=new_val)
    if engine.current_state:
        engine.current_state.display_settings = settings
        await ws_manager.broadcast({
            "type": "UPDATE_DISPLAY_SETTINGS",
            "settings": settings.model_dump()
        })
    return {"status": "ok", "sound_enabled": settings.sound_enabled}


@app.post("/api/test/mock-league")
async def mock_league(teams_count: int = Body(12, embed=True)) :
    """Generate a simulated league with 6, 8, 10, 12, 14, or 16 teams."""
    state = engine.generate_mock_league(teams_count)
    await ws_manager.broadcast({
        "type": "UPDATE_MATCHUPS",
        "state": state.model_dump()
    })
    return {"status": "ok", "teams_count": teams_count, "matchups_count": len(state.matchups)}


@app.post("/api/test/highlight")
async def trigger_test_highlight(
    player_name: str = Body("Josh Allen", embed=True),
    delta_points: float = Body(6.4, embed=True),
    fantasy_team_name: str = Body("auto", embed=True),
    position: str = Body("QB", embed=True),
    nfl_team: str = Body("BUF", embed=True),
    headshot_url: Optional[str] = Body(None, embed=True),
    highlight_type: Optional[str] = Body(None, embed=True),
    is_touchdown: Optional[bool] = Body(None, embed=True)
):
    """Trigger a manual test highlight event with custom parameters."""
    highlight = engine.trigger_test_highlight(
        player_name=player_name,
        delta_points=delta_points,
        fantasy_team_name=fantasy_team_name,
        position=position,
        nfl_team=nfl_team,
        headshot_url=headshot_url,
        highlight_type=highlight_type,
        is_touchdown=is_touchdown
    )
    await ws_manager.broadcast({
        "type": "PUSH_HIGHLIGHT",
        "highlight": highlight.model_dump()
    })
    return {"status": "ok", "highlight": highlight.model_dump()}


@app.post("/api/test/simulate-delta")
async def simulate_delta():
    """Simulate a random fantasy scoring play."""
    highlight = engine.simulate_random_delta()
    if highlight:
        await ws_manager.broadcast({
            "type": "PUSH_HIGHLIGHT",
            "highlight": highlight.model_dump()
        })
    return {"status": "ok", "highlight": highlight.model_dump() if highlight else None}


@app.post("/api/test/toggle-simulation")
async def toggle_simulation(enable: Optional[bool] = Body(None, embed=True)):
    """Enable or disable background test play simulation."""
    is_active = engine.toggle_simulation(enable)
    return {"status": "ok", "simulation_active": is_active}


# ==============================================================================
# WebSocket Endpoint
# ==============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Real-time bi-directional event stream to connected HUD overlays."""
    await ws_manager.connect(websocket)
    try:
        # Send initial snapshot immediately upon connect
        if engine.current_state:
            await websocket.send_json({
                "type": "INITIAL_STATE",
                "state": engine.current_state.model_dump()
            })

        while True:
            data = await websocket.receive_json()
            # Handle client-side commands or pings
            msg_type = data.get("type")
            if msg_type == "PING":
                await websocket.send_json({"type": "PONG"})
            elif msg_type == "REQUEST_STATE":
                if engine.current_state:
                    await websocket.send_json({
                        "type": "INITIAL_STATE",
                        "state": engine.current_state.model_dump()
                    })
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.warning(f"WebSocket connection encountered error: {e}")
        ws_manager.disconnect(websocket)


# ==============================================================================
# Standalone CLI Entry Point
# ==============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=HOST, port=PORT, reload=False)
