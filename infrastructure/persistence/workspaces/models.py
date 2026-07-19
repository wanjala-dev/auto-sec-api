import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class WorkspaceCategory(models.Model):
    name = models.CharField(max_length=200, unique=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class SubCategory(models.Model):
    name = models.CharField(max_length=200)
    category = models.ForeignKey(WorkspaceCategory, on_delete=models.CASCADE, related_name="subcategories")

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class WorkspaceOperations(models.Model):
    name = models.CharField(max_length=200, unique=False)
    checked = models.BooleanField(default=False)
    text = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class ObjectTracking(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ("-created_at",)


class Tag(ObjectTracking):
    name = models.CharField(max_length=50)

    def __str__(self):
        return self.name

    class Meta:
        ordering = []


class WorkspaceManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(status="active")

    def all_objects(self):
        return super().get_queryset()

    def inactive(self):
        return self.all_objects().filter(status="inactive")


class Workspace(models.Model):
    PUBLIC = "public"
    PRIVATE = "private"

    PRIVACY_CHOICES = (
        (PUBLIC, "public"),
        (PRIVATE, "private"),
    )

    PERSONAL = "personal"
    TEAMSPACE = "teamspace"
    WORKSPACE_TYPE_CHOICES = (
        (PERSONAL, "Personal"),
        (TEAMSPACE, "Teamspace"),
    )

    PLAN_ACTIVE = "active"
    PLAN_CANCELED = "canceled"
    PLAN_STATUS_CHOICES = (
        (PLAN_ACTIVE, "Active"),
        (PLAN_CANCELED, "Canceled"),
    )

    id = models.UUIDField(max_length=200, default=uuid.uuid4, unique=True, primary_key=True, editable=False)
    workspace_type = models.CharField(max_length=20, choices=WORKSPACE_TYPE_CHOICES, default=TEAMSPACE, db_index=True)
    workspace_name = models.CharField(max_length=250, blank=True)
    workspace_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="workspace_ownner", on_delete=models.CASCADE
    )
    # Security domains this workspace operates across (Cloud, Endpoint, Network,
    # Identity, …) — the generalized successor to the nonprofit sector concept.
    domains = models.ManyToManyField("domains.Domain", related_name="workspaces", blank=True)
    is_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    default_currency = models.CharField(
        max_length=3,
        default="USD",
        blank=False,
        help_text=(
            "ISO 4217 currency used for display when no connected "
            "payment method is available yet. Once a WorkspacePaymentMethod "
            "is connected, its settlement_currency takes precedence. "
            "NOT NULL since the money-context rollout — every existing row "
            "was backfilled honestly."
        ),
    )
    ai_teammate_enabled = models.BooleanField(default=False)
    notifications_enabled = models.BooleanField(default=True)
    donor_tips_enabled = models.BooleanField(
        default=True,
        help_text=(
            "When True, donation checkouts may show an optional donor tip — a "
            "voluntary contribution to the platform on top of the donation, "
            "taken as a Stripe Connect application_fee (the org keeps its full "
            "donation). Default True for the nonprofit ICP; the tip only ever "
            "surfaces on donation checkouts that have a connected payment "
            "account. Org-level kill switch: set False to hide the tip ask "
            "entirely. See docs/plans/DONOR_TIPS_IMPLEMENTATION.md."
        ),
    )
    # Donation-monetization axis (orthogonal to the feature tier). How the
    # platform earns on donations this workspace moves: a voluntary donor tip,
    # a revenue-share % of each gift, or nothing. Exactly ONE applies per
    # workspace — they never stack on a single gift (that would be charging
    # twice for the same value). `revenue_share` is DEFERRED (the dormant
    # WorkspacePaymentMethod.platform_fee_bps lever); only `tip`/`none` are
    # wired today. Default `tip` preserves the current donor-tip behaviour.
    # See docs/plans/PREMIUM_FEATURE_TIERS_PLAN.md §6.
    DONATION_MONETIZATION_TIP = "tip"
    DONATION_MONETIZATION_REVENUE_SHARE = "revenue_share"
    DONATION_MONETIZATION_NONE = "none"
    DONATION_MONETIZATION_CHOICES = (
        (DONATION_MONETIZATION_TIP, "Donor tip"),
        (DONATION_MONETIZATION_REVENUE_SHARE, "Revenue share"),
        (DONATION_MONETIZATION_NONE, "None"),
    )
    donation_monetization = models.CharField(
        max_length=16,
        choices=DONATION_MONETIZATION_CHOICES,
        default=DONATION_MONETIZATION_TIP,
        help_text=(
            "How the platform monetizes donations this workspace moves: "
            "'tip' (voluntary donor tip, current default), 'revenue_share' "
            "(flat percentage cut via revenue_share_bps), or 'none' (no platform "
            "cut on donations). Orthogonal to the feature tier; never stacks "
            "with another donation cut on the same gift."
        ),
    )
    # Revenue-share rate (only meaningful when donation_monetization=='revenue_share').
    # A FLAT percentage of each donation, taken as the Stripe Connect
    # application_fee. Market-standard shape (no per-charge volume threshold — a
    # volume-marginal model was researched + rejected as bespoke/complex). A paid
    # plan tier can later buy this rate down. See
    # components.payments.domain.policies.monetization_policy.
    revenue_share_bps = models.PositiveIntegerField(
        default=300,
        help_text=(
            "Revenue-share rate in basis points (300 = 3%). Applied as a flat "
            "Connect application_fee on every donation when donation_monetization "
            "is 'revenue_share'. Ignored in tip/none modes."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    followers = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="workspace_followers")
    workspace_categories = models.ManyToManyField(WorkspaceCategory, related_name="workspaces", blank=True)
    workspace_subcategories = models.ManyToManyField(SubCategory, related_name="workspaces")
    workspace_story = models.TextField(null=True, blank=True)
    vision = models.TextField(null=True, blank=True)
    mission = models.TextField(null=True, blank=True)
    # Free-text goals / objectives the org is working toward. Read by the
    # planner alongside vision / mission so AI-drafted plans and donor copy
    # honour what the org is actually trying to do.
    goals = models.TextField(null=True, blank=True)
    contact_email = models.EmailField(max_length=254, blank=True, default="")
    phone = models.CharField(max_length=64, blank=True, default="")
    # Address / location fields used by Settings -> Address tab. `country`
    # is the canonical primary country (matches the map picker selection)
    # and anchors currency hints + funder catalogs. `location` is the
    # short human-readable label (e.g. "Kampala, Uganda"). The remaining
    # fields back the structured mailing address used by receipts and
    # grant paperwork.
    country = models.CharField(max_length=120, blank=True, default="")
    location = models.CharField(max_length=255, blank=True, default="")
    street_address = models.CharField(max_length=255, blank=True, default="")
    city = models.CharField(max_length=120, blank=True, default="")
    state_region = models.CharField(max_length=120, blank=True, default="")
    postal_code = models.CharField(max_length=32, blank=True, default="")
    # max_length was 120 and silently truncated long S3 / CloudFront URLs
    # on upload. Bumped to 500 to fit signed URLs + forward-compat buckets.
    photo_url = models.CharField(max_length=500, blank=True)
    cover_photo_url = models.CharField(max_length=500, blank=True, default="")
    privacy = models.CharField(
        max_length=8,
        choices=PRIVACY_CHOICES,
        default=PUBLIC,
    )
    shared_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    tags = models.ManyToManyField("Tag", blank=True)
    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)
    status = models.CharField(default="inactive", max_length=10)
    shared_on = models.DateTimeField(blank=True, null=True)
    shared_body = models.TextField(blank=True, null=True)
    operations = models.ManyToManyField(WorkspaceOperations, blank=True, related_name="workspace_followers")
    # Org subscription tier (SaaS billing). Nullable freemium default.
    plan = models.ForeignKey(
        "subscription.Plan", on_delete=models.SET_NULL, null=True, blank=True, related_name="workspace_plan"
    )
    contribution_means = models.ManyToManyField("ContributionMeans", related_name="workspaces", blank=True)
    plan_status = models.CharField(max_length=20, choices=PLAN_STATUS_CHOICES, default=PLAN_ACTIVE)
    plan_end_date = models.DateTimeField(blank=True, null=True)
    stripe_customer_id = models.CharField(max_length=255, blank=True, null=True)
    stripe_subscription_id = models.CharField(max_length=255, blank=True, null=True)
    subscription_payment_method_id = models.UUIDField(blank=True, null=True)
    # Per-workspace numeric entitlement grants that override the plan's
    # limits ({EntitlementKey: int|None}). The seam for paying-customer
    # opt-ins (mirrors FeatureFlagRule) and, later, Stripe-Entitlements
    # sync. Resolution order: workspace override -> plan limits -> default.
    # Empty by default (= plan limits apply unchanged).
    entitlement_overrides = models.JSONField(default=dict, blank=True)

    @property
    def is_personal(self):
        return self.workspace_type == self.PERSONAL

    @property
    def is_teamspace(self):
        return self.workspace_type == self.TEAMSPACE

    def create_tags(self):
        for word in self.workspace_story.split():
            if word[0] == "#":
                tag = Tag.objects.filter(name=word[1:]).first()
                if tag:
                    self.tags.add(tag.pk)
                else:
                    tag = Tag(name=word[1:])
                    tag.save()
                    self.tags.add(tag.pk)
                self.save()

        if self.shared_body:
            for word in self.shared_body.split():
                if word[0] == "#":
                    tag = Tag.objects.filter(name=word[1:]).first()
                    if tag:
                        self.tags.add(tag.pk)
                    else:
                        tag = Tag(name=word[1:])
                        tag.save()
                        self.tags.add(tag.pk)
                    self.save()

    objects = WorkspaceManager()

    class Meta:
        ordering = ["-created_at", "-shared_on"]
        db_table = "workspaces"
        indexes = [
            models.Index(fields=["-created_at"], name="workspace_created_at_idx"),
            models.Index(fields=["status", "is_active"], name="workspace_status_active_idx"),
        ]

    def __str__(self):
        return self.workspace_name


class WorkspaceMembership(models.Model):
    """Role-aware membership for users within a workspace (organization).

    See ``docs/adr/0002-personas-and-rbac.md`` for the full rationale on why
    ``persona`` and ``role`` are kept as two orthogonal fields. In short:

    - ``role`` is the RBAC tier — every permission decision in the API reads
      this and only this. Standard owner/admin/member/viewer.
    - ``persona`` is the experience type — drives which dashboard, sidebar,
      and copy variants the frontend renders. Permission code MUST NEVER
      branch on persona.
    """

    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        MEMBER = "member", "Member"
        VIEWER = "viewer", "Viewer"

    class Persona(models.TextChoices):
        ADMIN = "admin", "Admin"
        CONTRIBUTOR = "contributor", "Contributor"
        SPONSOR = "sponsor", "Sponsor"
        VOLUNTEER = "volunteer", "Volunteer"
        AUDITOR = "auditor", "Auditor"
        BOARD_MEMBER = "board_member", "Board Member"
        AGENTIC = "agentic", "Agentic"
        PRIVATE = "private", "Private"
        # Guest on someone else's personal workspace — the "family member
        # joins my private books" or "accountant reviews my finances"
        # case. Renders under the frontend's "Shared with me" sidebar
        # bucket. Read-mostly finance/AI/projects; no settings, no
        # ownership operations. Named after Xero's Adviser role.
        ADVISER = "adviser", "Adviser"

    class Status(models.TextChoices):
        INVITED = "invited", "Invited"
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        # Self-service join (volunteer/contribute) that still needs the
        # workspace owner to approve before it becomes ACTIVE. The user
        # lands on the persona dashboard immediately but sees a
        # "pending approval" lock overlay until the owner approves the
        # paired WorkspaceJoinRequest. See the onboarding relationship flow.
        PENDING = "pending", "Pending approval"

    workspace = models.ForeignKey("Workspace", on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="workspace_memberships")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MEMBER)
    # Capability-backed role assignment. Nullable during the migration
    # window so legacy rows without a matching system role don't fail
    # to load; Phase 2 onward treats null as a hard bug.
    # See ADR 0002 + the role-redesign plan.
    workspace_role = models.ForeignKey(
        "workspaces.WorkspaceRole",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="memberships",
        help_text=(
            "Capability bundle driving RBAC. Null for memberships created before "
            "the role redesign backfill ran; Phase 2 authorization treats null "
            "as no permissions."
        ),
    )
    persona = models.CharField(
        max_length=20,
        choices=Persona.choices,
        default=Persona.CONTRIBUTOR,
        help_text=(
            "Experience type — drives which dashboard the user sees. "
            "NEVER read this in permission checks; use ``role`` instead. "
            "See ADR 0002."
        ),
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    # Workspace-scoped CRM tags for the directory contact (the member). Workflow
    # automations (Keela-style "Add Tag" / "Remove Tag" action nodes) add and
    # remove these; tagging is scoped to the membership — NOT the global user —
    # so a tag applied in one workspace never leaks into another. See
    # components/workflow/infrastructure/adapters/node_actions.py.
    tags = models.ManyToManyField("Tag", blank=True, related_name="workspace_memberships")
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workspace_membership_invites",
    )
    accepted_at = models.DateTimeField(null=True, blank=True)
    # Marks a row as a support impersonation membership — created when a
    # platform admin starts a SupportImpersonationSession, deleted when
    # that session ends. Always coexists with (and never replaces) the
    # user's real membership on the workspace, so revoking the session
    # restores the user's true access. Member-listing code filters
    # ``is_impersonation=False`` so impersonation rows don't appear as
    # team members. Permission helpers DO match on these rows so the
    # impersonation grants the chosen role/persona to the platform
    # admin for the duration of the session.
    is_impersonation = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # ``is_impersonation`` is part of the uniqueness so a real
            # membership and an impersonation membership for the same
            # (workspace, user) can coexist. Without this the platform
            # admin couldn't impersonate on a workspace they're already
            # a member of.
            models.UniqueConstraint(
                fields=["workspace", "user", "is_impersonation"],
                name="uniq_workspace_membership",
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "role"], name="workspace_membership_role_idx"),
            models.Index(fields=["user", "role"], name="ws_mship_user_role_idx"),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.workspace_id}:{self.user_id}:{self.role}"


