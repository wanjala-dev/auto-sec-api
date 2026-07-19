"""Canonical domain enums for the content bounded context.

Single source of truth for status / kind / cadence values used by Newsletter,
WritingDraft, and WritingTemplate. Domain-layer code MUST import from here,
never from ORM models.
"""

from __future__ import annotations


class NewsletterStatus:
    """Lifecycle states for a Newsletter row.

    Important: AI cadence-driven generation creates rows at ``AI_DRAFTED``.
    The ONLY path to ``SENT`` is a human-triggered SendNewsletterUseCase.
    No backend code path may flip a Newsletter to ``SENT`` without explicit
    human action.
    """

    DRAFT = "draft"  # human-authored, not yet sent
    AI_DRAFTED = "ai_drafted"  # cadence task produced it, waiting for review
    SCHEDULED = "scheduled"  # human approved + send-at time set
    SENDING = "sending"  # batch task claimed the row + dispatch in flight
    SENT = "sent"  # dispatched
    SEND_FAILED = "send_failed"  # batch task tried + the use case raised
    ARCHIVED = "archived"
    _ALL = {DRAFT, AI_DRAFTED, SCHEDULED, SENDING, SENT, SEND_FAILED, ARCHIVED}

    @classmethod
    def validate(cls, value: str) -> str:
        if value not in cls._ALL:
            raise ValueError(f"Invalid newsletter status: {value!r}")
        return value


class NewsletterCadence:
    """Per-workspace newsletter cadence stored in WorkspacePreference."""

    NONE = "none"
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"
    _ALL = {NONE, WEEKLY, BIWEEKLY, MONTHLY}

    @classmethod
    def validate(cls, value: str) -> str:
        if value not in cls._ALL:
            raise ValueError(f"Invalid newsletter cadence: {value!r}")
        return value


class WritingDraftKind:
    """Kind discriminator for ad-hoc writing drafts.

    The ``BLOG`` kind was added 2026-06-11 so blog posts compose / list
    through the unified WritingDraft surface instead of the legacy
    ``components/content`` News model. New blogs are WritingDraft rows
    with ``kind='blog'``; the legacy News table stays in place for one
    release as a read-only view, then drops once the data migration
    folds existing News rows into WritingDraft.
    """

    LETTER = "letter"
    UPDATE = "update"
    SUMMARY = "summary"
    MEMO = "memo"
    BLOG = "blog"
    # Project proposal (task #19 slice 3) — a funder/partner-facing pitch
    # for a specific piece of work. First-class kind so the compose flow
    # offers it directly ("when users are trying to create project
    # proposal" — Henry) and the proposal design templates attach to it.
    PROPOSAL = "proposal"
    # Social media post (task #9). A short, hook-first post drafted through
    # the SAME grounded pipeline as every other kind (retrieval + tone +
    # faithfulness gate) — unlike the agents chat tool, which drafts from a
    # bare prompt. Nothing auto-posts: the user copies the approved text to
    # LinkedIn/Instagram/Facebook themselves.
    SOCIAL = "social"
    # Workspace mission / about-us copy. Free-form (not entity-scoped) —
    # one organization-level statement the team iterates on. The Writing
    # surface treats it like any other draft so the AI flow that drafts
    # a mission can persist + return an edit URL through the same path.
    MISSION = "mission"
    # Entity-scoped draft kinds (added 2026-06-11). Each one is a draft
    # that targets a specific workspace entity — a recipient, a project,
    # an event, or a campaign. The compose flow passes the entity ID
    # alongside the kind so the editor can pre-load context (recipient
    # name, project status, event date) and the published draft can be
    # surfaced in the entity's own activity feed.
    RECIPIENT_UPDATE = "recipient_update"
    PROJECT_UPDATE = "project_update"
    EVENT_UPDATE = "event_update"
    CAMPAIGN_UPDATE = "campaign_update"
    _ALL = {
        LETTER,
        UPDATE,
        SUMMARY,
        MEMO,
        BLOG,
        PROPOSAL,
        SOCIAL,
        MISSION,
        RECIPIENT_UPDATE,
        PROJECT_UPDATE,
        EVENT_UPDATE,
        CAMPAIGN_UPDATE,
    }

    @classmethod
    def validate(cls, value: str) -> str:
        if value not in cls._ALL:
            raise ValueError(f"Invalid writing draft kind: {value!r}")
        return value


class WritingDraftStatus:
    """Lifecycle states for a WritingDraft."""

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"
    _ALL = {DRAFT, PUBLISHED, ARCHIVED}

    @classmethod
    def validate(cls, value: str) -> str:
        if value not in cls._ALL:
            raise ValueError(f"Invalid writing draft status: {value!r}")
        return value


class WritingTemplateKind:
    """Kind discriminator for WritingTemplates — spans all writing kinds
    plus newsletter and blog so a single template store covers every
    composable artifact in the Writing surface."""

    LETTER = "letter"
    UPDATE = "update"
    SUMMARY = "summary"
    MEMO = "memo"
    NEWSLETTER = "newsletter"
    BLOG = "blog"
    PROPOSAL = "proposal"
    SOCIAL = "social"
    _ALL = {LETTER, UPDATE, SUMMARY, MEMO, NEWSLETTER, BLOG, PROPOSAL, SOCIAL}

    @classmethod
    def validate(cls, value: str) -> str:
        if value not in cls._ALL:
            raise ValueError(f"Invalid writing template kind: {value!r}")
        return value


class WritingArtifactKind:
    """Kind tag used by the WritingArtifactsPort when surfacing
    cross-context artifact lists (e.g., to shared_platform's unified
    documents feed)."""

    NEWSLETTER = "newsletter"
    DRAFT = "draft"
    BLOG = "blog"
    _ALL = {NEWSLETTER, DRAFT, BLOG}


class SubscriberSource:
    """How a Subscriber row was created. Lets us distinguish admin imports
    from self-subscribed signups (which may need double-opt-in) from
    directory-driven adds (already-known team members)."""

    ADMIN_ADDED = "admin_added"
    SELF_SUBSCRIBED = "self_subscribed"
    IMPORTED = "imported"
    DIRECTORY_PICKED = "directory_picked"
    _ALL = {ADMIN_ADDED, SELF_SUBSCRIBED, IMPORTED, DIRECTORY_PICKED}

    @classmethod
    def validate(cls, value: str) -> str:
        if value not in cls._ALL:
            raise ValueError(f"Invalid subscriber source: {value!r}")
        return value


class SuppressedAddressReason:
    """Why an email address sits on the suppression list. Hard bounces and
    complaints come from SES SNS notifications; manual is an operator-set
    block; admin_removed is when an admin removes a subscriber from the
    workspace UI (soft delete preserves the audit trail)."""

    HARD_BOUNCE = "hard_bounce"
    COMPLAINT = "complaint"
    MANUAL = "manual"
    ADMIN_REMOVED = "admin_removed"
    _ALL = {HARD_BOUNCE, COMPLAINT, MANUAL, ADMIN_REMOVED}

    @classmethod
    def validate(cls, value: str) -> str:
        if value not in cls._ALL:
            raise ValueError(f"Invalid suppression reason: {value!r}")
        return value
