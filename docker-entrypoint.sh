#!/bin/sh
set -e
mkdir -p data/uploads data/rival-cache
python manage.py migrate --noinput
exec python manage.py runserver 0.0.0.0:8765 --noreload