class WorkspaceJoinRequest(models.Model):
    """A user's request to join a private workspace.

    Approval creates a ``WorkspaceMembership``; denial marks the row
    closed with an optional note. See
    ``components/workspace/domain/entities/workspace_join_request_entity.py``
    for the invariants and state-transition rules.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        DENIED = "denied", "Denied"
        WITHDRAWN = "withdrawn", "Withdrawn"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="join_requests",
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workspace_join_requests",
    )
    message = models.TextField(blank=True, default="")
    # Which experience the requester asked for — volunteer vs contributor.
    # Approval copies this onto the WorkspaceMembership.persona so the two
    # team personas stay distinct (they share a sidebar but record intent).
    # Defaults to contributor for legacy/back-compat rows.
    requested_persona = models.CharField(
        max_length=20,
        choices=WorkspaceMembership.Persona.choices,
        default=WorkspaceMembership.Persona.CONTRIBUTOR,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_workspace_join_requests",
    )
    review_note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-requested_at"]
        indexes = [
            models.Index(
                fields=["workspace", "status"],
                name="wsjoinreq_ws_status_idx",
            ),
            models.Index(
                fields=["requester", "status"],
                name="wsjoinreq_user_status_idx",
            ),
        ]
        constraints = [
            # Only one pending request per (workspace, requester) at a time.
            # Terminal-state rows are allowed to repeat so users can request
            # again after a denial / withdrawal.
            models.UniqueConstraint(
                fields=["workspace", "requester"],
                condition=models.Q(status="pending"),
                name="uniq_pending_workspace_join_request",
            ),
        ]

    def __str__(self):
        return f"{self.workspace_id}:{self.requester_id}:{self.status}"


class WorkspaceComment(models.Model):
    PUBLIC = "public"
    PRIVATE = "private"

    PRIVACY_CHOICES = (
        (PUBLIC, "public"),
        (PRIVATE, "private"),
    )

    comment = models.TextField()
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    created_on = models.DateTimeField(default=timezone.now)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="workspace_comment_author", on_delete=models.CASCADE
    )
    likes = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="workspace_comment_likes")
    privacy = models.CharField(
        max_length=8,
        choices=PRIVACY_CHOICES,
        default=PUBLIC,
    )
    dislikes = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="workspace_comment_dislikes")
    parent = models.ForeignKey("self", on_delete=models.CASCADE, blank=True, null=True, related_name="+")
    tags = models.ManyToManyField("Tag", blank=True)

    def create_tags(self):
        for word in self.comment.split():
            if word[0] == "#":
                tag = Tag.objects.get(name=word[1:])
                if tag:
                    self.tags.add(tag.pk)
                else:
                    tag = Tag(name=word[1:])
                    tag.save()
                    self.tags.add(tag.pk)
                self.save()

    @property
    def recipients(self):
        return WorkspaceComment.objects.filter(parent=self).order_by("-created_on").all()

    @property
    def is_parent(self):
        if self.parent is None:
            return True
        return False

    def __str__(self):
        return self.comment


## Removed legacy Income and Expense models in favor of budget.transactions.Transaction


class Action(models.Model):
    PUBLIC = "public"
    PRIVATE = "private"

    PRIVACY_CHOICES = (
        (PUBLIC, "public"),
        (PRIVATE, "private"),
    )

    title = models.CharField(max_length=200, unique=False)
    body = models.TextField(blank=True)
    privacy = models.CharField(
        max_length=8,
        choices=PRIVACY_CHOICES,
        default=PRIVATE,
    )
    created_date = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="action", on_delete=models.CASCADE)
    likes = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="workspace_action_likes")
    dislikes = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="workspace_action_dislikes")
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)

    class Meta:
        ordering = ("title",)
        db_table = "action"

    def __str__(self):
        return self.title


class WorkspaceCard(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    name = models.CharField(max_length=200, unique=True)
    checked = models.BooleanField(default=True)
    text = models.TextField(null=True, blank=True)
    photo_url = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class ContributionMeans(models.Model):
    name = models.CharField(max_length=100, unique=True)
    icon = models.CharField(max_length=100, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class Grant(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        OPEN = "open", "Open"
        SUBMITTED = "submitted", "Submitted"
        AWARDED = "awarded", "Awarded"
        REJECTED = "rejected", "Rejected"
        CLOSED = "closed", "Closed"

    class PipelineStage(models.TextChoices):
        """Phase-1 pipeline stage. Denormalized cache of MAX(decision)
        for fast Kanban rendering. The canonical history lives in
        GrantDecision (added in Phase 0)."""

        RESEARCHING = "researching", "Researching"
        LOI = "loi", "Letter of Inquiry"
        INVITED = "invited", "Invited to Apply"
        DRAFTING = "drafting", "Drafting"
        SUBMITTED = "submitted", "Submitted"
        UNDER_REVIEW = "under_review", "Under Review"
        AWARDED = "awarded", "Awarded"
        DECLINED = "declined", "Declined"

    class RestrictionType(models.TextChoices):
        """Phase-3 award restriction classification, per FASB ASU
        2016-14 vocabulary. Drives books-balance enforcement and the
        Statement of Activities release-from-restriction line."""

        UNRESTRICTED = "unrestricted", "Unrestricted"
        PURPOSE = "purpose", "Purpose-restricted"
        TIME = "time", "Time-restricted"
        PERMANENT = "permanent", "Permanently restricted"

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="grants")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="owned_grants")
    # Phase 1: canonical_funder is the structured FK; funder_name is kept
    # as a legacy free-text fallback for grants entered before the funder
    # catalog existed. Phase 2 normalizes legacy rows by upserting funders.
    canonical_funder = models.ForeignKey(
        "workspaces.Funder",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="grants",
    )
    opportunity = models.ForeignKey(
        "workspaces.GrantOpportunity",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="grants",
    )
    title = models.CharField(max_length=255)
    funder_name = models.CharField(max_length=255, blank=True)
    amount_requested = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    amount_awarded = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    currency = models.CharField(max_length=8, default="USD")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    pipeline_stage = models.CharField(
        max_length=20,
        choices=PipelineStage.choices,
        default=PipelineStage.RESEARCHING,
    )
    # Phase 3 — award restriction + match metadata. Defaults keep
    # Phase 1 / Phase 2 rows valid; the AwardGrantedHandler reads these
    # when materialising the BudgetCategory + Disbursement schedule.
    restriction_type = models.CharField(
        max_length=20,
        choices=RestrictionType.choices,
        default=RestrictionType.UNRESTRICTED,
    )
    purpose_summary = models.TextField(blank=True)
    restricted_period_start = models.DateField(null=True, blank=True)
    restricted_period_end = models.DateField(null=True, blank=True)
    sub_recipient = models.BooleanField(default=False)
    matching_required = models.BooleanField(default=False)
    match_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )
    # Stored as the funder's match ratio (e.g. 0.50 = 50% match). Phase 3
    # reporting will derive the implied required match from
    # match_amount + match_ratio + amount_awarded.
    match_ratio = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=0,
        validators=[MinValueValidator(0)],
    )
    submission_deadline = models.DateField(null=True, blank=True)
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    # Phase 5 — donor-public visibility. Default off; only when an
    # owner/admin flips is_public does this grant become visible on the
    # /public/ transparency surface. public_summary overrides notes on
    # the public page so internal notes never leak.
    is_public = models.BooleanField(
        default=False,
        help_text=(
            "When true, this grant is visible on the public "
            "transparency surface. Defaults to false — owners "
            "and admins must explicitly publish."
        ),
    )
    public_summary = models.TextField(
        blank=True,
        help_text=("Donor-public description. Overrides notes on the public page; internal notes never leak."),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["workspace", "status"], name="grant_workspace_status_idx"),
            models.Index(fields=["workspace", "pipeline_stage"], name="grant_ws_stage_idx"),
            models.Index(fields=["submission_deadline"], name="grant_deadline_idx"),
            models.Index(fields=["canonical_funder"], name="grant_funder_idx"),
            models.Index(fields=["opportunity"], name="grant_opportunity_idx"),
            models.Index(fields=["workspace", "is_public"], name="grant_ws_public_idx"),
        ]

    def __str__(self):
        return self.title


class GrantChecklistItem(models.Model):
    grant = models.ForeignKey(Grant, on_delete=models.CASCADE, related_name="checklist_items")
    title = models.CharField(max_length=255)
    checked = models.BooleanField(default=False)
    due_date = models.DateField(null=True, blank=True)
    order = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="grant_checklist_items"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "created_at"]
        indexes = [
            models.Index(fields=["grant", "checked"], name="grant_checklist_checked_idx"),
        ]

    def __str__(self):
        return f"{self.grant_id}:{self.title}"


class GrantReminder(models.Model):
    class Channel(models.TextChoices):
        IN_APP = "in_app", "In App"
        EMAIL = "email", "Email"

    grant = models.ForeignKey(Grant, on_delete=models.CASCADE, related_name="reminders")
    remind_at = models.DateTimeField()
    message = models.CharField(max_length=500)
    channel = models.CharField(max_length=20, choices=Channel.choices, default=Channel.IN_APP)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="grant_reminders")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["remind_at"]
        indexes = [
            models.Index(fields=["grant", "remind_at"], name="grant_remind_at_idx"),
        ]

    def __str__(self):
        return f"{self.grant_id}:{self.remind_at.isoformat()}"


class GrantAllocation(models.Model):
    grant = models.ForeignKey(Grant, on_delete=models.CASCADE, related_name="allocations")
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="grant_allocations")
    # budget.Budget FK dropped in the auto-sec fork (budgeting context removed).
    name = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    allocation_percent = models.DecimalField(
        max_digits=5, decimal_places=2, validators=[MinValueValidator(0), MaxValueValidator(100)], default=0
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="grant_allocations")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["grant", "workspace"], name="grant_alloc_workspace_idx"),
        ]

    def __str__(self):
        return f"{self.grant_id}:{self.name}"


class GrantBudgetLine(models.Model):
    """A single approved line in an awarded grant's budget — e.g.
    "Salaries $10,000", "Rent 40%", "Supplies $5,000".

    This is the line-item layer a funder auditor expects (Greg Boston /
    QuickBooks-for-Nonprofits checklist; Sage Intacct restricted-fund
    budgeting): each restricted grant carries its own budget broken into
    authorized expense lines, and spend is tracked per line (budget vs
    actual). Mirrors the RecipientNeed pattern — Transaction.grant_line
    points an expense at the line it draws down, so per-line "spent" is a
    simple aggregate over tagged transactions, reusing the existing
    books-balance machinery rather than a parallel ledger.

    Invariant (enforced in the application use case, NOT the model, so it
    lives beside the GrantAllocation-sum rule): the sum of approved_amount
    across a grant's lines must not exceed Grant.amount_awarded, and
    percent_basis (when used) must not exceed 100.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    grant = models.ForeignKey(Grant, on_delete=models.CASCADE, related_name="budget_lines")
    label = models.CharField(max_length=255)
    approved_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )
    # Optional funder-expressed basis (e.g. "40% of rent"). Stored as a
    # percentage 0–100; null when the line is a flat amount.
    percent_basis = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    order = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="grant_budget_lines",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "created_at"]
        indexes = [
            models.Index(fields=["grant", "order"], name="grant_budget_line_idx"),
        ]

    def __str__(self):
        return f"{self.grant_id}:{self.label}"


