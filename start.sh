#!/bin/bash
# NFL Fantasy Live Game HUD Starter Script
# Automatically verifies dependencies and launches backend

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

chmod +x run_backend.sh
exec ./run_backend.sh
