#!/bin/bash
# Start the Lance Viewer server (recommended to run in a terminal for long-term stability)
# Usage: ./start.sh [port]
PORT="${1:-8770}"
cd "$(dirname "$0")"
# Virtualenv path (default .venv; change to your own location)
VENV_PY="${VENV_PY:-.venv/bin/python}"
echo "Starting Lance Viewer: http://127.0.0.1:${PORT}"
echo "Press Ctrl+C to stop"
exec "$VENV_PY" -m lance_viewer.server --host 127.0.0.1 --port "$PORT"
