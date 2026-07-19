"""Persistence models for the content bounded context — newsletters, writing
drafts, writing templates, and (relocated) newsletter subscribers.

These models supersede the legacy ``infrastructure.persistence.landing``
``Newsletter`` and ``Subscriber`` models. The legacy tables stay in place
as read-only fallback for one release; data is copied by the migration
``0002_copy_newsletters_from_landing.py``.

Domain layer (``components.content.domain``) holds canonical enum values
and entity dataclasses. These ORM models are persistence-only — choices
are mirrored from ``components.content.domain.enums`` to keep Django
admin / forms aligned with the source of truth.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from components.content.domain.enums import (
    NewsletterStatus,
    SubscriberSource,
    SuppressedAddressReason,
    WritingDraftKind,
    WritingDraftStatus,
    WritingTemplateKind,
)


class NotDeletedManager(models.Manager):
    """Default manager for bin-aware Communications artifacts (task #29 —
    Henry: "if we ever deleted a draft of anything - it should just go in
    recycle bin"). Filtering at the DEFAULT manager means every read path
    — repositories, sharing resolvers, RAG handlers, scheduled dispatch —
    treats a trashed artifact as gone without auditing each call site;
    the recycle-bin adapter restores via ``all_objects``."""

    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


# ───────────────────────────── Subscriber ─────────────────────────────


class Subscriber(models.Model):
    """Workspace-scoped newsletter subscriber.

    Moved from ``infrastructure.persistence.landing.Subscriber``. As of
    migration ``0004_rescope_subscriber_email_to_workspace`` the email
    column is unique-per-workspace rather than globally unique — two
    different workspaces can independently maintain the same email on
    their mailing lists without one workspace "claiming" the other's.
    A workspace-NULL row (no current workspace) keeps the unique
    constraint on ``email`` alone via a partial unique constraint.

    Consent + lifecycle columns (added 2026-06-11 in migration
    ``0006_subscriber_consent_and_suppression``):

    - ``is_active`` — False once the subscriber unsubscribes or an admin
      removes them. Rows are NEVER hard-deleted; the row stays for audit
      + to keep their ``unsubscribe_token`` valid (so a subsequent
      click on an old email still resolves the same row).
    - ``unsubscribed_at`` — timestamp of when they were marked inactive.
    - ``unsubscribe_token`` — UUID per row, embedded in every outbound
      email's tokenized unsubscribe link + ``List-Unsubscribe`` header.
    - ``confirmed_at`` — set when self-subscribers confirm via the
      double-opt-in confirmation email. NULL for unconfirmed
      self-subscribers (``is_active=False`` until confirmed).
    - ``source`` — provenance: admin_added / self_subscribed /
      imported / directory_picked. Drives which onboarding email (if
      any) fires and whether double-opt-in applies.
    """

    SOURCE_CHOICES = [
        (SubscriberSource.ADMIN_ADDED, "Admin added"),
        (SubscriberSource.SELF_SUBSCRIBED, "Self-subscribed (public widget)"),
        (SubscriberSource.IMPORTED, "Imported (bulk paste / CSV)"),
        (SubscriberSource.DIRECTORY_PICKED, "Picked from workspace directory"),
    ]

    name = models.CharField(max_length=255, blank=True)
    email = models.EmailField()
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="content_subscribers",
    )
    subscribed_at = models.DateTimeField(auto_now_add=True)

    # Consent + lifecycle
    is_active = models.BooleanField(default=True, db_index=True)
    unsubscribed_at = models.DateTimeField(null=True, blank=True)
    unsubscribe_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(
        max_length=24,
        choices=SOURCE_CHOICES,
        default=SubscriberSource.ADMIN_ADDED,
    )

    class Meta:
        db_table = "content_subscriber"
        ordering = ("-subscribed_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "email"],
                name="content_subscriber_unique_workspace_email",
                condition=models.Q(workspace__isnull=False),
            ),
            models.UniqueConstraint(
                fields=["email"],
                name="content_subscriber_unique_email_when_no_workspace",
                condition=models.Q(workspace__isnull=True),
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "is_active"]),
        ]

    def __str__(self) -> str:
        return self.email


# ─────────────────────── SuppressedAddress ───────────────────────


class SuppressedAddress(models.Model):
    """Hard block on sending to an email address.

    Populated by:

    - SES SNS bounce notifications (``reason=hard_bounce``).
    - SES SNS complaint notifications (``reason=complaint``).
    - Admin "do not contact" toggle (``reason=manual``).
    - Admin remove-subscriber action (``reason=admin_removed``).

    The dispatch adapter MUST skip any subscriber whose email matches
    a row here — workspace-scoped match wins first; system-wide
    (workspace=NULL) match also blocks. This prevents reputation damage
    from re-sending to known-bad addresses even when subscribers are
    re-imported.

    A subscriber removed via the admin UI is BOTH soft-deleted on
    Subscriber AND added here with ``reason=admin_removed`` — so a
    later import of the same email gets re-suppressed automatically.
    """

    REASON_CHOICES = [
        (SuppressedAddressReason.HARD_BOUNCE, "Hard bounce"),
        (SuppressedAddressReason.COMPLAINT, "Spam complaint"),
        (SuppressedAddressReason.MANUAL, "Manually suppressed"),
        (SuppressedAddressReason.ADMIN_REMOVED, "Admin removed subscriber"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="content_suppressed_addresses",
        help_text="NULL means system-wide (e.g., a permanently invalid address).",
    )
    email = models.EmailField(db_index=True)
    reason = models.CharField(max_length=24, choices=REASON_CHOICES)
    suppressed_at = models.DateTimeField(auto_now_add=True)
    source_event = models.JSONField(
        default=dict,
        blank=True,
        help_text="SNS notification body or similar audit payload.",
    )

    class Meta:
        db_table = "content_suppressed_address"
        ordering = ("-suppressed_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "email"],
                name="content_suppressed_unique_workspace_email",
                condition=models.Q(workspace__isnull=False),
            ),
            models.UniqueConstraint(
                fields=["email"],
                name="content_suppressed_unique_email_when_no_workspace",
                condition=models.Q(workspace__isnull=True),
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "email"]),
        ]

    def __str__(self) -> str:
        return f"{self.email} ({self.reason})"


# ───────────────────────────── Newsletter ─────────────────────────────


class Newsletter(models.Model):
    """Workspace-scoped newsletter — drafted (by AI cadence or human) and
    explicitly sent by a human.

    Newsletters are NEVER auto-sent. Cadence-driven generation produces
    rows at ``status=ai_drafted``; only ``SendNewsletterUseCase`` (invoked
    by a human action endpoint) may flip status to ``sent``.

    Migrated from ``infrastructure.persistence.landing.Newsletter``. The
    legacy field ``content`` is renamed ``content_html`` here to make
    the body's media type explicit.
    """

    STATUS_CHOICES = [
        (NewsletterStatus.DRAFT, "Draft"),
        (NewsletterStatus.AI_DRAFTED, "AI-drafted (awaiting review)"),
        (NewsletterStatus.SCHEDULED, "Scheduled to send"),
        (NewsletterStatus.SENDING, "Sending"),
        (NewsletterStatus.SENT, "Sent"),
        (NewsletterStatus.SEND_FAILED, "Send failed"),
        (NewsletterStatus.ARCHIVED, "Archived"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="newsletters",
    )
    title = models.CharField(max_length=255)
    # Subject line shown in subscriber inboxes. Falls back to ``title``
    # if blank — we still want one editable knob in the editor without
    # forcing every legacy row to be re-saved.
    subject = models.CharField(max_length=255, blank=True)
    # Preheader text — the snippet preview most inbox clients show right
    # after the subject. Top-3 open-rate driver per industry data. 100
    # char practical cap (mobile preview truncates ~70).
    preheader = models.CharField(max_length=255, blank=True)
    # From display name override per send (e.g., "Zaylan via Wanjala").
    # The From email address is fixed to ``info@octopusintl.org`` at the
    # adapter layer.
    from_name = models.CharField(max_length=255, blank=True)
    # Reply-To for subscribers who hit reply. Defaults to the workspace
    # preference setting if blank.
    reply_to = models.EmailField(blank=True)

    content_html = models.TextField(blank=True)
    content_payload = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=NewsletterStatus.DRAFT,
        db_index=True,
    )
    scheduled_for = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True, db_index=True)

    pdf_key = models.CharField(max_length=512, blank=True)
    pdf_generated_at = models.DateTimeField(null=True, blank=True)

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="authored_newsletters",
    )
    ai_drafted_by_agent = models.CharField(max_length=64, blank=True)

    # Period semantics for cadence-driven rows. Nullable for ad-hoc
    # human-authored newsletters.
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)

    subscribers = models.ManyToManyField(
        Subscriber,
        related_name="newsletters",
        blank=True,
    )

    # Send metrics (denormalized counters, task #25). Written by the
    # dispatch ledger at send time and incremented row-by-row by the
    # open-pixel endpoint — NEVER aggregated at request time (rule §6a).
    # ``recipient_count`` is NULL for sends that predate tracking so the
    # UI can hide metrics instead of showing a false zero.
    recipient_count = models.IntegerField(null=True, blank=True)
    failed_count = models.IntegerField(null=True, blank=True)
    unique_open_count = models.IntegerField(default=0)
    total_open_count = models.IntegerField(default=0)
    last_opened_at = models.DateTimeField(null=True, blank=True)

    # Recycle-bin soft delete (task #29). ``objects`` (the default
    # manager) hides trashed rows from EVERY read path; the bin adapter
    # restores/purges via ``all_objects``.
    is_deleted = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = NotDeletedManager()
    all_objects = models.Manager()

    class Meta:
        db_table = "content_newsletter"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["workspace", "status"]),
            models.Index(fields=["workspace", "-created_at"]),
            models.Index(fields=["workspace", "period_start", "period_end"]),
        ]

    def __str__(self) -> str:
        return self.title


# ───────────────────────────── WritingTemplate ─────────────────────────────


class WritingTemplate(models.Model):
    """Seedable starter content for any composable Writing artifact.

    ``workspace`` nullable → global seeded template (Django fixtures load
    these). Non-null ``workspace`` → workspace-owned customization.
    """

    KIND_CHOICES = [
        (WritingTemplateKind.LETTER, "Letter"),
        (WritingTemplateKind.UPDATE, "Update"),
        (WritingTemplateKind.SUMMARY, "Summary"),
        (WritingTemplateKind.MEMO, "Memo"),
        (WritingTemplateKind.NEWSLETTER, "Newsletter"),
        (WritingTemplateKind.BLOG, "Blog"),
        (WritingTemplateKind.PROPOSAL, "Proposal"),
        # Social templates additionally carry ``metadata.platform``
        # (linkedin|instagram|tiktok|facebook) — each platform's format
        # and dimensions differ, so the compose wizard filters by it.
        (WritingTemplateKind.SOCIAL, "Social media"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="writing_templates",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, db_index=True)
    body_html = models.TextField(blank=True)
    is_seeded = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)
    # Soft delete → recycle bin (Template Kernel lifecycle). Trashed templates
    # drop out of the gallery + the writing template list; restore flips it back.
    is_deleted = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "content_writing_template"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["workspace", "kind"]),
            models.Index(fields=["kind", "is_seeded"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(is_seeded=False) | (models.Q(is_seeded=True) & models.Q(workspace__isnull=True))),
                name="content_writing_template_seeded_must_be_global",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.kind})"


# ───────────────────────────── WritingDraft ─────────────────────────────


class WritingDraft(models.Model):
    """Ad-hoc text artifact authored in the Writing surface.

    Covers letters, internal updates, period summaries, memos, blog
    posts, and entity-scoped updates (recipient / project / event /
    campaign). The ``kind`` discriminator routes UI rendering; the
    underlying schema is identical across kinds except for the optional
    ``related_entity_type`` + ``related_entity_id`` pair which the
    entity-scoped kinds populate so the editor can pre-load context and
    the published draft can be surfaced in the entity's activity feed.

    Optional FK to WritingTemplate captures the seed template (used for
    analytics; not load-bearing).
    """

    KIND_CHOICES = [
        (WritingDraftKind.LETTER, "Letter"),
        (WritingDraftKind.UPDATE, "Update"),
        (WritingDraftKind.SUMMARY, "Summary"),
        (WritingDraftKind.MEMO, "Memo"),
        (WritingDraftKind.BLOG, "Blog"),
        (WritingDraftKind.RECIPIENT_UPDATE, "Recipient update"),
        (WritingDraftKind.PROJECT_UPDATE, "Project update"),
        (WritingDraftKind.EVENT_UPDATE, "Event update"),
        (WritingDraftKind.CAMPAIGN_UPDATE, "Campaign update"),
    ]

    # Allowed values for ``related_entity_type`` — kept tight to a
    # known taxonomy so the editor doesn't have to guess what to load.
    RELATED_TYPE_RECIPIENT = "recipient"
    RELATED_TYPE_PROJECT = "project"
    RELATED_TYPE_EVENT = "event"
    RELATED_TYPE_CAMPAIGN = "campaign"
    RELATED_TYPE_CHOICES = [
        (RELATED_TYPE_RECIPIENT, "Recipient"),
        (RELATED_TYPE_PROJECT, "Project"),
        (RELATED_TYPE_EVENT, "Event"),
        (RELATED_TYPE_CAMPAIGN, "Campaign"),
    ]

    STATUS_CHOICES = [
        (WritingDraftStatus.DRAFT, "Draft"),
        (WritingDraftStatus.PUBLISHED, "Published"),
        (WritingDraftStatus.ARCHIVED, "Archived"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="writing_drafts",
    )
    title = models.CharField(max_length=255)
    body_html = models.TextField(blank=True)
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, db_index=True)
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=WritingDraftStatus.DRAFT,
        db_index=True,
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="authored_writing_drafts",
    )
    template = models.ForeignKey(
        WritingTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="drafts",
    )
    pdf_key = models.CharField(max_length=512, blank=True)
    pdf_generated_at = models.DateTimeField(null=True, blank=True)
    ai_drafted = models.BooleanField(default=False)
    # Entity-scoped link. Populated for kind in
    # {recipient_update, project_update, event_update, campaign_update};
    # NULL for free-form kinds (letter / update / summary / memo / blog).
    # Stored as type + UUID rather than a strict FK so the content
    # context doesn't pull cross-context schema in — the editor + the
    # surfacing handlers resolve the entity through the corresponding
    # bounded context's port.
    related_entity_type = models.CharField(
        max_length=16,
        blank=True,
        choices=RELATED_TYPE_CHOICES,
    )
    related_entity_id = models.UUIDField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    # Recycle-bin soft delete (task #29) — see NotDeletedManager.
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = NotDeletedManager()
    all_objects = models.Manager()

    class Meta:
        db_table = "content_writing_draft"
        ordering = ("-updated_at",)
        indexes = [
            models.Index(fields=["workspace", "status"]),
            models.Index(fields=["workspace", "kind", "status"]),
            models.Index(fields=["workspace", "author", "-updated_at"]),
            # Hot lookup for "show me every draft about this recipient /
            # project / event / campaign" — the entity's activity feed.
            models.Index(
                fields=["workspace", "related_entity_type", "related_entity_id"],
                name="content_draft_related_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.kind}/{self.status})"


class EmailDispatchRecord(models.Model):
    """One row per recipient of an emailed Communications artifact
    (task #25 — send metrics).

    Written by the dispatch ledger when a newsletter (and, next slice,
    a draft-email share) goes out. ``open_token`` keys the per-recipient
    tracking pixel; opens increment here AND on the artifact's
    denormalized counters so list cards never aggregate at request time.
    Artifact-generic by design: exactly one of ``newsletter`` / ``draft``
    is set.
    """

    STATUS_PENDING = "pending"
    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SENT, "Sent"),
        (STATUS_FAILED, "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="email_dispatch_records",
    )
    newsletter = models.ForeignKey(
        Newsletter,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="dispatch_records",
    )
    draft = models.ForeignKey(
        WritingDraft,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="email_dispatch_records",
    )
    recipient_email = models.EmailField()
    status = models.CharField(
        max_length=8,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    open_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    open_count = models.IntegerField(default=0)
    first_opened_at = models.DateTimeField(null=True, blank=True)
    last_opened_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "content_email_dispatch_record"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["newsletter", "status"]),
            models.Index(fields=["draft", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.recipient_email} ({self.status})"
