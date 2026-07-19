"""Pure builder that turns raw workspace facts into a structured snapshot.

No Django, no ORM, no I/O.  The builder assembles named sections from the
input dataclass, filters out sections whose body is blank, and computes a
content hash over what actually makes it into the snapshot.

Sections are ordered most-important-first so that when a retriever returns
top-k chunks for a short query, the identity / mission material tends to
rank above long activity dumps.

Body shape (2026-06-11): every section's body is **narrative prose**,
not labelled bullets.  The cross-encoder reranker (MS-MARCO MiniLM
L-6 v2) was trained on "passage answers a question" pairs, so
bulleted metadata blocks (``"Categories: Education, Community"``)
scored poorly against natural-language queries (``"What does
Zaylan do?"``).  Switching to prose — ``"Zaylan operates in the
Education and Community categories."`` — lets the cross-encoder
actually rank these chunks.  The 2026-06-11 threshold A/B
documented this gap in ``docs/plans/RAG_EVAL_BASELINE.md``; this
PR is the fix.  Section keys, ordering, and the data model are
unchanged — only the body text shape changed.

What this snapshot contains (and what it does NOT)
--------------------------------------------------

Tier 1 framed the snapshot as a pure IDENTITY layer.  Tier 2 #5/#6
makes it **partially data-aware** — it now embeds rollup counts and
top-N lists for the load-bearing domains, but never per-row detail.
The eight embedded sections:

* ``identity`` — workspace name, type, sector, privacy, status, default
  currency, contact email.
* ``mission`` — narrative ``story``, ``vision``, ``mission`` text fields.
* ``classification`` — category, subcategory, and tag **names** (no IDs,
  no descriptions).
* ``operations`` — operation names + contribution-means names.
* ``team`` — team count, member count, active-member count, follower
  count.  **Counts only — no member names.**
* ``members`` (Tier 3 #14) — active workspace members by name and role,
  top 10.  Closes the "Find <person>" routing gap by giving hybrid
  search a chunk that names members so the planner can prefer
  ``user_agent`` for member-shaped queries.  **Names + roles only —
  email and other PII stay out of the index.**
* ``recent_activity`` (Tier 2 #5) — last-30-day rollup: donation count
  + total, new-recipient count, new-campaign count, new-grant-decision
  count, new-project count.  **Counts and pre-formatted totals only.**
* ``top_entities`` (Tier 2 #6) — current state of the load-bearing
  entities: top 5 donors with lifetime totals, top 5 recipients,
  active campaigns with goal progress, open grants with stage +
  deadline, active projects with status.  Pre-formatted one-line rows
  the builder renders as bullets; structured detail (full donor
  profile, transaction list, grant history) still lives behind the
  specialist agents' ORM tools.
* ``timeline`` — ``created_at`` / ``updated_at`` ISO timestamps.

What this snapshot still does NOT contain:

* Full donation transaction history (only rollup count + total).
* Full recipient profiles (only top-5 names + simple status).
* Transaction-level expense lines.
* Budget category balances.
* Project milestones, task lists.
* Member email, phone, or other PII (Tier 3 #14 indexes name + role
  only; email/phone stay behind ``user_agent.get_user_profile``).
* ``EntityAuditLog`` entries (per-user audit history is owned by
  ``user_agent.list_user_activity``).

Agents asking *"who are our top donors?"* or *"what's our grant
pipeline state?"* can now answer from the snapshot at a one-line-per-
entity level.  Anything deeper (full donation history, grant
documents, transaction breakdowns) still dispatches to the specialist.
See ``docs/plans/RAG_AUDIT_AND_ROADMAP.md`` Tier 2 #5/#6.

Reindex trigger coverage
------------------------

The snapshot is rebuilt on ``Workspace.post_save`` only.  M2M changes to
``workspace_categories``, ``tags``, ``operations``, and
``contribution_means`` do NOT fire that signal — so a renamed category
will live in the embedding until the next ``Workspace.save()`` runs.
Domain-data saves (``Recipient.save``, ``Donation.save``, ``Grant.save``,
``Campaign.save``, etc.) do not trigger reindex either, which is fine
today because none of that data is in the snapshot, but will need
dedicated signal bridges when Tier 2 lands.  See Tier 2 #7 in the
roadmap.
"""

from __future__ import annotations

from typing import Callable

