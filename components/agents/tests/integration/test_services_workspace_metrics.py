import pytest
from datetime import timedelta

from components.agents.infrastructure.gateways import workspace_metrics_gateway as workspace_metrics
from infrastructure.persistence.sponsorship.donations.models import Donation


def test_detect_window_variations():
    delta, label = workspace_metrics.detect_window("Show me stats for this week")
    assert delta == timedelta(days=7)
    assert label == "this week"

    default_delta, default_label = workspace_metrics.detect_window("anything else")
    assert default_label == "last 30 days"
    assert default_delta.days == 30


@pytest.mark.django_db
def test_top_donors_returns_sorted(workspace_factory):
    workspace = workspace_factory()
    Donation.objects.create(workspace=workspace, amount=10, email="a@example.com", name="Alpha")
    Donation.objects.create(workspace=workspace, amount=50, email="b@example.com", name="Beta")
    Donation.objects.create(workspace=workspace, amount=25, email="c@example.com", name="Gamma")

    donors = workspace_metrics.top_donors(workspace.id, limit=2)

    assert donors[0]["label"] == "Beta"
    assert donors[0]["total"] == 50.0
    assert len(donors) == 2
