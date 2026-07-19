"""Unit tests for the RFC 9745 / 8594 deprecation header builder.

Pure function — no DB, no settings, no request.
"""

from datetime import datetime

from components.shared_platform.infrastructure.middleware.api_deprecation_middleware import (
    build_deprecation_headers,
)

_VALID = {
    "deprecation": "2026-06-19T00:00:00Z",
    "sunset": "2027-06-19T00:00:00Z",
    "successor": "/api/v2/",
    "link": "https://docs.wanjala.art/api/migrating-v1-v2",
}


def test_valid_entry_emits_rfc_compliant_headers():
    headers = build_deprecation_headers(_VALID)

    # RFC 9745: Deprecation is a structured-field Date — "@" + unix seconds.
    expected_epoch = int(datetime.fromisoformat("2026-06-19T00:00:00+00:00").timestamp())
    assert headers["Deprecation"] == "@%d" % expected_epoch

    # RFC 8594: Sunset is an HTTP-date (IMF-fixdate, ends in GMT).
    assert headers["Sunset"].endswith("GMT")
    assert "2027" in headers["Sunset"]

    assert '<https://docs.wanjala.art/api/migrating-v1-v2>; rel="deprecation"' in headers["Link"]
    assert '</api/v2/>; rel="successor-version"' in headers["Link"]


def test_sunset_before_deprecation_is_rejected():
    bad = {**_VALID, "sunset": "2025-01-01T00:00:00Z"}  # before deprecation
    assert build_deprecation_headers(bad) == {}


def test_missing_dates_yield_no_headers():
    assert build_deprecation_headers({}) == {}
    assert build_deprecation_headers({"successor": "/api/v2/"}) == {}


def test_successor_only_entry_has_no_deprecation_link():
    entry = {"deprecation": _VALID["deprecation"], "sunset": _VALID["sunset"], "successor": "/api/v2/"}
    headers = build_deprecation_headers(entry)
    assert headers["Link"] == '</api/v2/>; rel="successor-version"'


def test_no_links_when_neither_successor_nor_link_given():
    entry = {"deprecation": _VALID["deprecation"], "sunset": _VALID["sunset"]}
    headers = build_deprecation_headers(entry)
    assert "Deprecation" in headers and "Sunset" in headers
    assert "Link" not in headers


def test_parse_iso_is_always_timezone_aware():
    """A parsed sunset/deprecation MUST be tz-aware regardless of the source.

    Regression: a naive parse blew up the sunset comparison with
    ``can't compare offset-naive and offset-aware datetimes`` (TypeError) on
    every ``/api/v0/`` request in prod, because ``base.py`` runs ``USE_TZ=False``
    so Django's ``now`` was naive while the parsed value was aware. ``_parse_iso``
    now assumes UTC for an offset-less source so both sides are always aware.
    """
    from components.shared_platform.infrastructure.middleware.api_deprecation_middleware import (
        _parse_iso,
    )

    assert _parse_iso("2027-06-19T00:00:00Z").tzinfo is not None
    assert _parse_iso("2027-06-19T00:00:00+00:00").tzinfo is not None
    # No offset in the source — must still come back aware (assumed UTC).
    assert _parse_iso("2027-06-19T00:00:00").tzinfo is not None
    assert _parse_iso(None) is None
    assert _parse_iso("") is None


def test_sunset_has_passed_future_date_is_false_and_does_not_raise():
    """Future sunset → not passed → serve+stamp (no 410). MUST NOT raise.

    This is the exact path that 500'd in prod: with ``sunset`` in 2027 the
    comparison should quietly return False, never a TypeError.
    """
    from components.shared_platform.infrastructure.middleware.api_deprecation_middleware import (
        _sunset_has_passed,
    )

    assert _sunset_has_passed(_VALID) is False
    assert _sunset_has_passed({"sunset": "2099-01-01T00:00:00Z"}) is False
    # Offset-less config date must also be safe.
    assert _sunset_has_passed({"sunset": "2099-01-01T00:00:00"}) is False


def test_sunset_has_passed_past_date_is_true():
    """A sunset in the past → passed → triggers the 410 gate."""
    from components.shared_platform.infrastructure.middleware.api_deprecation_middleware import (
        _sunset_has_passed,
    )

    assert _sunset_has_passed({"sunset": "2000-01-01T00:00:00Z"}) is True


def test_sunset_has_passed_missing_date_fails_open():
    """No/garbled sunset → fail open (keep serving), never reject."""
    from components.shared_platform.infrastructure.middleware.api_deprecation_middleware import (
        _sunset_has_passed,
    )

    assert _sunset_has_passed({}) is False
    assert _sunset_has_passed({"sunset": None}) is False
