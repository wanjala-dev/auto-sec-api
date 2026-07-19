"""Unit tests for ``build_workspace_snapshot``.

Pure-domain tests — no Django, no DB, no fixtures.
"""

from __future__ import annotations

import pytest

from components.knowledge.domain.services.workspace_snapshot_builder import (
    build_workspace_snapshot,
    render_section_for_embedding,
)
from components.knowledge.domain.value_objects.workspace_snapshot import (
    WorkspaceSnapshot,
    WorkspaceSnapshotInput,
    WorkspaceSnapshotSection,
)


def _minimal(**overrides) -> WorkspaceSnapshotInput:
    defaults = dict(
        workspace_id="ws-1",
        workspace_name="Wanjala Foundation",
    )
    defaults.update(overrides)
    return WorkspaceSnapshotInput(**defaults)


class TestWorkspaceSnapshotSection:
    def test_rejects_blank_body(self):
        with pytest.raises(ValueError):
            WorkspaceSnapshotSection(key="x", title="X", body="   ")

    def test_rejects_missing_key(self):
        with pytest.raises(ValueError):
            WorkspaceSnapshotSection(key="", title="X", body="body")


class TestWorkspaceSnapshotInput:
    def test_rejects_missing_id(self):
        with pytest.raises(ValueError):
            WorkspaceSnapshotInput(workspace_id="", workspace_name="x")

    def test_rejects_missing_name(self):
        with pytest.raises(ValueError):
            WorkspaceSnapshotInput(workspace_id="id", workspace_name="")


class TestBuildWorkspaceSnapshot:
    def test_minimal_input_produces_identity_section_only(self):
        snapshot = build_workspace_snapshot(_minimal())
        assert not snapshot.is_empty()
        assert [s.key for s in snapshot.sections] == ["identity"]
        identity = snapshot.sections[0]
        assert "Wanjala Foundation" in identity.body

    def test_full_input_emits_all_sections(self):
        data = _minimal(
            workspace_type="teamspace",
            sector_name="Nonprofit",
            story="We fund literacy programs across East Africa.",
            vision="A literate future.",
            mission="Place books in every rural school.",
            privacy="public",
            status="active",
            default_currency="KES",
            contact_email="hello@wanjala.org",
            categories=("Education", "Youth"),
            subcategories=("Literacy",),
            tags=("books", "schools"),
            operations=("Book distribution", "Teacher training"),
            contribution_means=("Monetary", "In-kind"),
            member_count=12,
            active_member_count=10,
            follower_count=345,
            team_count=3,
            created_at_iso="2024-01-01T00:00:00",
            updated_at_iso="2026-04-18T12:00:00",
        )
        snapshot = build_workspace_snapshot(data)
        keys = [s.key for s in snapshot.sections]
        assert keys == [
            "identity",
            "mission",
            "classification",
            "operations",
            "team",
            "timeline",
        ]

    def test_sections_with_blank_bodies_are_dropped(self):
        # Only identity should survive — mission/classification/ops/team/timeline bodies all empty.
        snapshot = build_workspace_snapshot(_minimal(workspace_type="teamspace"))
        assert [s.key for s in snapshot.sections] == ["identity"]

    def test_content_hash_is_stable_across_calls(self):
        a = build_workspace_snapshot(_minimal(story="Same story."))
        b = build_workspace_snapshot(_minimal(story="Same story."))
        assert a.content_hash == b.content_hash

    def test_content_hash_changes_when_indexable_text_changes(self):
        a = build_workspace_snapshot(_minimal(story="First story."))
        b = build_workspace_snapshot(_minimal(story="Second story."))
        assert a.content_hash != b.content_hash

    def test_content_hash_unchanged_when_only_non_indexable_changes(self):
        # Team counts are emitted as text, so they DO affect the hash. Verify
        # that a genuinely non-indexable field (the workspace id) does not.
        a = build_workspace_snapshot(_minimal(workspace_id="ws-A", story="S"))
        b = build_workspace_snapshot(_minimal(workspace_id="ws-B", story="S"))
        assert a.content_hash == b.content_hash
        assert a.workspace_id != b.workspace_id

    def test_empty_workspace_can_only_be_flagged_via_is_empty(self):
        # WorkspaceSnapshotInput requires a name, so "truly empty" isn't
        # reachable via the public constructor — the builder will at least
        # emit an identity section from the name. This test documents that.
        snapshot = build_workspace_snapshot(_minimal())
        assert not snapshot.is_empty()