class GrantDocument(models.Model):
    """Associates a shared uploaded File with a grant — the signed
    agreement, award letter, funder report, or correspondence.

    The auditor's pet peeve (Greg Boston checklist): "save the signed
    grant and attach it to the record." The File itself lives in the
    shared content-addressed uploads table (reuse, NOT a grants-only
    document store — constitutional rule #10); GrantDocument is just the
    link plus grant-specific metadata (doc_type, label, visibility).
    """

    class DocType(models.TextChoices):
        AGREEMENT = "agreement", "Signed Agreement"
        AWARD_LETTER = "award_letter", "Award Letter"
        REPORT = "report", "Funder Report"
        CORRESPONDENCE = "correspondence", "Correspondence"
        OTHER = "other", "Other"

    class Visibility(models.TextChoices):
        INTERNAL = "internal", "Internal"
        PUBLIC = "public", "Public"

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    grant = models.ForeignKey(Grant, on_delete=models.CASCADE, related_name="documents")
    file = models.ForeignKey(
        "uploads.File",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="grant_documents",
    )
    doc_type = models.CharField(max_length=20, choices=DocType.choices, default=DocType.OTHER)
    label = models.CharField(max_length=255, blank=True)
    visibility = models.CharField(
        max_length=20,
        choices=Visibility.choices,
        default=Visibility.INTERNAL,
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="grant_documents",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["grant", "doc_type"], name="grant_document_idx"),
        ]

    def __str__(self):
        return f"{self.grant_id}:{self.doc_type}"