from components.knowledge.domain.value_objects.workspace_snapshot import (
    WorkspaceSnapshot,
    WorkspaceSnapshotInput,
    WorkspaceSnapshotSection,
)


def _clean(value: str) -> str:
    return (value or "").strip()


def _joined(values: tuple[str, ...]) -> str:
    return ", ".join(v for v in (_clean(v) for v in values) if v)


def _join_with_and(values: tuple[str, ...]) -> str:
    """Render a tuple as ``"a, b, and c"`` for narrative prose.

    Empty tuple → empty string.  Single value → just the value.  Two
    values → ``"a and b"``.  Three or more → Oxford comma.
    """
    cleaned = tuple(v for v in (_clean(v) for v in values) if v)
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"
    return ", ".join(cleaned[:-1]) + f", and {cleaned[-1]}"


def _identity_body(data: WorkspaceSnapshotInput) -> str:
    """Narrative prose describing the workspace's identity.

    Cross-encoder rerankers (MS-MARCO MiniLM) were trained on
    "passage answers a question" pairs.  Phrasing the metadata as
    prose ("Zaylan is a nonprofit teamspace") rather than bullets
    ("Type: teamspace / Sector: nonprofit") lets the cross-encoder
    actually rank these chunks against "what does Zaylan do?" type
    queries.  See the 2026-06-11 threshold A/B in
    docs/plans/RAG_EVAL_BASELINE.md.
    """
    name = data.workspace_name
    sentences: list[str] = []

    # First sentence: what is this workspace?  Uses the type word
    # ("teamspace") on its own rather than "<type> workspace" which
    # double-words it.  Sector lives in the same sentence so the
    # cross-encoder sees them adjacent — matches "what kind of
    # workspace is Zaylan?" type queries.
    intro = f"{name} is a {data.workspace_type or 'workspace'}"
    if data.sector_name:
        intro += f" operating in the {data.sector_name} sector"
    sentences.append(intro + ".")

    # Second sentence: status + privacy.  Separate so the cross-
    # encoder can pick up "is Zaylan active?" / "is Zaylan public?"
    # type queries without diluting the first sentence.
    flags: list[str] = []
    if data.privacy:
        flags.append(data.privacy)
    if data.status:
        flags.append(f"currently {data.status}")
    if flags:
        sentences.append(f"It is {' and '.join(flags)}.")

    if data.default_currency:
        sentences.append(
            f"Its default currency is {data.default_currency}."
        )
    if data.contact_email:
        sentences.append(
            f"The primary contact email is {data.contact_email}."
        )
    return " ".join(sentences)


def _mission_body(data: WorkspaceSnapshotInput) -> str:
    """Narrative prose describing mission / story / vision.

    Each present field becomes its own sentence so the cross-encoder
    sees three independent claims about the workspace's purpose
    rather than a labelled triple.
    """
    name = data.workspace_name
    parts: list[str] = []
    story = _clean(data.story)
    if story:
        parts.append(f"{name}'s story: {story}")
    mission = _clean(data.mission)
    if mission:
        parts.append(f"Its mission is: {mission}")
    vision = _clean(data.vision)
    if vision:
        parts.append(f"Its vision is: {vision}")
    return "\n\n".join(parts)


def _classification_body(data: WorkspaceSnapshotInput) -> str:
    """Narrative prose describing categories, subcategories, and tags."""
    name = data.workspace_name
    sentences: list[str] = []
    categories = _join_with_and(data.categories)
    if categories:
        plural = "categories" if len(data.categories) > 1 else "category"
        sentences.append(
            f"{name} operates in the {categories} {plural}."
        )
    subcategories = _join_with_and(data.subcategories)
    if subcategories:
        plural = (
            "subcategories"
            if len(data.subcategories) > 1
            else "subcategory"
        )
        sentences.append(f"Its {plural} include {subcategories}.")
    tags = _join_with_and(data.tags)
    if tags:
        sentences.append(f"Tags applied to the workspace: {tags}.")
    return " ".join(sentences)


def _operations_body(data: WorkspaceSnapshotInput) -> str:
    """Narrative prose describing how the workspace operates."""
    name = data.workspace_name
    sentences: list[str] = []
    operations = _join_with_and(data.operations)
    if operations:
        sentences.append(
            f"{name}'s operational areas are {operations}."
        )
    contribution_means = _join_with_and(data.contribution_means)
    if contribution_means:
        sentences.append(
            f"It accepts contributions in the form of "
            f"{contribution_means}."
        )
    return " ".join(sentences)