class TestRenderSectionForEmbedding:
    def test_prefixes_workspace_name_and_section_title(self):
        section = WorkspaceSnapshotSection(
            key="mission", title="Mission & story", body="Body text here."
        )
        rendered = render_section_for_embedding("Wanjala Foundation", section)
        assert rendered.startswith("Workspace: Wanjala Foundation")
        assert "Section: Mission & story" in rendered
        assert "Body text here." in rendered


class TestComputeHash:
    def test_hash_is_order_sensitive(self):
        s1 = WorkspaceSnapshotSection(key="a", title="A", body="alpha")
        s2 = WorkspaceSnapshotSection(key="b", title="B", body="beta")
        forward = WorkspaceSnapshot.compute_hash((s1, s2))
        reverse = WorkspaceSnapshot.compute_hash((s2, s1))
        assert forward != reverse

    def test_hash_ignores_title(self):
        a = WorkspaceSnapshotSection(key="x", title="Title One", body="Body.")
        b = WorkspaceSnapshotSection(key="x", title="Title Two", body="Body.")
        assert WorkspaceSnapshot.compute_hash((a,)) == WorkspaceSnapshot.compute_hash((b,))


class TestModuleDocstringDocumentsSnapshotBoundary:
    """Tier 1 #2 — the snapshot builder module docstring must spell out
    what IS and what is NOT embedded.  A future contributor reading
    ``snapshot_builder.py`` should learn the boundary without having
    to chase the roadmap doc.  See
    ``docs/plans/RAG_AUDIT_AND_ROADMAP.md`` Tier 1 #2.
    """

    def _doc(self) -> str:
        from components.knowledge.domain.services import (
            workspace_snapshot_builder,
        )

        return workspace_snapshot_builder.__doc__ or ""

    def test_docstring_frames_snapshot_as_identity_layer(self):
        doc = self._doc()
        # "identity layer not data layer" is the core mental model.
        assert "identity" in doc.lower(), (
            "Module docstring must frame the snapshot as an IDENTITY "
            "layer (not a DATA layer)."
        )

    def test_docstring_lists_what_IS_embedded(self):
        doc = self._doc().lower()
        # The six sections the builder actually produces.
        for section in ("identity", "mission", "classification", "operations", "team", "timeline"):
            assert section in doc, (
                f"Module docstring must list the embedded section "
                f"'{section}' so future contributors know what's in "
                f"the index."
            )

    def test_docstring_lists_what_is_NOT_embedded(self):
        doc = self._doc().lower()
        # The four highest-signal domains the snapshot does NOT cover.
        for domain in ("recipient", "donor", "grant", "transaction"):
            assert domain in doc, (
                f"Module docstring must call out '{domain}' as a "
                f"domain NOT embedded in the snapshot so agents know "
                f"to use ORM tools for those questions."
            )

    def test_docstring_points_at_roadmap(self):
        doc = self._doc()
        assert "RAG_AUDIT_AND_ROADMAP" in doc, (
            "Module docstring should reference docs/plans/"
            "RAG_AUDIT_AND_ROADMAP.md so a contributor can follow up "
            "to Tier 2 (data-aware snapshot)."
        )

    def test_docstring_lists_tier_2_sections(self):
        """Tier 2 #5/#6 added recent_activity + top_entities sections.
        The boundary doc must list them so future contributors don't
        assume the snapshot is still identity-only.
        """
        doc = self._doc().lower()
        for section in ("recent_activity", "top_entities"):
            assert section in doc, (
                f"Module docstring must list the Tier 2 section "
                f"'{section}' so the IS-IN list stays accurate."
            )