# ============================================================================
# Grants — Phase 0 scale-ready additions
# ----------------------------------------------------------------------------
# Salesforce Nonprofit Cloud + Fluxx Data Core pattern: decisions,
# requirements, disbursements, application drafts, and audit events are
# all first-class objects. Status fields on Grant are denormalized caches
# of the latest GrantDecision; the real history lives here. Versioned
# drafts are append-only — every save creates a new row.
# See ~/.claude/skills/grants/SKILL.md sections 1 and 3.
# ============================================================================


class GrantDecision(models.Model):
    """Immutable state-transition record for a grant.

    Every pipeline-stage move, submission, invitation, award, decline,
    withdrawal, and closure is a new row. The Grant.status (and the
    Phase-1 pipeline_stage) is a denormalized cache of MAX(decided_at).
    No update/delete in the repository — decisions are facts.
    """

    class DecisionType(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        INVITED = "invited", "Invited"
        LOI_SENT = "loi_sent", "LOI Sent"
        AWARDED = "awarded", "Awarded"
        DECLINED = "declined", "Declined"
        WITHDRAWN = "withdrawn", "Withdrawn"
        CLOSED = "closed", "Closed"

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    grant = models.ForeignKey(Grant, on_delete=models.CASCADE, related_name="decisions")
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="grant_decisions")
    decision_type = models.CharField(max_length=20, choices=DecisionType.choices)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="grant_decisions")
    decided_at = models.DateTimeField(default=timezone.now)
    note = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)
    idempotency_key = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-decided_at"]
        indexes = [
            models.Index(fields=["grant", "decided_at"], name="grant_decision_grant_idx"),
            models.Index(fields=["workspace", "decision_type"], name="grant_decision_ws_type_idx"),
        ]

    def __str__(self):
        return f"{self.grant_id}:{self.decision_type}@{self.decided_at.isoformat()}"


