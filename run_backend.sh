#!/bin/bash
# ==============================================================================
# NFL Fantasy Live Game HUD — Self-Contained Backend Runner
# Automatically creates virtualenv, installs dependencies and manages port
# ==============================================================================

set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

export PATH="/opt/homebrew/bin:/usr/local/bin:/opt/anaconda3/bin:$PATH"

# 1. Check Python 3
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: python3 is not installed on this system."
    exit 1
fi

# 2. Check / Create Virtual Environment
VENV_DIR="$DIR/.venv"
if [ ! -d "$VENV_DIR" ] || [ ! -f "$VENV_DIR/bin/python" ]; then
    echo "📦 Creating isolated Python virtual environment (.venv)..."
    python3 -m venv "$VENV_DIR"
fi

# 3. Check and Install Dependencies
PYTHON_BIN="$VENV_DIR/bin/python"
PIP_BIN="$VENV_DIR/bin/pip"

if [ -f "requirements.txt" ]; then
    # Quick check if all required libraries are importable
    if ! "$PYTHON_BIN" -c "import fastapi, uvicorn, websockets, httpx, dotenv, pydantic, requests" 2>/dev/null; then
        echo "⬇️  Installing required dependencies from requirements.txt..."
        "$PIP_BIN" install -q --upgrade pip
        "$PIP_BIN" install -q -r requirements.txt
        echo "✅ Dependencies installed successfully!"
    fi
fi

# 4. Check .env
if [ ! -f .env ] && [ -f .env.example ]; then
    cp .env.example .env
fi

# 5. Free port 8080 if an older server instance is still occupying it
PORT=8080
OCCUPIED_PIDS=$(lsof -ti :$PORT 2>/dev/null || true)
if [ -n "$OCCUPIED_PIDS" ]; then
    echo "🔄 Freeing port $PORT (cleaning previous instance PIDs: $OCCUPIED_PIDS)..."
    kill -9 $OCCUPIED_PIDS 2>/dev/null || true
    sleep 0.5
fi

# 6. Start Server
echo "🚀 Starting NFL Fantasy HUD Backend Server on http://0.0.0.0:$PORT..."
exec "$PYTHON_BIN" -m uvicorn main:app --host 0.0.0.0 --port $PORT
