#!/bin/bash
# =============================================================================
# SSL initialization script for EC2 deployment.
#
# Run this ONCE after the first deploy to obtain Let's Encrypt certificates,
# then swap Nginx to the full HTTPS config.
#
# Usage (from the api-v2.0 directory on the EC2 instance):
#   bash docker/nginx/init-ssl.sh api.wanjala.art your-email@example.com
# =============================================================================

set -euo pipefail

DOMAIN="${1:?Usage: $0 <domain> <email>}"
EMAIL="${2:?Usage: $0 <domain> <email>}"
COMPOSE_CMD="docker compose -f docker/compose/docker-compose.yml -f docker/compose/docker-compose.ec2.yml"

echo "==> Step 1: Starting stack with initial (HTTP-only) Nginx config..."
cp docker/nginx/nginx-initial.conf docker/nginx/active.conf
$COMPOSE_CMD up -d

echo "==> Step 2: Waiting for Nginx to be ready..."
sleep 5

echo "==> Step 3: Requesting certificate from Let's Encrypt..."
$COMPOSE_CMD run --rm certbot certonly \
  --webroot \
  -w /var/www/certbot \
  -d "$DOMAIN" \
  --email "$EMAIL" \
  --agree-tos \
  --no-eff-email

echo "==> Step 4: Switching to HTTPS Nginx config..."
cp docker/nginx/nginx.conf docker/nginx/active.conf

echo "==> Step 5: Reloading Nginx..."
$COMPOSE_CMD exec nginx nginx -s reload

echo ""
echo "Done! HTTPS is now live at https://$DOMAIN"
echo "Certbot will auto-renew via the certbot container's entrypoint."
