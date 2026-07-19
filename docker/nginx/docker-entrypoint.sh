#!/bin/sh
set -e

# Auto-select nginx config based on whether certs exist yet.
# On first deploy: no certs → HTTP-only config (serves ACME challenge + proxies to Django).
# After certbot issues certs → full HTTPS config with redirect.
# A background loop checks every 30s for new certs and reloads automatically.

DOMAIN="${API_DOMAIN:-api.wanjala.art}"
CERT="/etc/letsencrypt/live/$DOMAIN/fullchain.pem"
HTTPS_CONF="/etc/nginx/templates/nginx-https.conf"
HTTP_CONF="/etc/nginx/templates/nginx-initial.conf"

if [ -f "$CERT" ]; then
  echo "nginx: SSL cert found for $DOMAIN — using HTTPS config"
  cp "$HTTPS_CONF" /etc/nginx/conf.d/default.conf
else
  echo "nginx: No cert yet — using HTTP-only config (waiting for certbot)"
  cp "$HTTP_CONF" /etc/nginx/conf.d/default.conf

  # Background watcher: reload nginx once certbot-init obtains the cert
  (
    while true; do
      sleep 30
      if [ -f "$CERT" ]; then
        echo "nginx: Cert detected — switching to HTTPS"
        cp "$HTTPS_CONF" /etc/nginx/conf.d/default.conf
        nginx -s reload 2>/dev/null || true
        echo "nginx: HTTPS active for $DOMAIN"
        exit 0
      fi
    done
  ) &
fi

exec nginx -g "daemon off;"
