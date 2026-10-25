#!/usr/bin/env bash
# One-shot build for a single-service deploy (Render / Railway / VPS).
# Builds the React app, then Django serves it alongside the API.
set -euo pipefail
cd "$(dirname "$0")"

(cd frontend && npm ci && npm run build)

cd backend
pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate --noinput
python manage.py seed_demo --demo-tickets   # idempotent: safe on every deploy
