#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 -m venv "$ROOT_DIR/backend/.venv"
source "$ROOT_DIR/backend/.venv/bin/activate"
pip install --upgrade pip
pip install -r "$ROOT_DIR/backend/requirements.txt" -r "$ROOT_DIR/backend/requirements-dev.txt"

if [ ! -f "$ROOT_DIR/backend/.env" ]; then
  cp "$ROOT_DIR/backend/.env.example" "$ROOT_DIR/backend/.env"
fi

if [ ! -f "$ROOT_DIR/frontend/.env.local" ]; then
  cp "$ROOT_DIR/frontend/.env.example" "$ROOT_DIR/frontend/.env.local"
fi

printf "\nSetup complete. Activate the backend venv and run the app with:\n"
printf "cd %s/backend && source .venv/bin/activate && uvicorn app.main:app --reload\n" "$ROOT_DIR"
printf "\nOr start the frontend with:\n"
printf "cd %s/frontend && npm install && npm run dev\n" "$ROOT_DIR"