def _team_body(data: WorkspaceSnapshotInput) -> str:
    """Narrative prose describing team size + follower count."""
    if not any(
        [
            data.member_count,
            data.active_member_count,
            data.follower_count,
            data.team_count,
        ]
    ):
        return ""
    name = data.workspace_name
    sentences: list[str] = []
    if data.team_count:
        team_word = "teams" if data.team_count != 1 else "team"
        sentences.append(
            f"{name} has {data.team_count} {team_word}."
        )
    if data.member_count or data.active_member_count:
        member_parts: list[str] = []
        if data.member_count:
            member_word = (
                "members" if data.member_count != 1 else "member"
            )
            member_parts.append(
                f"{data.member_count} total {member_word}"
            )
        if data.active_member_count:
            member_parts.append(
                f"{data.active_member_count} active"
            )
        sentences.append(f"It has {', '.join(member_parts)}.")
    if data.follower_count:
        follower_word = (
            "followers" if data.follower_count != 1 else "follower"
        )
        sentences.append(
            f"The workspace has {data.follower_count} "
            f"{follower_word}."
        )
    return " ".join(sentences)


def _members_body(data: WorkspaceSnapshotInput) -> str:
    """Tier 3 #14 — active workspace members by name (narrative).

    Closes the "Find <person>" routing gap.  Without this section, the
    snapshot only indexed top donors / top recipients, so any bare
    person-find query was pulled toward donation_agent or
    sponsorship_agent.  Indexing member names lets hybrid search
    surface a `members` chunk for member-shaped queries and lets the
    planner prefer user_agent.

    Rows are pre-formatted by the adapter as "First Last — Role"; the
    builder renders them as a sentence.  Email is intentionally NOT
    included — PII stays out of the embedding index.

    Narrative form (2026-06-11): "The active members of <name> are
    A, B, and C." reads as an answer to "Who is on the team?" and
    "Who are the workspace members?" — both questions the cross-
    encoder can match against.  The previous bulleted form
    ("Active members:\n  - A\n  - B") didn't match either query
    template under MS-MARCO scoring.
    """
    if not data.top_members:
        return ""
    name = data.workspace_name
    members_text = _join_with_and(tuple(data.top_members))
    return (
        f"The active members of {name} are {members_text}."
    )


def _recent_activity_body(data: WorkspaceSnapshotInput) -> str:
    """Tier 2 #5 — last-30-day activity rollup (narrative).

    Counts only; specialist agents own per-row detail.  Narrative
    form so the cross-encoder can match queries like "what's
    happening lately?" or "how much have we raised recently?" — the
    previous "Donations (last 30 days): 11" labelled form didn't
    score well against either.
    """
    name = data.workspace_name
    sentences: list[str] = []
    if data.recent_donation_count_30d:
        donation_word = (
            "donations"
            if data.recent_donation_count_30d != 1
            else "donation"
        )
        sentence = (
            f"In the last 30 days, {name} received "
            f"{data.recent_donation_count_30d} {donation_word}"
        )
        if data.recent_donation_total_30d:
            sentence += f" totaling {data.recent_donation_total_30d}"
        sentences.append(sentence + ".")
    if data.recent_new_recipient_count_30d:
        word = (
            "recipients"
            if data.recent_new_recipient_count_30d != 1
            else "recipient"
        )
        sentences.append(
            f"It onboarded {data.recent_new_recipient_count_30d} "
            f"new {word} in the last 30 days."
        )
    if data.recent_new_campaign_count_30d:
        word = (
            "campaigns"
            if data.recent_new_campaign_count_30d != 1
            else "campaign"
        )
        sentences.append(
            f"It launched {data.recent_new_campaign_count_30d} "
            f"new {word} in the last 30 days."
        )
    if data.recent_new_grant_decision_count_30d:
        word = (
            "decisions"
            if data.recent_new_grant_decision_count_30d != 1
            else "decision"
        )
        sentences.append(
            f"It logged "
            f"{data.recent_new_grant_decision_count_30d} new grant "
            f"{word} in the last 30 days."
        )
    if data.recent_new_project_count_30d:
        word = (
            "projects"
            if data.recent_new_project_count_30d != 1
            else "project"
        )
        sentences.append(
            f"It started {data.recent_new_project_count_30d} new "
            f"{word} in the last 30 days."
        )
    return " ".join(sentences)