class AwardRequirement(models.Model):
    """Post-award obligation — narrative report, financial report, site
    visit, sub-recipient report, match certification.

    Each requirement is its own dated, ownable record (Salesforce
    FundingAwardRequirement pattern). Phase 4 wires linked_period_id to
    ReportingPeriod once that model lands.
    """

    class RequirementType(models.TextChoices):
        NARRATIVE_REPORT = "narrative_report", "Narrative Report"
        FINANCIAL_REPORT = "financial_report", "Financial Report"
        SITE_VISIT = "site_visit", "Site Visit"
        SUB_RECIPIENT_REPORT = "sub_recipient_report", "Sub-Recipient Report"
        MATCH_CERTIFICATION = "match_certification", "Match Certification"
        OTHER = "other", "Other"

    class Recurrence(models.TextChoices):
        ONE_TIME = "one_time", "One Time"
        QUARTERLY = "quarterly", "Quarterly"
        ANNUAL = "annual", "Annual"

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    grant = models.ForeignKey(Grant, on_delete=models.CASCADE, related_name="requirements")
    requirement_type = models.CharField(max_length=30, choices=RequirementType.choices)
    description = models.TextField(blank=True)
    due_date = models.DateField(null=True, blank=True)
    recurrence = models.CharField(max_length=20, choices=Recurrence.choices, default=Recurrence.ONE_TIME)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="completed_grant_requirements",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_grant_requirements",
    )
    # Phase 4 — points at the ReportingPeriod that satisfies this
    # requirement. SET_NULL on period delete so the requirement
    # outlives its scheduled window.
    linked_period = models.ForeignKey(
        "ReportingPeriod",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requirements",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["due_date", "created_at"]
        indexes = [
            models.Index(fields=["grant", "due_date"], name="grant_req_due_idx"),
            models.Index(fields=["due_date", "completed_at"], name="grant_req_pending_idx"),
        ]

    def __str__(self):
        return f"{self.grant_id}:{self.requirement_type}@{self.due_date}"


class GrantDisbursement(models.Model):
    """Expected vs actual payment tranche for an awarded grant.

    transaction is populated via the Phase 3 award→budget integration
    when a real Transaction with source_type='grant' matches an expected
    disbursement.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    grant = models.ForeignKey(Grant, on_delete=models.CASCADE, related_name="disbursements")
    expected_amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    actual_amount = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    expected_date = models.DateField(null=True, blank=True)
    received_date = models.DateField(null=True, blank=True)
    # Phase 3 will FK to budget.transactions.Transaction; UUID kept loose.
    transaction_id = models.UUIDField(null=True, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["expected_date", "created_at"]
        indexes = [
            models.Index(fields=["grant", "expected_date"], name="grant_disb_expected_idx"),
        ]

    def __str__(self):
        return f"{self.grant_id}:disb@{self.expected_date}"


class GrantApplicationDraft(models.Model):
    """Append-only versioned grant application draft.

    Every save creates a new row referencing parent_version_id. The
    current draft is MAX(version) for a grant. Submit copies the latest
    revision into an immutable GrantApplicationSubmission (added in
    Phase 1) and records a GrantDecision(decision_type='submitted').

    Narrative is stored as markdown directly for now; Phase 1 may move
    long narratives to S3 via content-hash pointers (see plan section
    "Risks and gotchas" — versioned drafts can grow unbounded).
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    grant = models.ForeignKey(Grant, on_delete=models.CASCADE, related_name="application_drafts")
    version = models.PositiveIntegerField()
    parent_version = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="child_versions",
    )
    # Phase 1 will FK to ApplicationTemplate; UUID kept loose.
    schema_version_id = models.UUIDField(null=True, blank=True)
    fields = models.JSONField(default=dict, blank=True)
    narrative_md = models.TextField(blank=True)
    authored_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="authored_grant_drafts"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version"]
        unique_together = [("grant", "version")]
        indexes = [
            models.Index(fields=["grant", "version"], name="grant_draft_latest_idx"),
        ]

    def __str__(self):
        return f"{self.grant_id}:draft@v{self.version}"


class GrantAuditEvent(models.Model):
    """Append-only, tenant-scoped audit log on every grant state-changing
    write.

    Funders, boards, and statutory auditors all ask for this artifact.
    Written by the grant repository on every create/update/delete and by
    the use cases that mutate decisions/requirements/disbursements/drafts.
    Never updated, never deleted.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="grant_audit_events")
    grant = models.ForeignKey(Grant, on_delete=models.CASCADE, related_name="audit_events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="grant_audit_events")
    event_type = models.CharField(max_length=64)
    payload = models.JSONField(default=dict, blank=True)
    ts = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-ts"]
        indexes = [
            models.Index(fields=["workspace", "grant", "-ts"], name="grant_audit_lookup_idx"),
            models.Index(fields=["event_type"], name="grant_audit_type_idx"),
        ]

    def __str__(self):
        return f"{self.grant_id}:{self.event_type}@{self.ts.isoformat()}"


# ============================================================================
# Grants Phase 1 — workspace-scoped Funder catalog, Opportunity catalog,
# Snippet library, and Application Template registry.
# ----------------------------------------------------------------------------
# Phase 1 ships these workspace-scoped. Phase 2 promotes Funder + Opportunity
# to platform-owned global tables (PlatformFunder/PlatformOpportunity) with
# the workspace records becoming overlays pointing at the canonical platform
# row via FK. Same data shape; no migration pain.
# See ~/.claude/skills/grants/SKILL.md sections 1.5 and 3.
# ============================================================================


class Funder(models.Model):
    """Workspace-scoped funder catalog entry.

    Phase 2: optionally linked to a platform-owned `PlatformFunder` via
    `platform_funder` FK so a workspace's "Gates Foundation" record can
    reference the canonical platform row for cross-tenant funder history
    and funder-graph queries — without losing the workspace-scoped
    contact + notes overlay.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="funders")
    platform_funder = models.ForeignKey(
        "workspaces.PlatformFunder",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workspace_overlays",
    )
    name = models.CharField(max_length=255)
    canonical_key = models.SlugField(max_length=255, blank=True)
    contact_name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=64, blank=True)
    website = models.URLField(blank=True)
    notes = models.TextField(blank=True)
    tags = models.JSONField(default=list, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="created_funders")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "canonical_key"],
                name="funder_ws_canonical_key_unique",
                condition=models.Q(canonical_key__gt=""),
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "name"], name="funder_ws_name_idx"),
        ]

    def __str__(self):
        return f"{self.name} ({self.workspace_id})"


