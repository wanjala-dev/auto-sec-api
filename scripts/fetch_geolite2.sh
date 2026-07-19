#!/usr/bin/env bash
# Fetch the MaxMind GeoLite2-City database used for login-session geo
# enrichment (components/identity — MaxMindGeoIPAdapter).
#
# Usage:
#   MAXMIND_LICENSE_KEY=<your-free-key> ./scripts/fetch_geolite2.sh [dest-dir]
#
# dest-dir defaults to ./geoip (the default settings.GEOIP_PATH). A free
# license key comes with a (free) MaxMind account:
# https://www.maxmind.com/en/geolite2/signup → "Manage License Keys".
#
# The database file is OPTIONAL at runtime — without it the GeoIP adapter
# returns None for every lookup and sessions enrich with device facts
# only. See docs/reference/GEOIP_SETUP.md.
set -euo pipefail

if [[ -z "${MAXMIND_LICENSE_KEY:-}" ]]; then
    echo "ERROR: MAXMIND_LICENSE_KEY env var is required (free key: https://www.maxmind.com/en/geolite2/signup)" >&2
    exit 1
fi

DEST_DIR="${1:-$(cd "$(dirname "$0")/.." && pwd)/geoip}"
EDITION="GeoLite2-City"
URL="https://download.maxmind.com/app/geoip_download?edition_id=${EDITION}&license_key=${MAXMIND_LICENSE_KEY}&suffix=tar.gz"

mkdir -p "$DEST_DIR"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "Downloading ${EDITION} …"
curl -fsSL "$URL" -o "$TMP_DIR/${EDITION}.tar.gz"

echo "Extracting …"
tar -xzf "$TMP_DIR/${EDITION}.tar.gz" -C "$TMP_DIR"

MMDB_PATH="$(find "$TMP_DIR" -name "${EDITION}.mmdb" -print -quit)"
if [[ -z "$MMDB_PATH" ]]; then
    echo "ERROR: ${EDITION}.mmdb not found in the downloaded archive" >&2
    exit 1
fi

mv "$MMDB_PATH" "$DEST_DIR/${EDITION}.mmdb"
echo "Installed $DEST_DIR/${EDITION}.mmdb"
echo "If GEOIP_PATH is overridden in the environment, make sure it points at: $DEST_DIR"
