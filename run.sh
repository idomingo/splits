#!/usr/bin/env bash
# Start the dashboard on http://127.0.0.1:8000  (./run.sh demo for demo data)
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || { echo "Run ./setup.sh first."; exit 1; }
# shellcheck disable=SC1091
source .venv/bin/activate
PORT="${PORT:-8000}"
if [ "${1:-}" = "demo" ]; then
  export DB_PATH="data/demo.sqlite3"
  if [ ! -f "$DB_PATH" ]; then
    python manage.py migrate -v0
    python manage.py seed_demo
  fi
fi
python manage.py migrate -v0
URL="http://127.0.0.1:$PORT"
echo "Dashboard: $URL  (Ctrl+C to stop)"
( sleep 1.5; command -v open >/dev/null && open "$URL" ) >/dev/null 2>&1 &
# reloads by itself when the code changes; a sync running at that moment stops and can be restarted
exec python manage.py runserver "127.0.0.1:$PORT"
