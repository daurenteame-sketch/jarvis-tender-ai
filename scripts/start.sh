#!/bin/bash
# Daily startup — pulls latest code, rebuilds containers, runs smoke test.
# This is the single command you run when you sit down to work each day.
#
# Why rebuild on every start: code changes in frontend/ and backend/ get baked
# into Docker images at build time (no volume-mount). Skipping --build gives
# you yesterday's bundle even if you git pulled new code today.

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

source "$SCRIPT_DIR/_lib.sh"
locate_docker

echo "==> 1/6 Pulling latest code from GitHub..."
git fetch origin
LOCAL=$(git rev-parse main)
REMOTE=$(git rev-parse origin/main)
if [ "$LOCAL" != "$REMOTE" ]; then
  echo "  remote has new commits — pulling"
  git pull --ff-only origin main
else
  echo "  already up to date"
fi

echo "==> 2/6 Running backend regression tests (no docker needed yet)..."
if python -c "import pytest" 2>/dev/null; then
  ( cd backend && python -m pytest tests/ -q --tb=short ) || {
    echo "  ❌ regression tests failed — fix before proceeding"
    exit 1
  }
else
  echo "  ⚠ pytest not installed (pip install pytest) — skipping local tests"
  echo "    GitHub Actions CI will catch regressions on push regardless"
fi

echo "==> 3/6 Building backend + frontend (only rebuilds layers that changed)..."
dc up -d --build backend frontend

echo "==> 4/6 Waiting for backend to become healthy..."
for i in 1 2 3 4 5 6 7 8 9 10; do
  status=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health 2>/dev/null || echo "000")
  if [ "$status" = "200" ]; then
    echo "  backend healthy after ${i}x3s"
    break
  fi
  [ $i -eq 10 ] && { echo "  backend never came up — check 'docker logs jarvis-tender-ai-backend-1'"; exit 1; }
  sleep 3
done

echo "==> 5/6 Waiting for frontend..."
for i in 1 2 3 4 5; do
  status=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:3000 2>/dev/null || echo "000")
  if [ "$status" = "200" ]; then
    echo "  frontend ready"
    break
  fi
  [ $i -eq 5 ] && { echo "  frontend not responding — check 'docker logs jarvis-tender-ai-frontend-1'"; exit 1; }
  sleep 3
done

echo "==> 6/6 Running smoke test..."
bash "$SCRIPT_DIR/smoke-test.sh"

echo
echo "Платформа готова: http://localhost:3000"
echo "Login: admin@tender.ai / admin123"
