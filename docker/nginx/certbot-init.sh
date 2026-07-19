#!/bin/sh
set -e

# Certbot init — obtains SSL certificate for the API domain.
# Frontend is on CloudFront (HTTPS built-in, no cert needed here).

DOMAIN="${API_DOMAIN:-api.wanjala.art}"
EMAIL="${CERTBOT_EMAIL:-c0d3henry@gmail.com}"
CERT_DIR="/etc/letsencrypt/live/$DOMAIN"

if [ -f "$CERT_DIR/fullchain.pem" ] && [ -f "$CERT_DIR/privkey.pem" ]; then
  echo "certbot-init: Certs already exist for $DOMAIN — skipping"
  exit 0
fi

echo "certbot-init: Waiting for nginx to be ready..."
sleep 10

echo "certbot-init: Requesting certificate for $DOMAIN..."
certbot certonly \
  --webroot \
  -w /var/www/certbot \
  -d "$DOMAIN" \
  --email "$EMAIL" \
  --agree-tos \
  --no-eff-email \
  --non-interactive

if [ -f "$CERT_DIR/fullchain.pem" ]; then
  echo "certbot-init: Certificate obtained for $DOMAIN"
  echo "$DOMAIN" > /etc/letsencrypt/.cert-ready
  exit 0
else
  echo "certbot-init: Certificate request failed for $DOMAIN"
  exit 1
fi