class TestRecentActivitySection:
    """Tier 2 #5 — last-30-day rollup section."""

    def test_empty_when_no_activity_fields_set(self):
        snapshot = build_workspace_snapshot(_minimal())
        keys = [s.key for s in snapshot.sections]
        assert "recent_activity" not in keys, (
            "recent_activity must drop when every count is 0 — empty "
            "sections are noise."
        )

    def test_emits_donation_count_only(self):
        data = _minimal(recent_donation_count_30d=7)
        snapshot = build_workspace_snapshot(data)
        activity = next(
            s for s in snapshot.sections if s.key == "recent_activity"
        )
        # Narrative form: "In the last 30 days, <name> received 7 donations."
        assert "in the last 30 days" in activity.body.lower()
        assert "7 donations" in activity.body
        # No total because the total string is empty.
        assert "totaling" not in activity.body

    def test_emits_donation_count_with_total(self):
        data = _minimal(
            recent_donation_count_30d=7,
            recent_donation_total_30d="USD 12,345.00",
        )
        snapshot = build_workspace_snapshot(data)
        activity = next(
            s for s in snapshot.sections if s.key == "recent_activity"
        )
        assert "7 donations" in activity.body
        assert "totaling USD 12,345.00" in activity.body

    def test_emits_each_count_when_set(self):
        data = _minimal(
            recent_donation_count_30d=1,
            recent_new_recipient_count_30d=2,
            recent_new_campaign_count_30d=3,
            recent_new_grant_decision_count_30d=4,
            recent_new_project_count_30d=5,
        )
        snapshot = build_workspace_snapshot(data)
        activity = next(
            s for s in snapshot.sections if s.key == "recent_activity"
        )
        # Narrative form: one sentence per non-zero count, each
        # naming the count and the entity.
        for token in (
            "1 donation",
            "2 new recipients",
            "3 new campaigns",
            "4 new grant decisions",
            "5 new projects",
        ):
            assert token in activity.body, (
                f"Missing narrative phrase: {token!r}"
            )


class TestTopEntitiesSection:
    """Tier 2 #6 — top-N current-state listings."""

    def test_empty_when_no_top_lists_set(self):
        snapshot = build_workspace_snapshot(_minimal())
        keys = [s.key for s in snapshot.sections]
        assert "top_entities" not in keys

    def test_renders_top_donors_as_narrative_sentence(self):
        data = _minimal(
            top_donors=(
                "Alice Mwangi — USD 12,400.00 lifetime",
                "Smith Family — USD 8,200.00 lifetime",
            ),
        )
        snapshot = build_workspace_snapshot(data)
        top = next(s for s in snapshot.sections if s.key == "top_entities")
        # Narrative form: "<name>'s top donors are A and B."
        assert "top donors are" in top.body.lower()
        assert "Alice Mwangi — USD 12,400.00 lifetime" in top.body
        assert "Smith Family — USD 8,200.00 lifetime" in top.body
        # The two donors are joined with "and" in a single sentence,
        # not separate bulleted lines.
        assert (
            "Alice Mwangi — USD 12,400.00 lifetime and "
            "Smith Family — USD 8,200.00 lifetime"
        ) in top.body

    def test_drops_empty_blocks(self):
        data = _minimal(
            top_donors=("Alice Mwangi — USD 1,000 lifetime",),
            top_recipients=(),
            active_campaigns=(),
            open_grants=(),
            active_projects=(),
        )
        snapshot = build_workspace_snapshot(data)
        top = next(s for s in snapshot.sections if s.key == "top_entities")
        assert "top donors are" in top.body.lower()
        # Other entity sentences must not appear when their list is empty.
        for absent in (
            "top recipients are",
            "active campaigns include",
            "open grants include",
            "active projects include",
        ):
            assert absent not in top.body.lower(), (
                f"Empty list must not render its narrative phrase: "
                f"{absent!r}"
            )

    def test_separates_sentences_with_a_space(self):
        """Each populated block is its own sentence so the cross-encoder
        sees independent claims about donors and projects."""
        data = _minimal(
            top_donors=("Alice Mwangi — USD 1,000 lifetime",),
            active_projects=("Food Q3 — in_progress",),
        )
        snapshot = build_workspace_snapshot(data)
        top = next(s for s in snapshot.sections if s.key == "top_entities")
        # Two sentences separated by a space.
        assert "top donors are Alice Mwangi" in top.body
        assert "Active projects include Food Q3" in top.body
        # The body is one continuous paragraph (sentences separated
        # by spaces, not newlines).
        assert "\n" not in top.body.strip()


