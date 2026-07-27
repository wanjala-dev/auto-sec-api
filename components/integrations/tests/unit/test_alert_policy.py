"""Pure severity-gate tests."""

from __future__ import annotations

import pytest

from components.integrations.domain.alert_policy import severity_meets_threshold

pytestmark = pytest.mark.unit


def test_at_or_above_threshold_passes():
    assert severity_meets_threshold("critical", "high")
    assert severity_meets_threshold("high", "high")


def test_below_threshold_blocked():
    assert not severity_meets_threshold("medium", "high")
    assert not severity_meets_threshold("low", "critical")


def test_informational_is_lowest():
    assert severity_meets_threshold("informational", "informational")
    assert not severity_meets_threshold("informational", "low")


def test_unknown_severity_never_passes_on_its_own():
    assert not severity_meets_threshold("nonsense", "high")


def test_blank_threshold_falls_back_to_default_high():
    # default is HIGH, so medium is blocked, critical passes
    assert not severity_meets_threshold("medium", "")
    assert severity_meets_threshold("critical", "")