class GrantOpportunity(models.Model):
    """Workspace-scoped grant opportunity (RFP / NOFO / posted call).

    Phase 1 = manually entered. Phase 2 = also ingested from Grants.gov
    (and promoted to platform-owned `PlatformOpportunity` with a workspace
    overlay record pointing here). Status mirrors how funders describe
    the opportunity, not pipeline (which lives on Grant.pipeline_stage
    once converted).
    """

    class OpportunityStatus(models.TextChoices):
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"
        FORECASTED = "forecasted", "Forecasted"

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="grant_opportunities")
    funder = models.ForeignKey(
        Funder,
        on_delete=models.CASCADE,
        related_name="opportunities",
    )
    # Phase 2: optionally points at the canonical PlatformOpportunity row
    # so converting a discovered opportunity into a workspace
    # opportunity doesn't fork the upstream data.
    platform_opportunity = models.ForeignKey(
        "workspaces.PlatformOpportunity",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workspace_overlays",
    )
    title = models.CharField(max_length=512)
    summary = models.TextField(blank=True)
    source_url = models.URLField(blank=True)
    posted_at = models.DateField(null=True, blank=True)
    submission_deadline = models.DateField(null=True, blank=True)
    award_floor = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    award_ceiling = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    eligibility_summary = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=OpportunityStatus.choices, default=OpportunityStatus.OPEN)
    tags = models.JSONField(default=list, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="created_grant_opportunities"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-posted_at", "-created_at"]
        indexes = [
            models.Index(fields=["workspace", "status", "submission_deadline"], name="opportunity_ws_active_idx"),
            models.Index(fields=["funder", "status"], name="opportunity_funder_idx"),
        ]

    def __str__(self):
        return self.title


class GrantSnippet(models.Model):
    """Reusable boilerplate snippet for grant applications.

    Keyed by `{{key}}` for token-replacement in application drafts:
    mission, leadership_bios, prior_outcomes, etc. usage_count +
    last_used_at let the UI surface most-used snippets.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="grant_snippets")
    key = models.SlugField(max_length=64)
    label = models.CharField(max_length=255)
    content_md = models.TextField()
    last_used_at = models.DateTimeField(null=True, blank=True)
    usage_count = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="created_grant_snippets"
    )
    # Soft delete → recycle bin (Template Kernel lifecycle).
    is_deleted = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_used_at", "key"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "key"], name="snippet_ws_key_unique"),
        ]
        indexes = [
            models.Index(fields=["workspace", "usage_count"], name="snippet_ws_usage_idx"),
        ]

    def __str__(self):
        return f"{self.key} ({self.workspace_id})"


class ApplicationTemplate(models.Model):
    """Versioned JSON-Schema application form template.

    workspace nullable = platform-default template (seeded). funder
    nullable = generic template not tied to a specific funder. Schema
    is stored as JSON Schema so the frontend can render the form
    dynamically. In-flight drafts hold a `schema_version_id` referencing
    a specific version so a template update mid-cycle doesn't break
    existing drafts.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="application_templates",
    )
    funder = models.ForeignKey(
        Funder,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="application_templates",
    )
    name = models.CharField(max_length=255)
    version = models.PositiveIntegerField(default=1)
    schema = models.JSONField()
    is_active = models.BooleanField(default=True)
    # Soft delete → recycle bin (Template Kernel lifecycle). Distinct from
    # is_active (which toggles a version on/off without trashing it).
    is_deleted = models.BooleanField(default=False, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_application_templates",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "funder", "name", "version"],
                name="application_template_ws_funder_name_version_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "is_active"], name="application_template_ws_idx"),
            models.Index(fields=["funder", "is_active"], name="app_tmpl_funder_active_idx"),
        ]

    def __str__(self):
        return f"{self.name} v{self.version}"


# ============================================================================
# Grants Phase 2 — Platform-owned global discovery catalog + saved searches
# ----------------------------------------------------------------------------
# Platform tables are NOT workspace-scoped. They hold the canonical
# discovered-from-the-world catalog (Grants.gov first; ProPublica + IATI
# later behind the same GrantsDiscoveryPort). Workspace records
# (Funder / GrantOpportunity from Phase 1) keep their workspace_id and
# optionally point at a Platform row via a nullable FK — so a workspace's
# "Gates Foundation" record is independent but can be linked to the
# canonical PlatformFunder for cross-tenant funder history and graph
# queries.
#
# This pattern matches the Instrumentl + Fluxx Data Core insight noted in
# the benchmark research: the catalog is platform-owned; pipeline state is
# workspace-owned.
# ============================================================================


