from django.conf import settings
from django.db import models

# Models

# NOTE: the subscription-tier ``Plan`` model was relocated to the
# ``subscription`` persistence app (its proper bounded-context home) — see
# infrastructure/persistence/subscription/models.py and
# docs/plans/PREMIUM_FEATURE_TIERS_PLAN.md. ``Team.plan`` / ``Workspace.plan``
# reference it by string (``"subscription.Plan"``). The physical table is
# unchanged (``team_plan``) — it was a pure state move.


class Team(models.Model):
    #
    # Status

    ACTIVE = "active"
    DELETED = "deleted"

    CHOICES_STATUS = ((ACTIVE, "Active"), (DELETED, "Deleted"))

    #
    # Plan status

    PLAN_ACTIVE = "active"
    PLAN_CANCELED = "canceled"

    CHOICES_PLAN_STATUS = ((PLAN_ACTIVE, "Active"), (PLAN_CANCELED, "Canceled"))

    #
    # Team privacy
    PUBLIC = "public"
    PRIVATE = "private"

    PRIVACY_CHOICES = (
        (PUBLIC, "public"),
        (PRIVATE, "private"),
    )

    class Kind(models.TextChoices):
        DEPARTMENT = "department", "Department"
        PROJECT_TEAM = "project_team", "Project Team"
        AI_AGENTS = "ai_agents", "AI Agents"

    #
    # Fields
    workspace = models.ForeignKey("workspaces.Workspace", related_name="workspace_teams", on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="teams")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="created_teams", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.DEPARTMENT, db_index=True)
    status = models.CharField(max_length=10, choices=CHOICES_STATUS, default=ACTIVE)
    privacy = models.CharField(max_length=8, choices=PRIVACY_CHOICES, default=PRIVATE)
    # The auto-created default/"home" team for a workspace (one per workspace).
    # Bootstrap sets this True so "the default team" is identifiable without
    # fragile title string-matching ("Contributors"/"Family"/"General"/"Default
    # Team"). The duplicate-default dedupe migration relies on it.
    is_default = models.BooleanField(default=False, db_index=True)
    # Org subscription tier. Nullable so a team can exist on the freemium default
    # before a paid plan is assigned (SET_NULL preserves the team if a plan is
    # deleted). SaaS billing (`subscription` context) owns Plan/pricing.
    plan = models.ForeignKey(
        "subscription.Plan", related_name="teams", on_delete=models.SET_NULL, null=True, blank=True
    )
    plan_end_date = models.DateTimeField(blank=True, null=True)
    plan_status = models.CharField(max_length=20, choices=CHOICES_PLAN_STATUS, default=PLAN_ACTIVE)
    stripe_customer_id = models.CharField(max_length=255, blank=True, null=True)
    stripe_subscription_id = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title


class Invitation(models.Model):
    """Workspace invitation — covers both team-attached and team-detached
    invites (sponsors, auditors, etc.).

    See ADR 0002. ``persona`` selects which dashboard the invitee lands on
    and which enrollment branch the accept use case takes:

    - team-attached personas (contributor, volunteer) → ``team`` is set,
      accept enrolls them in the team
    - team-detached personas (sponsor, auditor, board_member) → ``team`` is
      null, accept only writes the WorkspaceMembership
    """

    INVITED = "invited"
    ACCEPTED = "accepted"
    EXPIRED = "expired"
    REVOKED = "revoked"

    CHOICES_STATUS = (
        (INVITED, "Invited"),
        (ACCEPTED, "Accepted"),
        (EXPIRED, "Expired"),
        (REVOKED, "Revoked"),
    )

    PERSONA_CHOICES = (
        ("admin", "Admin"),
        ("contributor", "Contributor"),
        ("sponsor", "Sponsor"),
        ("volunteer", "Volunteer"),
        ("auditor", "Auditor"),
        ("board_member", "Board Member"),
    )

    workspace = models.ForeignKey("workspaces.Workspace", on_delete=models.CASCADE)
    team = models.ForeignKey(
        Team,
        related_name="invitations",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="Required for team-attached personas; null for sponsor/auditor/board_member.",
    )
    email = models.EmailField()
    # Legacy short code retained for backward compatibility with the team
    # invite UI; new invites use the cryptographic ``token`` below for the
    # magic-link accept flow.
    code = models.CharField(max_length=20, blank=True)
    token = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text="Single-use magic-link token. Hex-encoded 32-byte secret.",
    )
    persona = models.CharField(
        max_length=20,
        choices=PERSONA_CHOICES,
        default="contributor",
        help_text="Persona the invitee will receive on accept. See ADR 0002.",
    )
    role = models.CharField(
        max_length=20,
        default="member",
        help_text="WorkspaceMembership.role to grant on accept (RBAC tier).",
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workspace_invitations_sent",
    )
    # Optional permission groups the invitee should be enrolled into on
    # accept. This is invitation-scoped state (the inviter's intent for
    # this specific invite), not user-scoped, so it lives on Invitation.
    # On accept, the AcceptWorkspaceInviteUseCase reads this list and
    # creates WorkspaceGroupMembership rows for each group.
    permission_group_ids = models.JSONField(
        default=list,
        blank=True,
        help_text="UUIDs of WorkspaceGroups to enroll the invitee into when the invitation is accepted.",
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=CHOICES_STATUS, default=INVITED)
    date_sent = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return self.email


class TeamMembership(models.Model):
    """Role-aware membership for users within a team."""

    class Role(models.TextChoices):
        LEAD = "lead", "Lead"
        EDITOR = "editor", "Editor"
        VIEWER = "viewer", "Viewer"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"

    team = models.ForeignKey("Team", on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="team_memberships")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.EDITOR)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "user"], name="uniq_team_membership"),
        ]
        indexes = [
            models.Index(fields=["team", "role"], name="team_membership_role_idx"),
            models.Index(fields=["user", "role"], name="team_membership_user_role_idx"),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.team_id}:{self.user_id}:{self.role}"
