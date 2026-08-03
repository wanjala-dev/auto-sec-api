"""Unit tests for the EPSS + KEV feed parsers (pure — no network, no DB)."""

from __future__ import annotations

from datetime import date

import pytest

from components.vuln_intel.infrastructure.adapters.epss_feed_adapter import EpssFeedAdapter
from components.vuln_intel.infrastructure.adapters.kev_feed_adapter import KevFeedAdapter

pytestmark = pytest.mark.unit

_EPSS_CSV = (
    "#model_version:v2025.03.14,score_date:2026-08-03T00:00:00+0000\n"
    "cve,epss,percentile\n"
    "CVE-2024-3094,0.94255,0.99912\n"
    "CVE-2021-44228,0.94398,0.99931\n"
)


class TestEpssParse:
    def test_parses_metadata_and_records(self):
        snap = EpssFeedAdapter._parse(_EPSS_CSV, checksum="abc")
        assert snap.score_date == date(2026, 8, 3)
        assert snap.model_version == "v2025.03.14"
        assert snap.checksum == "abc"
        assert snap.record_count == 2
        by_cve = {r.cve: r for r in snap.records}
        assert by_cve["CVE-2024-3094"].epss == pytest.approx(0.94255)
        assert by_cve["CVE-2021-44228"].percentile == pytest.approx(0.99931)

    def test_missing_metadata_falls_back_to_today(self):
        snap = EpssFeedAdapter._parse("cve,epss,percentile\nCVE-2020-0001,0.1,0.5\n")
        assert snap.score_date == date.today()
        assert snap.record_count == 1

    def test_bad_rows_are_skipped_not_fatal(self):
        text = "#score_date:2026-08-03\ncve,epss,percentile\nCVE-1,notafloat,0.5\nCVE-2,0.2,0.6\n"
        snap = EpssFeedAdapter._parse(text)
        assert {r.cve for r in snap.records} == {"CVE-2"}

    def test_out_of_range_values_are_clamped(self):
        # S2: a feed value outside [0,1] is clamped at ingest so it can't trip EpssScore's
        # invariant at read time.
        text = "#score_date:2026-08-03\ncve,epss,percentile\nCVE-1,1.5,-0.2\n"
        snap = EpssFeedAdapter._parse(text)
        (record,) = snap.records
        assert record.epss == 1.0
        assert record.percentile == 0.0


class TestKevParse:
    def test_parses_version_and_records(self):
        data = {
            "catalogVersion": "2026.08.01",
            "vulnerabilities": [
                {"cveID": "CVE-2021-44228", "dateAdded": "2021-12-10", "knownRansomwareCampaignUse": "Known"},
                {"cveID": "CVE-2024-3094", "dateAdded": "2024-03-29", "knownRansomwareCampaignUse": "Unknown"},
            ],
        }
        snap = KevFeedAdapter._parse(data, checksum="zzz")
        assert snap.catalog_version == "2026.08.01"
        assert snap.record_count == 2
        by_cve = {r.cve: r for r in snap.records}
        assert by_cve["CVE-2021-44228"].known_ransomware is True
        assert by_cve["CVE-2021-44228"].date_added == date(2021, 12, 10)
        assert by_cve["CVE-2024-3094"].known_ransomware is False

    def test_missing_catalog_version_raises(self):
        from components.vuln_intel.domain.errors import MalformedFeedError

        with pytest.raises(MalformedFeedError):
            KevFeedAdapter._parse({"vulnerabilities": []})

    def test_rows_without_cve_are_skipped(self):
        data = {"catalogVersion": "v1", "vulnerabilities": [{"cveID": ""}, {"cveID": "CVE-9"}]}
        snap = KevFeedAdapter._parse(data)
        assert {r.cve for r in snap.records} == {"CVE-9"}
