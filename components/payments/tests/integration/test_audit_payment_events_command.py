"""Integration coverage for the audit_payment_events management command.

Verifies:
- Lists PaymentEvent rows stuck in PROCESSING longer than the threshold.
- Respects the --provider filter.
- --reset releases stale PROCESSING claims back to RECEIVED (does NOT
  touch FAILED rows even when --include-failed is set).
- The 15-minute default threshold mirrors the stale-claim recovery
  window from payment_event_state.py.
"""

from __future__ import annotations

from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from infrastructure.persistence.workspaces.payments.models import PaymentEvent


pytestmark = [pytest.mark.django_db]


def _stuck_event(
    *, provider="stripe", status=PaymentEvent.STATUS_PROCESSING, age_minutes=60
):
    """Create a PaymentEvent and backdate its created_at into the stuck window."""
    event = PaymentEvent.objects.create(
        provider=provider,
        event_id=f"evt_{age_minutes}_{status}",
        external_id=f"ext_{age_minutes}_{status}",
        event_type="invoice.payment_succeeded",
        status=status,
    )
    PaymentEvent.objects.filter(id=event.id).update(
        created_at=timezone.now() - timedelta(minutes=age_minutes),
        processing_at=timezone.now() - timedelta(minutes=age_minutes),
    )
    event.refresh_from_db()
    return event


class TestAuditPaymentEventsCommand:
    def test_reports_no_stuck_events_when_ledger_clean(self):
        out = StringIO()
        call_command("audit_payment_events", stdout=out)
        assert "No stuck PaymentEvents" in out.getvalue()

    def test_lists_stuck_processing_events(self):
        stuck = _stuck_event(age_minutes=60)
        out = StringIO()
        call_command("audit_payment_events", stdout=out)
        text = out.getvalue()
        assert "Found 1 stuck PaymentEvent" in text
        assert str(stuck.id) in text
        assert "status=processing" in text

    def test_recent_events_are_not_flagged(self):
        _stuck_event(age_minutes=5)
        out = StringIO()
        call_command("audit_payment_events", stdout=out)
        # The 15-minute default threshold means a 5-minute-old event is
        # still in the "healthy worker just started processing" window.
        assert "No stuck PaymentEvents" in out.getvalue()

    def test_failed_events_only_listed_when_flag_passed(self):
        _stuck_event(status=PaymentEvent.STATUS_FAILED, age_minutes=60)
        out_default = StringIO()
        call_command("audit_payment_events", stdout=out_default)
        assert "No stuck PaymentEvents" in out_default.getvalue()

        out_with_failed = StringIO()
        call_command(
            "audit_payment_events", "--include-failed", stdout=out_with_failed
        )
        assert "Found 1 stuck PaymentEvent" in out_with_failed.getvalue()
        assert "status=failed" in out_with_failed.getvalue()

    def test_provider_filter(self):
        _stuck_event(provider="stripe", age_minutes=60)
        _stuck_event(provider="braintree", age_minutes=60)
        out = StringIO()
        call_command("audit_payment_events", "--provider", "stripe", stdout=out)
        text = out.getvalue()
        assert "Found 1 stuck PaymentEvent" in text
        assert "provider=stripe" in text
        assert "provider=braintree" not in text

    def test_reset_releases_processing_claims_to_received(self):
        stuck = _stuck_event(age_minutes=60)
        out = StringIO()
        call_command("audit_payment_events", "--reset", stdout=out)
        text = out.getvalue()
        assert "Released 1 PROCESSING claim" in text

        stuck.refresh_from_db()
        assert stuck.status == PaymentEvent.STATUS_RECEIVED
        assert stuck.processing_at is None
        assert "audit_payment_events --reset" in stuck.status_message

    def test_reset_does_not_touch_failed_rows(self):
        failed = _stuck_event(status=PaymentEvent.STATUS_FAILED, age_minutes=60)
        out = StringIO()
        call_command(
            "audit_payment_events", "--include-failed", "--reset", stdout=out
        )
        text = out.getvalue()
        # FAILED rows are reported but not auto-released — ops must
        # investigate them explicitly.
        assert "Found 1 stuck PaymentEvent" in text
        assert "No PROCESSING rows to reset" in text

        failed.refresh_from_db()
        assert failed.status == PaymentEvent.STATUS_FAILED
