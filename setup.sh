#!/usr/bin/env bash
# One-time setup: Python environment, packages and database.
set -euo pipefail
cd "$(dirname "$0")"

PY=""
for cand in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$cand" >/dev/null 2>&1; then
    if "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      PY="$cand"; break
    fi
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10 or newer is needed. With Homebrew: brew install python@3.12"
  exit 1
fi
echo "Using $($PY --version)"

[ -d .venv ] || "$PY" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
mkdir -p data
python manage.py migrate -v0

if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
  echo "Created .env: paste your Garmin key into it."
fi
if grep -qE '^GARMIN_PERSONAL_API_KEY=.+' .env; then
  echo "Garmin key: set"
else
  echo "Garmin key: NOT set yet (edit .env)"
fi
echo
echo "Done. Next:"
echo "  ./check.sh   test the key and see which Garmin data is available"
echo "  ./run.sh     open the dashboard (click Sync now to fetch your history)"
echo "  ./run.sh demo   look around with demo data first"
