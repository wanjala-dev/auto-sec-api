"""MaxMind GeoLite2 adapter implementing GeoIPPort.

Reads ``<settings.GEOIP_PATH>/GeoLite2-City.mmdb``. The database file is
OPTIONAL — dev/test/CI run without it and every lookup then returns
``None`` (logged once at INFO, not per lookup). Fetch the database with
``scripts/fetch_geolite2.sh`` (needs a free MaxMind license key); see
``docs/reference/GEOIP_SETUP.md``.

The reader is opened lazily on first lookup and cached per adapter class
(one mmap for the whole process — ``geoip2.database.Reader`` is
thread-safe for reads).
"""

from __future__ import annotations

import contextlib
import ipaddress
import logging
import os
import threading

from components.identity.application.ports.geoip_port import GeoIPPort, GeoLocation

logger = logging.getLogger(__name__)

_DB_FILENAME = "GeoLite2-City.mmdb"


class MaxMindGeoIPAdapter(GeoIPPort):
    """GeoLite2-City backed lookup. Best-effort: returns None, never raises."""

    # Process-wide cached reader; None = not yet opened, False = known-missing.
    _reader = None
    _reader_lock = threading.Lock()

    @classmethod
    def _database_path(cls) -> str:
        from django.conf import settings

        return os.path.join(settings.GEOIP_PATH, _DB_FILENAME)

    @classmethod
    def _get_reader(cls):
        """Open (once) and cache the mmdb reader. False when unavailable."""
        if cls._reader is not None:
            return cls._reader
        with cls._reader_lock:
            if cls._reader is not None:
                return cls._reader
            path = cls._database_path()
            if not os.path.exists(path):
                logger.info("geoip_database_missing path=%s — session geo enrichment disabled", path)
                cls._reader = False
                return cls._reader
            try:
                import geoip2.database
                import maxminddb

                cls._reader = geoip2.database.Reader(path)
            except (OSError, ValueError, maxminddb.InvalidDatabaseError):
                # Unreadable/corrupt database — treat as absent.
                logger.exception("geoip_database_unreadable path=%s", path)
                cls._reader = False
        return cls._reader

    @classmethod
    def reset_cached_reader(cls) -> None:
        """Test seam: forget the cached reader so a new path is re-probed."""
        with cls._reader_lock:
            if cls._reader not in (None, False):
                with contextlib.suppress(OSError):  # close is best-effort
                    cls._reader.close()
            cls._reader = None

    def lookup(self, ip: str) -> GeoLocation | None:
        if not ip:
            return None
        try:
            parsed = ipaddress.ip_address(ip)
        except ValueError:
            logger.debug("geoip_lookup_invalid_ip")
            return None
        if not parsed.is_global:
            # Private / loopback / link-local / reserved — never in GeoLite2.
            return None

        reader = self._get_reader()
        if not reader:
            return None

        import geoip2.errors
        import maxminddb

        try:
            response = reader.city(ip)
        except geoip2.errors.AddressNotFoundError:
            return None
        except (OSError, ValueError, maxminddb.InvalidDatabaseError):
            logger.exception("geoip_lookup_failed")
            return None

        return GeoLocation(
            city=response.city.name or "",
            country=response.country.name or "",
            country_code=response.country.iso_code or "",
        )
