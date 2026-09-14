#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

LEADGEN_PORT="${LEADGEN_PORT:-8040}"
if [[ "${1:-}" == "--fresh" ]]; then
  export LEADGEN_DB_PATH="$PWD/backend/data/rehearsal-$(date -u +%Y%m%dT%H%M%SZ)-$$.db"
  echo "Opening a fresh rehearsal workspace. Existing research is preserved."
elif [[ $# -gt 0 ]]; then
  echo "Usage: ./start.sh [--fresh]"
  exit 2
fi

if ! [[ -x .venv/bin/python ]] || ! .venv/bin/python -c 'import fastapi, uvicorn, langgraph, langgraph.checkpoint.sqlite' 2>/dev/null; then
  if ! command -v uv >/dev/null 2>&1; then
    echo "Install uv (https://docs.astral.sh/uv/getting-started/installation/) and run this script again."
    exit 1
  fi
  uv sync --locked
fi

if ! [[ -f frontend/dist/index.html ]]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "Node.js with npm is needed for the initial frontend build."
    exit 1
  fi
  if ! [[ -d frontend/node_modules ]]; then
    npm ci --prefix frontend --no-audit --no-fund
  fi
  npm run build --prefix frontend
fi

echo
echo "Lead Gen Platform is opening at http://127.0.0.1:$LEADGEN_PORT"
echo "Keep this terminal open. Press Ctrl+C to stop."
echo "Live research uses Gemini configuration. Captured replay also works offline."
echo
exec .venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port "$LEADGEN_PORT"
