#!/bin/bash
# ─────────────────────────────────────────────────────────────
# JARVIS Tender AI — Local Development Startup
# Usage: bash start-dev.sh
# ─────────────────────────────────────────────────────────────
set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  JARVIS Tender AI — LOCAL DEV START"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check .env exists
if [ ! -f .env ]; then
  echo "❌ .env file not found. Copy and edit it:"
  echo "   cp .env .env.bak && nano .env"
  exit 1
fi

echo "► Stopping old containers..."
docker compose -f docker-compose.yml -f docker-compose.dev.yml down --remove-orphans 2>/dev/null || true

echo "► Building images..."
docker compose -f docker-compose.yml -f docker-compose.dev.yml build

echo "► Starting services..."
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

echo ""
echo "► Waiting for backend to be ready..."
for i in $(seq 1 30); do
  if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
    echo "  ✓ Backend is up!"
    break
  fi
  echo -n "  . "
  sleep 2
done

echo ""
echo "► Checking admin user..."
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec -T backend python create_admin.py 2>/dev/null || \
  echo "  (Admin will be created automatically on next backend restart)"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ JARVIS is running!"
echo ""
echo "  🌐 Frontend:  http://localhost:3000"
echo "  🔧 Backend:   http://localhost:8000"
echo "  📡 API Docs:  http://localhost:8000/api/docs"
echo ""
echo "  👤 Admin login:"
echo "     Email:    admin@tender.ai"
echo "     Password: admin123"
echo ""
echo "  📋 Logs:  docker compose logs -f backend frontend"
echo "  🛑 Stop:  docker compose -f docker-compose.yml -f docker-compose.dev.yml down"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
