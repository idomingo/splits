#!/usr/bin/env bash
# Test the Garmin key and list which endpoints answer. Never prints the key.
set -euo pipefail
cd "$(dirname "$0")"
# shellcheck disable=SC1091
source .venv/bin/activate
exec python manage.py garmin_check
