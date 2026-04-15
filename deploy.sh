#!/bin/bash
# ════════════════════════════════════════════════════════════════
# JARVIS Tender AI — Deployment Script for Hetzner VPS (Ubuntu)
# Usage: chmod +x deploy.sh && ./deploy.sh
# ════════════════════════════════════════════════════════════════

set -e

DOMAIN="jarvis.alltame.kz"
EMAIL="your@email.com"   # Change to your email for SSL certificate

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  JARVIS Tender AI — Deployment"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 1. Install Docker if not present
if ! command -v docker &> /dev/null; then
    echo "► Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
fi

# 2. Install Docker Compose if not present
if ! command -v docker compose &> /dev/null; then
    echo "► Installing Docker Compose..."
    apt-get install -y docker-compose-plugin
fi

# 3. Check .env file
if [ ! -f .env ]; then
    echo "► Creating .env from template..."
    cp .env.example .env
    echo ""
    echo "⚠️  ВАЖНО: Заполните файл .env перед продолжением!"
    echo "   nano .env"
    echo ""
    read -p "Нажмите Enter после заполнения .env..."
fi

# 4. Create SSL certificates directory
mkdir -p infrastructure/certbot/{conf,www}

# 5. Start services with HTTP only first (for SSL certificate)
echo "► Starting services (HTTP mode for SSL setup)..."
docker compose up -d postgres redis
sleep 5

# 6. Get SSL certificate
echo "► Obtaining SSL certificate for $DOMAIN..."
docker compose run --rm certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    -d "$DOMAIN" || echo "SSL already configured or domain not pointing to this server"

# 7. Build and start all services
echo "► Building and starting all services..."
docker compose build
docker compose up -d

# 8. Wait for services to be healthy
echo "► Waiting for services to start..."
sleep 15

# 9. Check health
echo "► Health check..."
curl -sf http://localhost:8000/health && echo " ✓ Backend OK" || echo " ✗ Backend not ready"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ JARVIS deployed!"
echo "  🌐 Dashboard: https://$DOMAIN"
echo "  📡 API:       https://$DOMAIN/api/docs"
echo "  🔍 Logs:      docker compose logs -f backend"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
