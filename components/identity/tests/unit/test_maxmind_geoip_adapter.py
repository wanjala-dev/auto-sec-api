"""Unit tests: MaxMind GeoIP adapter degrades to None, never raises (T2-S2).

Dev/test/CI have no GeoLite2-City.mmdb on disk — every lookup must return
None. Private and invalid IPs short-circuit before the database is even
probed.
"""

from __future__ import annotations

import pytest

from components.identity.infrastructure.adapters.maxmind_geoip_adapter import MaxMindGeoIPAdapter

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_reader_cache():
    MaxMindGeoIPAdapter.reset_cached_reader()
    yield
    MaxMindGeoIPAdapter.reset_cached_reader()


class TestMissingDatabase:
    def test_lookup_returns_none_when_mmdb_absent(self, settings, tmp_path):
        settings.GEOIP_PATH = str(tmp_path)  # exists, but holds no mmdb
        adapter = MaxMindGeoIPAdapter()
        assert adapter.lookup("8.8.8.8") is None

    def test_lookup_returns_none_when_geoip_dir_absent(self, settings, tmp_path):
        settings.GEOIP_PATH = str(tmp_path / "does-not-exist")
        adapter = MaxMindGeoIPAdapter()
        assert adapter.lookup("8.8.8.8") is None

    def test_missing_database_result_is_cached(self, settings, tmp_path, monkeypatch):
        settings.GEOIP_PATH = str(tmp_path)
        adapter = MaxMindGeoIPAdapter()
        assert adapter.lookup("8.8.8.8") is None

        # A second lookup must not re-probe the filesystem.
        import components.identity.infrastructure.adapters.maxmind_geoip_adapter as module

        def _boom(_path):  # pragma: no cover - failure branch
            raise AssertionError("filesystem re-probed despite cached miss")

        monkeypatch.setattr(module.os.path, "exists", _boom)
        assert adapter.lookup("8.8.8.8") is None

    def test_corrupt_database_treated_as_absent(self, settings, tmp_path):
        (tmp_path / "GeoLite2-City.mmdb").write_bytes(b"not a real mmdb")
        settings.GEOIP_PATH = str(tmp_path)
        adapter = MaxMindGeoIPAdapter()
        assert adapter.lookup("8.8.8.8") is None


class TestIpShortCircuits:
    """These never touch settings or the filesystem."""

    @pytest.mark.parametrize(
        "ip",
        [
            "",
            None,
            "not-an-ip",
            "999.1.1.1",
            "10.0.0.2",  # private
            "192.168.1.10",  # private
            "127.0.0.1",  # loopback
            "169.254.0.5",  # link-local
            "::1",  # v6 loopback
            "fe80::1",  # v6 link-local
        ],
    )
    def test_invalid_or_non_global_ips_return_none(self, ip):
        assert MaxMindGeoIPAdapter().lookup(ip) is None
