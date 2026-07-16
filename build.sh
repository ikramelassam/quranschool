#!/usr/bin/env bash
# Exécuté par Render au build. Génère staticfiles/staticfiles.json (WhiteNoise)
# avant que gunicorn ne démarre, sinon {% static %} plante avec
# "ValueError: Missing staticfiles manifest entry" (page 500 sans traceback).
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate
