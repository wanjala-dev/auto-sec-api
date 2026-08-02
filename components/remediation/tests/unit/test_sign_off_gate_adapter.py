"""The sign-off gate adapter fails closed on ANY sign-off failure.

A security gate must never crash *open*. The adapter delegates to
``require_approved``; whatever that raises — an approved-state failure
(``NotApprovedError``), an unregistered artifact (``UnregisteredArtifactError``),
or an unexpected lookup error a future registered adapter surfaces
(``ObjectDoesNotExist`` / a DB error) — must deterministically resolve to
``is_approved == False``, not propagate. And a genuinely-approved artifact must
return ``True``.
"""

from __future__ import annotations

import pytest

from components.remediation.infrastructure.adapters import sign_off_gate_adapter as mod
from components.remediation.infrastructure.adapters.sign_off_gate_adapter import SignOffGateAdapter
from components.sign_off.domain.errors import NotApprovedError, UnregisteredArtifactError
from components.sign_off.domain.value_objects.review_state import ReviewState

pytestmark = pytest.mark.unit


def _adapter_with(monkeypatch, require_approved_impl) -> SignOffGateAdapter:
    # Swap the module-level require_approved the adapter calls; monkeypatch
    # restores it after each test so nothing leaks.
    monkeypatch.setattr(mod, "require_approved", require_approved_impl)
    return SignOffGateAdapter()


class TestFailClosed:
    def test_approved_returns_true(self, monkeypatch):
        adapter = _adapter_with(monkeypatch, lambda at, aid: None)  # no-raise = approved
        assert adapter.is_approved(artifact_type="remediation", artifact_id="s1") is True

    def test_not_approved_error_returns_false(self, monkeypatch):
        def raises(at, aid):
            raise NotApprovedError(at, aid, ReviewState.PENDING)

        adapter = _adapter_with(monkeypatch, raises)
        assert adapter.is_approved(artifact_type="remediation", artifact_id="s1") is False

    def test_unregistered_artifact_returns_false(self, monkeypatch):
        def raises(at, aid):
            raise UnregisteredArtifactError(at)

        adapter = _adapter_with(monkeypatch, raises)
        assert adapter.is_approved(artifact_type="remediation", artifact_id="s1") is False

    def test_unexpected_error_fails_closed_not_crashes(self, monkeypatch):
        # A future registered adapter's get_state raises something OUTSIDE the
        # SignOffError taxonomy (e.g. DoesNotExist / DB error). The gate must deny,
        # not propagate the crash.
        def raises(at, aid):
            raise RuntimeError("sign-off backend exploded")

        adapter = _adapter_with(monkeypatch, raises)
        assert adapter.is_approved(artifact_type="remediation", artifact_id="s1") is False
