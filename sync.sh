#!/usr/bin/env bash
# Fetch new Garmin data from the terminal (same as the Sync button).
#   ./sync.sh            only what is new
#   ./sync.sh --full     re-read everything
#   ./sync.sh --recheck  retry data sets that were marked as not available
set -euo pipefail
cd "$(dirname "$0")"
# shellcheck disable=SC1091
source .venv/bin/activate
exec python manage.py sync_garmin "$@"
