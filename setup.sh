#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -f "$ROOT/.env" ]; then
  cp "$ROOT/.env.example" "$ROOT/.env"
  echo "==> Created .env from .env.example"
fi

echo "==> Backend"
cd "$ROOT/backend"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -r requirements.txt
# The OCR library pulls in OpenCV's desktop build, which needs graphics system
# libraries a fresh Linux / WSL doesn't have. The headless build doesn't.
./.venv/bin/pip uninstall --quiet --yes opencv-python
./.venv/bin/pip install --quiet opencv-python-headless==5.0.0.93
./.venv/bin/python manage.py migrate --noinput
./.venv/bin/python manage.py seed

echo
echo "==> Frontend"
cd "$ROOT/frontend"
npm install

echo
echo "Setup complete."
echo
echo "Start the backend:"
echo "  cd backend && source .venv/bin/activate && python manage.py runserver"
echo
echo "Start the frontend (in another terminal):"
echo "  cd frontend && npm run dev"
echo
echo "Then open http://localhost:5173"
