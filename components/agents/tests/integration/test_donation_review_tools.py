"""DB-backed tests for donation_agent manual-review tools (PR-B6).

Wires the agent layer to ``ReviewManualDonationUseCase`` — the same
use case the ``DonationsDashboardPage`` review buttons drive
(``sponsorshipApi.reviewDonation`` posts to
``/sponsorship/donations/<id>/review/``).

Refund is intentionally NOT exposed as an agent tool. The
``IssueDonationRefundUseCase`` is Stripe-webhook-driven and not safe
for an agent to synthesize unilaterally — refunds remain a human-in-
the-loop operation through the admin UI.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from components.agents.infrastructure.adapters.langchain.tools import (
    donation_agent as donation_tools,
)


def _make_agent(workspace_id, user, *, is_staff=False, is_superuser=False):
    """Stub agent with the attrs the tools read.

    Note: ``ReviewManualDonationUseCase`` checks ``is_staff`` /
    ``is_superuser`` on the resolved user — pass these through here
    so the tests can exercise both authorized and unauthorized paths.
    """
    user.is_staff = is_staff
    user.is_superuser = is_superuser
    user.save(update_fields=["is_staff", "is_superuser"])

    agent = MagicMock()
    agent.workspace_id = workspace_id
    agent.user_id = user.id
    agent.config = {
        "default_user_id": str(user.id),
        "default_user_email": user.email,
    }
    return agent


@pytest.fixture
def pending_donation(workspace_factory, user_factory):
    """Workspace + a Donation with review_status=pending_review."""
    from infrastructure.persistence.sponsorship.donations.models import Donation

    user = user_factory()
    workspace = workspace_factory(owner=user)
    donation = Donation(
        workspace_id=workspace.id,
        amount=Decimal("75.00"),
        email="manual@example.com",
        name="Manual Donor",
        review_status=Donation.REVIEW_PENDING,
    )
    donation._skip_ingest = True
    donation.save()
    return {
        "user": user,
        "workspace": workspace,
        "donation": donation,
    }


# ── approve_donation ───────────────────────────────────────────────────


@pytest.mark.django_db
class TestApproveDonation:
    def test_approves_pending_donation(self, pending_donation):
        from infrastructure.persistence.sponsorship.donations.models import Donation

        agent = _make_agent(
            pending_donation["workspace"].id,
            pending_donation["user"],
            is_staff=True,
        )
        result = donation_tools.approve_donation(
            agent, {"donation_id": str(pending_donation["donation"].id)}
        )
        pending_donation["donation"].refresh_from_db()
        assert pending_donation["donation"].review_status == Donation.REVIEW_APPROVED
        assert "approved" in result

    def test_rejects_missing_donation_id(self, pending_donation):
        agent = _make_agent(
            pending_donation["workspace"].id,
            pending_donation["user"],
            is_staff=True,
        )
        result = donation_tools.approve_donation(agent, {})
        assert "donation_id is required" in result

    def test_rejects_unknown_donation(self, pending_donation):
        agent = _make_agent(
            pending_donation["workspace"].id,
            pending_donation["user"],
            is_staff=True,
        )
        result = donation_tools.approve_donation(
            agent, {"donation_id": "00000000-0000-0000-0000-000000000000"}
        )
        # Either the use-case returns an error (we surface it) or a not-found.
        assert "Cannot approve" in result or "Error" in result


# ── reject_donation ────────────────────────────────────────────────────


@pytest.mark.django_db
class TestRejectDonation:
    def test_rejects_pending_donation(self, pending_donation):
        from infrastructure.persistence.sponsorship.donations.models import Donation

        agent = _make_agent(
            pending_donation["workspace"].id,
            pending_donation["user"],
            is_staff=True,
        )
        result = donation_tools.reject_donation(
            agent, {"donation_id": str(pending_donation["donation"].id)}
        )
        pending_donation["donation"].refresh_from_db()
        assert pending_donation["donation"].review_status == Donation.REVIEW_REJECTED
        assert "rejected" in result

    def test_round_trip_approve_then_reject(self, pending_donation):
        """The use case may or may not allow flipping a previously-approved
        donation back to rejected — exercise the round-trip and let the
        use case's response decide.
        """
        from infrastructure.persistence.sponsorship.donations.models import Donation

        agent = _make_agent(
            pending_donation["workspace"].id,
            pending_donation["user"],
            is_staff=True,
        )
        donation_tools.approve_donation(
            agent, {"donation_id": str(pending_donation["donation"].id)}
        )
        result = donation_tools.reject_donation(
            agent, {"donation_id": str(pending_donation["donation"].id)}
        )
        pending_donation["donation"].refresh_from_db()
        # Final state is whatever the use case allowed; assert we got a
        # non-error message (the tool layer surfaced it cleanly).
        assert "Error" not in result or "Cannot" in result


# ── permission boundary ────────────────────────────────────────────────


@pytest.mark.django_db
class TestReviewPermissionBoundary:
    def test_non_staff_non_owner_is_blocked(self, workspace_factory, user_factory):
        """Use case must reject a non-staff, non-admin reviewer.

        We construct a workspace owned by user A, then attempt the
        review as user B (no role on the workspace, not staff). The
        use case's permission check should refuse and the tool surfaces
        the friendly error.
        """
        from infrastructure.persistence.sponsorship.donations.models import Donation

        owner = user_factory()
        outsider = user_factory()
        ws = workspace_factory(owner=owner)
        donation = Donation(
            workspace_id=ws.id,
            amount=Decimal("10.00"),
            email="manual@example.com",
            review_status=Donation.REVIEW_PENDING,
        )
        donation._skip_ingest = True
        donation.save()

        agent = _make_agent(ws.id, outsider, is_staff=False, is_superuser=False)
        result = donation_tools.approve_donation(
            agent, {"donation_id": str(donation.id)}
        )
        # Must NOT have approved.
        donation.refresh_from_db()
        assert donation.review_status == Donation.REVIEW_PENDING
        # And the tool surfaced an error string, not a stack trace.
        assert "Cannot approve" in result or "Error" in result
