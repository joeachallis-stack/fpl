#!/bin/zsh
set -euo pipefail

PROJECT_DIR="${0:A:h}"
cd "$PROJECT_DIR"

if [[ ! -d frontend/node_modules ]]; then
  echo "Installing the local frontend dependencies…"
  npm --prefix frontend install
fi

echo "Building FPL Decision Room…"
npm --prefix frontend run build

echo "Opening http://127.0.0.1:8765"
python scripts/frontend_server.py &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT INT TERM

sleep 1
open http://127.0.0.1:8765
wait "$SERVER_PID"