class PlatformFunder(models.Model):
    """Global funder catalog — one row per unique funder across the
    platform. Populated by ingest adapters (Grants.gov agencies first;
    later ProPublica EINs, IATI publishers, etc.). Used by:

    - The Discover page's funder filter dropdown.
    - WorkspaceFunder (Phase 1's `Funder`) overlay via
      `Funder.platform_funder_id` FK.
    - PlatformOpportunity to associate every opportunity with a funder.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    name = models.CharField(max_length=255)
    canonical_key = models.SlugField(max_length=255, unique=True)
    # `external_source` + `external_id` lets us track the origin record
    # (e.g. Grants.gov agency code or ProPublica EIN). Pair is unique.
    external_source = models.CharField(max_length=64, blank=True)
    external_id = models.CharField(max_length=255, blank=True)
    website = models.URLField(blank=True)
    description = models.TextField(blank=True)
    tags = models.JSONField(default=list, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["external_source", "external_id"],
                name="platform_funder_external_unique",
                condition=models.Q(external_id__gt=""),
            ),
        ]
        indexes = [
            models.Index(fields=["name"], name="platform_funder_name_idx"),
            models.Index(
                fields=["external_source"],
                name="platform_funder_source_idx",
            ),
        ]

    def __str__(self):
        return self.name


class PlatformOpportunity(models.Model):
    """Global opportunity catalog. Source-of-truth for what Grants.gov
    (and future adapters) advertise. Workspace overlays (Phase 1's
    `GrantOpportunity`) point here via a nullable FK so a workspace
    record can "save" or "tag" a global opportunity without forking the
    canonical data.
    """

    class OpportunityStatus(models.TextChoices):
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"
        FORECASTED = "forecasted", "Forecasted"
        ARCHIVED = "archived", "Archived"

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    funder = models.ForeignKey(
        PlatformFunder,
        on_delete=models.CASCADE,
        related_name="opportunities",
    )
    # external_source = adapter name ("grants_gov", "propublica", "iati").
    # external_id = adapter's stable identifier (Grants.gov
    # opportunityNumber+agencyCode, ProPublica EIN, IATI activity id).
    external_source = models.CharField(max_length=64)
    external_id = models.CharField(max_length=255)
    title = models.CharField(max_length=512)
    summary = models.TextField(blank=True)
    source_url = models.URLField(blank=True)
    posted_at = models.DateField(null=True, blank=True)
    submission_deadline = models.DateField(null=True, blank=True)
    award_floor = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    award_ceiling = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    eligibility_summary = models.TextField(blank=True)
    eligibility_schema = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20,
        choices=OpportunityStatus.choices,
        default=OpportunityStatus.OPEN,
    )
    tags = models.JSONField(default=list, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-posted_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["external_source", "external_id"],
                name="platform_opportunity_external_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=["status", "submission_deadline"],
                name="platform_opp_active_idx",
            ),
            models.Index(
                fields=["funder", "status"],
                name="platform_opp_funder_idx",
            ),
            models.Index(
                fields=["external_source", "last_seen_at"],
                name="platform_opp_source_idx",
            ),
        ]

    def __str__(self):
        return f"{self.external_source}:{self.external_id} — {self.title[:60]}"


class SavedGrantSearch(models.Model):
    """Workspace's saved Discover search. Phase 2.5 schedules a daily
    task that re-evaluates each saved search and emits a
    GrantOpportunityMatchFinding AI action per new match.
    """

    class NotifyVia(models.TextChoices):
        NONE = "none", "None"
        WEEKLY_DIGEST = "weekly_digest", "Weekly digest"
        FOR_YOU_TODAY = "for_you_today", "For-you-today card"

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="saved_grant_searches",
    )
    name = models.CharField(max_length=255)
    filters = models.JSONField(default=dict)
    notify_via = models.CharField(
        max_length=20,
        choices=NotifyVia.choices,
        default=NotifyVia.FOR_YOU_TODAY,
    )
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_match_count = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="created_grant_searches",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["workspace", "notify_via"],
                name="saved_search_ws_idx",
            ),
        ]

    def __str__(self):
        return f"{self.workspace_id}:{self.name}"


# ============================================================================
# Grants Phase 4 — Reporting (ReportingPeriod, ReportTemplate, Report,
# ReportRevision). Period-lock invariant: once a Report is filed, the
# ReportingPeriod flips to 'filed' and transactions inside the window
# get period_locked at the Transaction level (see migration 0011 in
# the transactions app).
# ============================================================================


class ReportingPeriod(models.Model):
    """A reporting window for a grant — e.g. Q3 2026, FY2026 H2."""

    class Status(models.TextChoices):
        UPCOMING = "upcoming", "Upcoming"
        IN_PROGRESS = "in_progress", "In progress"
        FILED = "filed", "Filed"

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    grant = models.ForeignKey(
        Grant,
        on_delete=models.CASCADE,
        related_name="reporting_periods",
    )
    label = models.CharField(max_length=128)
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.UPCOMING,
    )
    filed_at = models.DateTimeField(null=True, blank=True)
    filed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="filed_reporting_periods",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["period_start"]
        constraints = [
            models.UniqueConstraint(
                fields=["grant", "label"],
                name="reporting_period_grant_label_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=["grant", "status"],
                name="reporting_period_status_idx",
            ),
            models.Index(
                fields=["period_start", "period_end"],
                name="reporting_period_window_idx",
            ),
        ]

    def __str__(self):
        return f"{self.label} ({self.period_start}–{self.period_end})"


class ReportTemplate(models.Model):
    """Versioned JSON Schema for a funder report. Phase 4.2 saves
    Report revisions against a specific template_id so mid-cycle
    template changes don't break in-flight reports."""

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="report_templates",
    )
    funder = models.ForeignKey(
        Funder,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="report_templates",
    )
    name = models.CharField(max_length=255)
    version = models.PositiveIntegerField(default=1)
    schema = models.JSONField()
    is_active = models.BooleanField(default=True)
    # Soft delete → recycle bin (Template Kernel lifecycle).
    is_deleted = models.BooleanField(default=False, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_report_templates",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "funder", "name", "version"],
                name="report_template_ws_funder_name_version_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=["workspace", "is_active"],
                name="report_template_ws_idx",
            ),
            models.Index(
                fields=["funder", "is_active"],
                name="report_template_funder_idx",
            ),
        ]

    def __str__(self):
        return f"{self.name} v{self.version}"


class Report(models.Model):
    """A single funder report for (grant, requirement, period). The
    Report row is the long-lived envelope; the content lives in
    versioned ReportRevision rows (append-only)."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        AMENDED = "amended", "Amended"

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    grant = models.ForeignKey(
        Grant,
        on_delete=models.CASCADE,
        related_name="reports",
    )
    requirement = models.ForeignKey(
        AwardRequirement,
        on_delete=models.CASCADE,
        related_name="reports",
        null=True,
        blank=True,
    )
    reporting_period = models.ForeignKey(
        ReportingPeriod,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports",
    )
    template = models.ForeignKey(
        ReportTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submitted_grant_reports",
    )
    submitted_revision = models.ForeignKey(
        "ReportRevision",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submitted_for_reports",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["grant", "status"],
                name="report_grant_status_idx",
            ),
            models.Index(
                fields=["reporting_period"],
                name="report_period_idx",
            ),
        ]

    def __str__(self):
        return f"Report({self.grant_id}, {self.status})"


class ReportRevision(models.Model):
    """Append-only versioned content for a Report. Every save writes a
    new row referencing parent_revision_id."""

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    report = models.ForeignKey(
        Report,
        on_delete=models.CASCADE,
        related_name="revisions",
    )
    version = models.PositiveIntegerField()
    parent_revision = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="child_revisions",
    )
    schema_version_id = models.UUIDField(null=True, blank=True)
    fields = models.JSONField(default=dict, blank=True)
    narrative_md = models.TextField(blank=True)
    financial_summary = models.JSONField(default=dict, blank=True)
    authored_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="authored_report_revisions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version"]
        unique_together = [("report", "version")]
        indexes = [
            models.Index(
                fields=["report", "version"],
                name="report_revision_latest_idx",
            ),
        ]

    def __str__(self):
        return f"{self.report_id}:rev@v{self.version}"


# ============================================================================
# Workspace Groups & Permissions
# ============================================================================


class WorkspaceGroup(models.Model):
    """Permission group within a workspace."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey("workspaces.Workspace", on_delete=models.CASCADE, related_name="groups")
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="WorkspaceGroupMembership",
        through_fields=("group", "user"),
        related_name="workspace_groups",
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="created_groups"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("workspace", "name")
        ordering = ("name",)
        db_table = "workspace_groups"

    def __str__(self):
        return f"{self.workspace_id}:{self.name}"