class TestTier2SectionsRankBetweenTeamAndTimeline:
    """The ``recent_activity`` and ``top_entities`` sections must land
    between ``team`` and ``timeline`` in the embedded order so a query
    like "what's happening here" pulls real activity before creation
    timestamps under cosine top-k.
    """

    def test_section_order(self):
        data = _minimal(
            team_count=2,
            recent_donation_count_30d=1,
            top_donors=("Alice — USD 100 lifetime",),
            created_at_iso="2026-01-01",
        )
        snapshot = build_workspace_snapshot(data)
        keys = [s.key for s in snapshot.sections]
        assert keys.index("team") < keys.index("recent_activity")
        assert keys.index("recent_activity") < keys.index("top_entities")
        assert keys.index("top_entities") < keys.index("timeline")


class TestMembersSection:
    """Tier 3 #14 — workspace members by name + role.

    Closes the "Find <person>" routing gap. Bare ``Find Aisha Otieno``
    queries were routing to donation_agent because top donors were the
    only named identities in the embedding index. The members section
    gives hybrid search a named-member chunk so the planner can prefer
    user_agent for member-shaped queries.
    """

    def test_omitted_when_top_members_empty(self):
        snapshot = build_workspace_snapshot(_minimal())
        keys = [s.key for s in snapshot.sections]
        assert "members" not in keys

    def test_renders_member_names_with_roles_as_narrative_sentence(self):
        data = _minimal(
            top_members=(
                "Aisha Otieno — Programs Coordinator",
                "Daniel Mwangi — Development Lead",
            ),
        )
        snapshot = build_workspace_snapshot(data)
        members = next(s for s in snapshot.sections if s.key == "members")
        # Narrative form: "The active members of <name> are A and B."
        assert "active members of" in members.body.lower()
        assert "Aisha Otieno — Programs Coordinator" in members.body
        assert "Daniel Mwangi — Development Lead" in members.body
        # Single sentence, not bullets — no newlines, no leading "  - ".
        assert "\n" not in members.body.strip()
        assert "  -" not in members.body

    def test_does_not_leak_email_or_phone(self):
        """Email/phone live behind user_agent.get_user_profile; the
        embedding index must not contain PII beyond name + role.
        """
        data = _minimal(
            top_members=("Aisha Otieno — Programs Coordinator",),
        )
        snapshot = build_workspace_snapshot(data)
        members = next(s for s in snapshot.sections if s.key == "members")
        # Adapter is responsible for not passing PII through; the
        # builder must not synthesise it either. Verify by ensuring
        # no @ or phone-shaped token appears in the rendered body.
        assert "@" not in members.body
        assert "+1" not in members.body
        assert "+254" not in members.body

    def test_members_ranks_after_team_and_before_recent_activity(self):
        """Member chunks should rank between team-counts and activity
        rollups so a query like ``Find Aisha Otieno`` retrieves the
        members chunk ahead of recent-donation totals.
        """
        data = _minimal(
            team_count=2,
            top_members=("Aisha Otieno — Programs Coordinator",),
            recent_donation_count_30d=1,
            top_donors=("Henry Wanjala — USD 100 lifetime",),
            created_at_iso="2026-01-01",
        )
        snapshot = build_workspace_snapshot(data)
        keys = [s.key for s in snapshot.sections]
        assert keys.index("team") < keys.index("members")
        assert keys.index("members") < keys.index("recent_activity")
        assert keys.index("members") < keys.index("top_entities")
        assert keys.index("members") < keys.index("timeline")
