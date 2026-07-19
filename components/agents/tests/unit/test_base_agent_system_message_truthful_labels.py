"""Tier 1 #1 — BaseAgent system message must truthfully describe what
``retrieve_workspace_context`` actually returns.

Pre-Tier-1 the system prompt told every agent to *"ALWAYS call
`retrieve_workspace_context` FIRST for any question about this
workspace"*, which over-promised the surface: the workspace snapshot
is an IDENTITY layer (name, mission, sector, categories, counts), not
a DATA layer.  Agents called the tool for donor / recipient / grant
questions, got back the workspace mission text, then called their
domain tools anyway — a token + latency tax with diminishing returns.

These tests pin the post-Tier-1 wording so a future edit can't
silently re-introduce the over-promise.  See
``docs/plans/RAG_AUDIT_AND_ROADMAP.md`` Tier 1 #1.
"""

from __future__ import annotations

from unittest.mock import patch

from components.agents.infrastructure.adapters.langchain.base import BaseAgent


def _build_system_message():
    """Construct a system message via a minimal stub agent.

    Bypasses ``__init__`` (which expects an LLM provider + memory
    service) by instantiating a lightweight subclass that only
    populates the attributes ``_build_system_message`` reads.
    """

    class _Stub(BaseAgent):  # noqa: D401 — test stub
        profile = {
            "name": "Stub Agent",
            "summary": "A stub for system-message tests.",
            "capabilities": ["one", "two"],
        }

        def __init__(self):
            # Skip BaseAgent.__init__ — we only need the message builder.
            self.workspace_id = "ws-1"

        # Stub the customisation hook so it returns nothing.
        def _get_prompt_customization_vars(self):
            return {}

        def _get_agent_profile(self):
            return self.profile

    return _Stub()._build_system_message()


class TestSystemMessageRemovesOverPromise:
    def test_no_always_call_retrieve_first_instruction(self):
        msg = _build_system_message()
        # The exact pre-Tier-1 phrasing that over-promised the snapshot.
        assert "ALWAYS call `retrieve_workspace_context` FIRST" not in msg, (
            "Pre-Tier-1 system message told every agent to ALWAYS call "
            "retrieve_workspace_context FIRST for any question about "
            "this workspace.  That cost a vector round-trip per "
            "invocation for a layer that can't answer "
            "donor/recipient/grant/transaction questions.  "
            "See docs/plans/RAG_AUDIT_AND_ROADMAP.md Tier 1 #1."
        )

    def test_message_describes_what_snapshot_actually_indexes(self):
        msg = _build_system_message()
        # Truthful wording must name the categories of content the
        # snapshot actually embeds: identity / mission / sector /
        # categories / classification / operations / counts.  The exact
        # word list is flexible; the test asserts at least one
        # identity-side token AND one classification-side token AND
        # one team-side token are present so the agent knows what RAG
        # is good for.
        lowered = msg.lower()
        identity_tokens = ("identity", "mission", "story", "sector")
        classification_tokens = ("categories", "tags", "operations", "classification")
        team_tokens = ("team", "follower", "members", "counts")
        assert any(t in lowered for t in identity_tokens), (
            "System message must name what the snapshot indexes "
            "(identity/mission/story/sector)."
        )
        assert any(t in lowered for t in classification_tokens), (
            "System message must name the classification dimensions "
            "(categories/tags/operations) the snapshot indexes."
        )
        assert any(t in lowered for t in team_tokens), (
            "System message must mention the team/counts dimension."
        )

    def test_message_names_data_categories_that_are_NOT_in_snapshot(self):
        msg = _build_system_message()
        # The system message should warn agents what's NOT in the
        # snapshot so they don't waste a vector round-trip on those
        # shapes.  Recipients / donors / transactions / grants are the
        # four load-bearing domains today.
        lowered = msg.lower()
        domain_words = ("recipient", "donor", "transaction", "grant")
        present = [w for w in domain_words if w in lowered]
        assert len(present) >= 2, (
            "System message must explicitly name at least two of "
            "{recipients, donors, transactions, grants} as data NOT "
            "in the snapshot so agents call their domain tools "
            "directly for those questions.  Found only: "
            f"{present}."
        )

    def test_message_points_at_the_roadmap_doc(self):
        msg = _build_system_message()
        assert "RAG_AUDIT_AND_ROADMAP" in msg, (
            "System message should reference the roadmap doc so a "
            "future contributor reading the prompt has a path to the "
            "full plan.  See docs/plans/RAG_AUDIT_AND_ROADMAP.md."
        )