def _top_entities_body(data: WorkspaceSnapshotInput) -> str:
    """Tier 2 #6 — current state of the load-bearing entities (narrative).

    Each populated entity list becomes its own sentence so the
    cross-encoder sees independent claims about donors, recipients,
    campaigns, grants, and projects.  Empty lists drop their
    sentence so the body stays signal-only.  The rows themselves
    come pre-formatted from the adapter — the builder never touches
    currency, dates, or status names.
    """
    name = data.workspace_name
    sentences: list[str] = []
    if data.top_donors:
        donors = _join_with_and(tuple(data.top_donors))
        sentences.append(f"{name}'s top donors are {donors}.")
    if data.top_recipients:
        recipients = _join_with_and(tuple(data.top_recipients))
        sentences.append(f"Its top recipients are {recipients}.")
    if data.active_campaigns:
        campaigns = _join_with_and(tuple(data.active_campaigns))
        sentences.append(f"Active campaigns include {campaigns}.")
    if data.open_grants:
        grants = _join_with_and(tuple(data.open_grants))
        sentences.append(f"Open grants include {grants}.")
    if data.active_projects:
        projects = _join_with_and(tuple(data.active_projects))
        sentences.append(f"Active projects include {projects}.")
    return " ".join(sentences)


def _timeline_body(data: WorkspaceSnapshotInput) -> str:
    """Narrative prose describing creation + last update timestamps."""
    name = data.workspace_name
    sentences: list[str] = []
    if data.created_at_iso:
        sentences.append(
            f"{name} was created on {data.created_at_iso}."
        )
    if data.updated_at_iso:
        sentences.append(
            f"It was last updated on {data.updated_at_iso}."
        )
    return " ".join(sentences)


_SectionBodyFn = Callable[[WorkspaceSnapshotInput], str]

# Section order matters under cosine top-k: identity/mission rank
# highest, then activity, then admin metadata.  Tier 2 #5/#6 inserts
# `recent_activity` and `top_entities` between `team` and `timeline`
# so a query like "what's happening here" pulls real activity before
# creation timestamps.
_SECTION_DEFS: tuple[tuple[str, str, _SectionBodyFn], ...] = (
    ("identity", "Workspace identity", _identity_body),
    ("mission", "Mission & story", _mission_body),
    ("classification", "Classification & tags", _classification_body),
    ("operations", "Operations & contribution", _operations_body),
    ("team", "Team & followers", _team_body),
    # Members sit after the team-counts block and before activity rollups
    # so a query like "Find Aisha Otieno" pulls the named-members chunk
    # ahead of recent-activity counts under cosine similarity.
    ("members", "Active workspace members", _members_body),
    ("recent_activity", "Recent activity (30 days)", _recent_activity_body),
    ("top_entities", "Top entities & current pipeline", _top_entities_body),
    ("timeline", "Timeline", _timeline_body),
)


def build_workspace_snapshot(data: WorkspaceSnapshotInput) -> WorkspaceSnapshot:
    """Assemble a ``WorkspaceSnapshot`` from raw workspace facts.

    Sections with an empty body are dropped.  The resulting snapshot is
    empty (``snapshot.is_empty()``) only if the workspace has *nothing*
    indexable — which means the caller should treat reindex as a no-op.
    """
    sections: list[WorkspaceSnapshotSection] = []
    for key, title, body_fn in _SECTION_DEFS:
        body = body_fn(data).strip()
        if not body:
            continue
        sections.append(WorkspaceSnapshotSection(key=key, title=title, body=body))

    section_tuple = tuple(sections)
    content_hash = WorkspaceSnapshot.compute_hash(section_tuple)
    return WorkspaceSnapshot(
        workspace_id=data.workspace_id,
        sections=section_tuple,
        content_hash=content_hash,
    )


def render_section_for_embedding(
    workspace_name: str, section: WorkspaceSnapshotSection
) -> str:
    """Text form used as the embedded chunk body.

    Prefixes the chunk with the workspace name and section title so the
    embedding captures context (semantic search on "tldr <workspace>"
    matches against chunks that name the workspace explicitly).
    """
    return f"Workspace: {workspace_name}\nSection: {section.title}\n\n{section.body}"