class WorkspaceGroupMembership(models.Model):
    """Through model for group membership."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group = models.ForeignKey(WorkspaceGroup, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="group_memberships")
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("group", "user")
        db_table = "workspace_group_memberships"

    def __str__(self):
        return f"{self.group_id}:{self.user_id}"


class WorkspaceRole(models.Model):
    """Named bundle of capabilities that can be assigned to a workspace membership.

    A role is the RBAC enforcement unit — a user's permissions in a workspace
    are their role's ``permissions`` list (a set of keys drawn from
    ``components.workspace.api.groups_controller.VALID_PERMISSION_KEYS``).

    Two flavours:

    - **System roles** (``is_system=True``, ``workspace=None``) are seeded from
      the ``seed_system_roles`` data migration and shared across every
      workspace. They are the canonical templates (Owner, Admin, Campaign
      Manager, Finance, Auditor, Viewer, etc.) and cannot be edited or
      deleted through the API.
    - **Workspace-scoped roles** (``is_system=False``, ``workspace`` set) are
      created by workspace admins for capability bundles the system defaults
      don't cover. Slug is unique per workspace; system slugs (e.g. ``admin``)
      are reserved and cannot be reused as a custom-role slug.

    See ADR 0002 for the persona/role split — persona drives UX routing, role
    drives RBAC. This model makes ``role`` a first-class capability-backed
    entity instead of the current free-string on ``WorkspaceMembership.role``.
    The legacy string field stays in place during the migration phases; it
    will be removed once every reader and writer has moved to the FK.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="custom_roles",
        null=True,
        blank=True,
        help_text="Null for system roles (shared across all workspaces); set for workspace-scoped custom roles.",
    )
    slug = models.SlugField(
        max_length=100,
        help_text="Stable identifier used for lookups. Unique per workspace (or globally for system roles).",
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    permissions = models.JSONField(
        default=list,
        help_text="List of permission keys from VALID_PERMISSION_KEYS.",
    )
    is_system = models.BooleanField(
        default=False,
        help_text="Seeded from code — read-only from the API, never deleted.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "workspace_roles"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "slug"],
                name="uniq_workspace_role_slug",
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "is_system"], name="ws_role_ws_system_idx"),
            models.Index(fields=["slug", "is_system"], name="ws_role_slug_system_idx"),
        ]
        ordering = ["workspace_id", "name"]

    def __str__(self):
        scope = "system" if self.is_system else f"ws={self.workspace_id}"
        return f"{scope}:{self.slug}"


class WorkspacePermissionGrant(models.Model):
    """Permission granted to a user or group within a workspace."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey("workspaces.Workspace", on_delete=models.CASCADE, related_name="permission_grants")
    permission_key = models.CharField(max_length=100)
    # Either user OR group — one must be set
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name="permission_grants"
    )
    group = models.ForeignKey(
        WorkspaceGroup, on_delete=models.CASCADE, null=True, blank=True, related_name="permission_grants"
    )
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "workspace_permission_grants"
        indexes = [
            models.Index(fields=["workspace", "permission_key"], name="ws_perm_grant_key_idx"),
            models.Index(fields=["workspace", "user"], name="ws_perm_grant_user_idx"),
            models.Index(fields=["workspace", "group"], name="ws_perm_grant_group_idx"),
        ]

    def __str__(self):
        target = f"user={self.user_id}" if self.user_id else f"group={self.group_id}"
        return f"{self.workspace_id}:{self.permission_key}:{target}"


class SupportImpersonationSession(models.Model):
    """Time-bound session granting a platform admin the chosen
    persona/role on a target workspace, for support troubleshooting.

    Lifecycle
    ---------
    On start the use case creates a ``WorkspaceMembership`` row with
    ``is_impersonation=True`` and stores its id on
    ``synthetic_membership``. Permission helpers see the new row and
    grant the chosen role/persona to the actor for the session
    duration. On end (explicit or automatic), the synthetic membership
    is deleted and ``ended_at`` is stamped.

    Safety
    ------
    * Sessions are gated by ``feature.support_impersonation`` (USER
      scope). Invisible to non-platform-admins.
    * 30-minute hard expiry. A Celery task expires stale sessions and
      cleans up their synthetic memberships.
    * Money / payment endpoints refuse mutation while the actor has
      any active impersonation membership on the workspace — see
      ``components.payments.api.billing_support``.
    * Member-list serializers filter ``is_impersonation=False`` so the
      impersonation row never appears in team rosters.

    See the project's ``architecture-manifesto`` and
    ``persistence-and-orm`` rules for placement constraints; this
    model is owned by the workspaces context because the synthetic
    membership it manages is a ``WorkspaceMembership`` row.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="support_impersonation_sessions_started",
        help_text="Platform admin running the impersonation.",
    )
    target_workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="support_impersonation_sessions",
    )
    target_persona = models.CharField(max_length=20)
    target_role = models.CharField(max_length=20)
    reason = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    synthetic_membership = models.OneToOneField(
        WorkspaceMembership,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="impersonation_session",
        help_text=(
            "The ``is_impersonation=True`` WorkspaceMembership row "
            "this session created. Set null after ``ended_at`` is "
            "stamped and the synthetic row is deleted."
        ),
    )

    class Meta:
        ordering = ["-started_at"]
        indexes = [
            models.Index(
                fields=["actor", "ended_at", "expires_at"],
                name="impersonation_active_idx",
            ),
            models.Index(
                fields=["target_workspace", "ended_at", "expires_at"],
                name="impersonation_workspace_idx",
            ),
        ]

    def is_active_at(self, now) -> bool:
        if self.ended_at is not None:
            return False
        return now < self.expires_at

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"impersonation actor={self.actor_id} "
            f"workspace={self.target_workspace_id} "
            f"persona={self.target_persona} role={self.target_role}"
        )


# SaaS billing ledger models (PaymentProvider / WorkspacePaymentMethod /
# PaymentPlan / PaymentEvent / PaymentOrder / PaymentTransaction / …) live in
# the workspaces.payments submodule but belong to the `workspaces` app. Import
# the module here so Django registers them under this app (their migrations live
# in workspaces/migrations). See api/settings INSTALLED_APPS note.
from infrastructure.persistence.workspaces.payments import models as _payment_models  # noqa: E402,F401
