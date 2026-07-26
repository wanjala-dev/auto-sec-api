"""Unit tests for the impact_score -> severity band mapping (issue #95).

``_derive_severity`` must return the canonical shared-kernel ``Severity`` value
strings and must include the CRITICAL band at >= 90 (inverting the detectors'
``_IMPACT`` maps, where a Prowler critical = impact_score 90). Before the fix it
capped at "high", so ``finding_critical`` — and the ON-by-default
critical-finding-alert playbook — could never fire.
"""

from __future__ import annotations

import pytest

from components.agents.application.handlers.specialist_persistence_service import (
    _derive_severity,
)
from components.shared_kernel.domain.security import Severity

pytestmark = [pytest.mark.unit]


class TestDeriveSeverity:
    @pytest.mark.parametrize(
        "score,expected",
        [
            (100, Severity.CRITICAL),
            (90, Severity.CRITICAL),  # cloud_posture critical -> now critical, not high
            (89, Severity.HIGH),
            (70, Severity.HIGH),
            (69, Severity.MEDIUM),
            (40, Severity.MEDIUM),
            (39, Severity.LOW),
            (0, Severity.LOW),
        ],
    )
    def test_band_boundaries(self, score, expected):
        assert _derive_severity(score) == expected.value

    def test_returns_canonical_severity_strings(self):
        # Every band the helper can return must be a real Severity value, so the
        # finding tier and the workflow finding_<band> triggers stay aligned.
        valid = {s.value for s in Severity}
        for score in (0, 40, 70, 90):
            assert _derive_severity(score) in valid
