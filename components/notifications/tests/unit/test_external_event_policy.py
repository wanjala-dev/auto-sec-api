"""Classification + dedup identity for the external leg (ADR 0016 D4).

The load-bearing property here is *fail closed*: an unrecognised dispatch must never
leave the tenant. Everything else is about a retry converging instead of double-posting.
"""

from __future__ import annotations

import pytest

from components.notifications.domain.policies.external_event_policy import (
    classify_event,
    derive_dedup_key,
    is_kev,
    is_new_observation,
)
from components.shared_kernel.domain.delivery_events import (
    DRAFT_PR_OPENED,
    FINDING_CRITICAL,
    SCAN_DIGEST,
    SCAN_FAILED,
)

pytestmark = pytest.mark.unit


class TestClassify:
    @pytest.mark.parametrize(
        "kind,expected",
        [
            ("soc.draft_pr_opened", DRAFT_PR_OPENED),
            ("soc.finding_filed", FINDING_CRITICAL),
            ("soc.scan_failed", SCAN_FAILED),
            ("soc.scan_completed", SCAN_DIGEST),
        ],
    )
    def test_maps_known_kinds(self, kind, expected):
        assert classify_event("ai_event", {"kind": kind}) == expected

    @pytest.mark.parametrize(
        "kind",
        ["soc.ai_kill_switch", "soc.sign_off_pending"],
    )
    def test_internal_only_kinds_never_leave_the_tenant(self, kind):
        """A kill-switch flip and a sign-off escalation have a named in-app
        audience; broadcasting them to a team channel is the wrong call."""
        assert classify_event("ai_event", {"kind": kind}) is None

    @pytest.mark.parametrize(
        "metadata",
        [None, {}, {"kind": ""}, {"kind": "something.new"}, {"task_id": "abc"}],
    )
    def test_fails_closed_on_anything_unrecognised(self, metadata):
        """A new internal notification type must be added here consciously before
        it can reach a third-party chat service."""
        assert classify_event("ai_event", metadata) is None

    def test_is_case_insensitive(self):
        assert classify_event("ai_event", {"kind": "SOC.Finding_Filed"}) == FINDING_CRITICAL


class TestDedupKey:
    def test_same_event_yields_the_same_key(self):
        meta = {"finding_id": "f-1", "severity": "critical"}
        a = derive_dedup_key(workspace_id="w1", event_key=FINDING_CRITICAL, metadata=meta)
        b = derive_dedup_key(workspace_id="w1", event_key=FINDING_CRITICAL, metadata=dict(meta))
        assert a == b, "a retry must converge on the same ledger row"

    def test_different_findings_differ(self):
        a = derive_dedup_key(workspace_id="w1", event_key=FINDING_CRITICAL, metadata={"finding_id": "f-1"})
        b = derive_dedup_key(workspace_id="w1", event_key=FINDING_CRITICAL, metadata={"finding_id": "f-2"})
        assert a != b

    def test_different_workspaces_differ(self):
        a = derive_dedup_key(workspace_id="w1", event_key=FINDING_CRITICAL, metadata={"finding_id": "f-1"})
        b = derive_dedup_key(workspace_id="w2", event_key=FINDING_CRITICAL, metadata={"finding_id": "f-1"})
        assert a != b

    def test_different_event_types_on_the_same_subject_differ(self):
        """A scan that fails and a scan that completes are different events even
        though they name the same run."""
        a = derive_dedup_key(workspace_id="w1", event_key=SCAN_FAILED, metadata={"scan_id": "s-1"})
        b = derive_dedup_key(workspace_id="w1", event_key=SCAN_DIGEST, metadata={"scan_id": "s-1"})
        assert a != b

    def test_falls_back_to_a_content_hash(self):
        meta = {"engine": "prowler", "detail": "x"}
        a = derive_dedup_key(workspace_id="w1", event_key=SCAN_FAILED, metadata=meta)
        b = derive_dedup_key(workspace_id="w1", event_key=SCAN_FAILED, metadata={"detail": "x", "engine": "prowler"})
        assert a == b, "key order must not change the identity"
        assert a.endswith(a.split("sha=")[-1])

    def test_key_is_stable_without_a_timestamp(self):
        """Keying on anything time-varying would make every retry look like a new
        event and defeat the ledger entirely."""
        key = derive_dedup_key(workspace_id="w1", event_key=FINDING_CRITICAL, metadata={"finding_id": "f-1"})
        assert "finding_id=f-1" in key


class TestGates:
    @pytest.mark.parametrize(
        "metadata,expected",
        [({"in_kev": True}, True), ({"risk": {"in_kev": True}}, True), ({"in_kev": False}, False), ({}, False)],
    )
    def test_kev_detection(self, metadata, expected):
        assert is_kev(metadata) is expected

    def test_absent_is_new_defaults_to_deliverable(self):
        """A draft PR or a scan digest carries no ``is_new`` — defaulting to False
        would silently suppress them."""
        assert is_new_observation({}) is True

    def test_explicit_re_observation_is_suppressed(self):
        assert is_new_observation({"is_new": False}) is False
