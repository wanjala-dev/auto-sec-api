"""Redaction + rendering for messages that leave the tenant (ADR 0016 D6).

This is the single enforcement point for what may cross the boundary into a
third-party chat service, so the tests here are deliberately adversarial: they feed
the builder the kind of metadata a real finding carries — prompts, raw payloads, log
lines, tokens — and assert none of it comes out the other side.
"""

from __future__ import annotations

import pytest

from components.notifications.domain.services.external_message_builder import build_message
from components.shared_kernel.domain.delivery_events import (
    DRAFT_PR_OPENED,
    FINDING_CRITICAL,
    SCAN_DIGEST,
    SCAN_FAILED,
)

pytestmark = pytest.mark.unit


def _rendered(message) -> str:
    """Everything that could reach a channel, as one blob to search."""
    return " ".join([message.title, message.body, message.link, repr(message.fields)])


class TestRedaction:
    def test_drops_everything_not_on_the_allowlist(self):
        message = build_message(
            event_key=FINDING_CRITICAL,
            verb="Public S3 bucket",
            metadata={
                "asset_urn": "arn:aws:s3:::bucket",
                "severity": "critical",
                # None of the following may ever leave the tenant.
                "prompt": "You are a security analyst. The admin password is hunter2",
                "tool_output": "{'rows': [...]}",
                "attributes": {"raw": "sensitive"},
                "log_line": "2026-01-01 ERROR token=xoxb-secret",
                "token": "xoxb-super-secret",
                "raw_payload": {"a": 1},
            },
        )
        blob = _rendered(message)

        for leaked in ("hunter2", "tool_output", "xoxb-super-secret", "xoxb-secret", "raw_payload", "sensitive"):
            assert leaked not in blob, f"{leaked!r} escaped the redaction allowlist"

    def test_keeps_the_notification_grade_facts(self):
        message = build_message(
            event_key=FINDING_CRITICAL,
            verb="Public S3 bucket",
            metadata={"asset_urn": "arn:aws:s3:::bucket", "source": "cloud_posture.prowler", "severity": "critical"},
            link="https://app.example.com/findings/1",
        )
        blob = _rendered(message)

        assert "Public S3 bucket" in blob
        assert "arn:aws:s3:::bucket" in blob
        assert message.link == "https://app.example.com/findings/1"

    def test_keeps_the_vulnerability_identity(self):
        """#247: CVE + package are allowlisted so lookalike titles ("CVE-… in
        openssl" across images) stay distinguishable in a chat channel."""
        message = build_message(
            event_key=FINDING_CRITICAL,
            verb="CVE-2024-1234 in openssl",
            metadata={
                "severity": "critical",
                "vulnerability_id": "CVE-2024-1234",
                "package": "openssl",
            },
        )
        assert message.fields["vulnerability_id"] == "CVE-2024-1234"
        assert message.fields["package"] == "openssl"

    def test_strips_newlines_so_a_log_line_cannot_forge_extra_lines(self):
        """A crafted log line is untrusted input — without this it could inject
        what looks like separate messages into the channel."""
        message = build_message(
            event_key=FINDING_CRITICAL,
            verb="ok",
            metadata={"asset_urn": "arn\n\nFAKE: everything is fine", "severity": "high"},
        )
        assert "\n" not in message.fields["asset_urn"]

    def test_unknown_event_key_yields_no_fields(self):
        message = build_message(event_key="not_a_real_event", verb="hi", metadata={"secret": "x"})
        assert message.fields == {}
        assert "x" not in _rendered(message)


class TestRendering:
    def test_finding_title_carries_severity(self):
        message = build_message(event_key=FINDING_CRITICAL, verb="Public bucket", metadata={"severity": "critical"})
        assert "Critical" in message.title
        assert message.severity == "critical"

    def test_scan_digest_is_counts_not_a_finding_list(self):
        """The batch rule made legible — one message per scan with counts, never
        one message per finding (ADR 0016 D5)."""
        message = build_message(
            event_key=SCAN_DIGEST,
            verb="",
            metadata={"engine": "Prowler", "critical": 3, "high": 12, "medium": 41},
        )
        assert "Prowler" in message.title
        assert "3 critical" in message.body
        assert "12 high" in message.body

    def test_scan_digest_with_no_findings_says_so(self):
        message = build_message(event_key=SCAN_DIGEST, verb="", metadata={"engine": "Trivy"})
        assert "No new findings" in message.body

    def test_draft_pr_names_the_repo(self):
        message = build_message(
            event_key=DRAFT_PR_OPENED,
            verb="fix: tighten bucket policy",
            metadata={"repo": "acme/api", "pr_url": "https://github.com/acme/api/pull/7"},
        )
        assert "Draft PR" in message.title
        assert message.fields["repo"] == "acme/api"

    def test_scan_failed_names_the_engine(self):
        message = build_message(event_key=SCAN_FAILED, verb="", metadata={"engine": "Prowler"})
        assert "Scan failed" in message.title
        assert "Prowler" in message.title

    def test_never_raises_on_malformed_metadata(self):
        """A malformed dispatch must degrade to a plain title, not block delivery
        of a real security event."""
        message = build_message(event_key=FINDING_CRITICAL, verb="", metadata=None)
        assert isinstance(message.title, str)

    def test_title_is_length_capped(self):
        message = build_message(event_key=FINDING_CRITICAL, verb="x" * 5000, metadata={"severity": "high"})
        assert len(message.title) <= 250
