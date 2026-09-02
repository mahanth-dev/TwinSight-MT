#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi
mkdir -p data
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py load_backup
echo
echo "TwinSight · محصول MT → http://127.0.0.1:8765/"
exec .venv/bin/python manage.py runserver 0.0.0.0:8765
