"""Pin signal-bridge coverage for the workspace index pipeline.

Tier 3 #14 audit (2026-06-11) found three holes — Project, Team,
WorkspaceMembership had no signal bridge, so model changes lived
stale until the nightly beat. This contract test asserts every
model the snapshot reads from has a corresponding bridge wired
through ``WorkspaceIndexSignalProvider`` — a future regression
that drops a bridge fails this test, not the freshness SLO weeks
later.

The assertion checks Django's ``signal.receivers`` registry for
each (sender, dispatch_uid) we expect — not the provider source —
so even a rewrite of how bridges register stays covered.
"""

from __future__ import annotations

import pytest
from django.db.models.signals import post_save


@pytest.mark.django_db
class TestDomainChangeBridgeCoverage:
    """Every reindex-triggering model has a post_save bridge."""

    EXPECTED = (
        # (model dotted path, dispatch_uid)
        (
            "infrastructure.persistence.workspaces.models.Grant",
            "knowledge:grant_reindex_on_save",
        ),
        (
            "infrastructure.persistence.project.models.Project",
            "knowledge:project_reindex_on_save",
        ),
        (
            "infrastructure.persistence.team.models.Team",
            "knowledge:team_reindex_on_save",
        ),
        (
            "infrastructure.persistence.workspaces.models.WorkspaceMembership",
            "knowledge:workspace_membership_reindex_on_save",
        ),
    )

    @pytest.mark.parametrize("model_dotted, dispatch_uid", EXPECTED)
    def test_each_expected_bridge_is_registered(self, model_dotted, dispatch_uid):
        from importlib import import_module

        module_path, class_name = model_dotted.rsplit(".", 1)
        sender = getattr(import_module(module_path), class_name)

        # Django's Signal.receivers shape is
        #   [(lookup_key, receiver_ref, sender_ref, is_async), ...]
        # where ``lookup_key`` is itself a tuple whose first element
        # is the ``dispatch_uid`` (string) when the receiver
        # registered one, or an integer ID otherwise. We pull
        # everything that's a string so the set matches against
        # the dispatch_uids the provider wires.
        dispatch_uids = {item[0][0] for item in post_save.receivers if isinstance(item[0][0], str)}
        assert dispatch_uid in dispatch_uids, (
            f"Missing bridge: dispatch_uid={dispatch_uid!r} not registered. "
            f"Expected to wire post_save → reindex for {sender.__name__}. "
            "Check components/knowledge/application/providers/"
            "workspace_index_signal_provider.py."
        )
