"""
Agent Models

Database models for persisting AI agent state and configuration.
"""

import uuid

from django.contrib.auth import get_user_model
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

User = get_user_model()

# Import Workspace model
try:
    from infrastructure.persistence.workspaces.models import Workspace
except ImportError:
    Workspace = None


class AgentType(models.Model):
    """Catalog of available agent implementations"""

    slug = models.SlugField(max_length=100, unique=True)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    class_path = models.CharField(max_length=255)
    default_config = models.JSONField(default=dict, blank=True)
    aliases = models.JSONField(default=list, blank=True)
    required_actions = models.JSONField(default=list, blank=True)
    allowed_tools = models.JSONField(default=list, blank=True)
    department_tags = models.JSONField(default=list, blank=True)
    default_run_config = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.slug})"


class WorkspaceAgentType(models.Model):
    """Per-workspace enablement of agent types."""

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="agent_entitlements")
    agent_type = models.ForeignKey(AgentType, on_delete=models.CASCADE, related_name="workspace_entitlements")
    is_enabled = models.BooleanField(default=False)
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agent_entitlement_updates",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("workspace", "agent_type")
        indexes = [
            models.Index(fields=["workspace", "is_enabled"], name="ai_workspace_agent_enabled_idx"),
            models.Index(fields=["agent_type", "is_enabled"], name="ai_agent_type_enabled_idx"),
        ]

    def __str__(self):
        status = "enabled" if self.is_enabled else "disabled"
        return f"{self.workspace_id}::{self.agent_type.slug} ({status})"


class Agent(models.Model):
    """Persistent storage for AI agents"""

    STATUS_CHOICES = [
        ("active", "Active"),
        ("paused", "Paused"),
        ("completed", "Completed"),
        ("error", "Error"),
    ]

    agent_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agent_type = models.CharField(max_length=100)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="ai_agents")
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="ai_agents", null=True, blank=True)
    department = models.ForeignKey(
        "team.Team",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="department_agents",
    )

    # Agent state
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    config = models.JSONField(default=dict, blank=True)

    # Execution tracking
    last_query = models.TextField(blank=True)
    last_result = models.TextField(blank=True)
    execution_count = models.PositiveIntegerField(default=0)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_executed = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        permissions = (
            ("ai_manage", "Can manage AI agents (settings, disable, share, customization)"),
            ("ai_execute", "Can execute/pause/resume AI agents"),
            ("ai_engage", "Can engage with AI agents (follow/like/rate/comment)"),
        )
        indexes = [
            models.Index(fields=["user", "workspace"]),
            models.Index(fields=["agent_type", "status"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.agent_type} - {self.user.username} ({self.status})"

    @property
    def user_id_str(self):
        return str(self.user.id)

    def to_dict(self):
        """Convert to dictionary format expected by the factory"""
        return {
            "agent_id": str(self.agent_id),
            "agent_type": self.agent_type,
            "user_id": str(self.user.id),
            "workspace_id": str(self.workspace.id) if self.workspace else None,
            "department_id": str(self.department_id) if self.department_id else None,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_executed": self.last_executed.isoformat() if self.last_executed else None,
            "execution_count": self.execution_count,
            "last_query": self.last_query,
            "last_result": self.last_result,
            "config": self.config,
        }


class AgentExecution(models.Model):
    """Track individual agent executions for history and debugging"""

    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_RUNNING, "Running"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
    ]

    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name="executions")
    query = models.TextField()
    result = models.TextField(blank=True)
    success = models.BooleanField(default=True)
    error_message = models.TextField(blank=True)
    execution_time_ms = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    task_id = models.CharField(max_length=255, blank=True)
    progress = models.PositiveSmallIntegerField(default=0)
    state = models.JSONField(default=dict, blank=True)
    triggered_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="ai_agent_executions"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["agent", "created_at"]),
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["success", "created_at"]),
            models.Index(fields=["task_id"]),
            models.Index(fields=["triggered_by"], name="ai_execution_trigger_idx"),
        ]

    def __str__(self):
        status_icon = "✓" if self.success else "✗"
        return f"{status_icon} {self.get_status_display()} {self.agent.agent_type} - {self.query[:50]}..."


class AgentProfile(models.Model):
    """User-facing profile and settings for an Agent."""

    VISIBILITY_SEED_ONLY = "workspace_only"
    VISIBILITY_SHARED_LINK = "shared_link"
    VISIBILITY_CHOICES = [
        (VISIBILITY_SEED_ONLY, "Workspace only"),
        (VISIBILITY_SHARED_LINK, "Shared link"),
    ]

    agent = models.OneToOneField(Agent, on_delete=models.CASCADE, related_name="profile")
    display_name = models.CharField(max_length=150, blank=True)
    summary = models.TextField(blank=True)
    avatar_url = models.URLField(blank=True)
    tags = models.JSONField(default=list, blank=True)
    visibility = models.CharField(max_length=20, choices=VISIBILITY_CHOICES, default=VISIBILITY_SEED_ONLY)
    allow_followers = models.BooleanField(default=True)
    allow_ratings = models.BooleanField(default=True)
    allow_comments = models.BooleanField(default=True)
    is_disabled = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["agent"]

    def __str__(self):
        return self.display_name or f"Profile for {self.agent_id}"


class AgentFollow(models.Model):
    """Follow relationship between a user and an agent."""

    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name="follows")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="agent_follows")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("agent", "user")
        indexes = [
            models.Index(fields=["agent", "user"]),
            models.Index(fields=["created_at"]),
        ]


class AgentReaction(models.Model):
    """Reaction (like) on an agent."""

    REACTION_LIKE = "like"
    REACTION_CHOICES = [
        (REACTION_LIKE, "Like"),
    ]

    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name="reactions")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="agent_reactions")
    reaction_type = models.CharField(max_length=30, choices=REACTION_CHOICES, default=REACTION_LIKE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("agent", "user", "reaction_type")
        indexes = [
            models.Index(fields=["agent", "user"]),
            models.Index(fields=["reaction_type"]),
            models.Index(fields=["created_at"]),
        ]


class AgentRating(models.Model):
    """User rating for an agent."""

    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name="ratings")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="agent_ratings")
    score = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("agent", "user")
        indexes = [
            models.Index(fields=["agent", "user"]),
            models.Index(fields=["created_at"]),
        ]


class AgentComment(models.Model):
    """Threaded comment on an agent."""

    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name="comments")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="agent_comments")
    body = models.TextField()
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="replies",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["agent", "user"]),
            models.Index(fields=["created_at"]),
        ]

    @property
    def depth(self) -> int:
        current = self
        level = 0
        while current.parent_id:
            level += 1
            current = current.parent
        return level


class AgentShare(models.Model):
    """Shareable link to an agent."""

    SCOPE_WORKSPACE_ONLY = "workspace_only"
    SCOPE_SEED_ONLY = SCOPE_WORKSPACE_ONLY
    SCOPE_PUBLIC = "public"
    SCOPE_CHOICES = [
        (SCOPE_WORKSPACE_ONLY, "Workspace only"),
        (SCOPE_PUBLIC, "Public"),
    ]

    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name="shares")
    share_token = models.CharField(max_length=64, unique=True)
    scope = models.CharField(max_length=20, choices=SCOPE_CHOICES, default=SCOPE_WORKSPACE_ONLY)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["share_token"]),
            models.Index(fields=["agent", "created_at"]),
        ]

    def is_active(self) -> bool:
        if self.expires_at and self.expires_at <= timezone.now():
            return False
        return True


class DeepRun(models.Model):
    """Persist deep-agent run/checkpoint state."""

    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_RUNNING, "Running"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
    ]

    thread_id = models.CharField(max_length=255, unique=True)
    plan_id = models.CharField(max_length=255)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="deep_runs")
    workspace = models.ForeignKey(Workspace, on_delete=models.SET_NULL, null=True, blank=True, related_name="deep_runs")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    state = models.JSONField(default=dict, blank=True)
    checkpoints = models.JSONField(default=dict, blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["thread_id"]),
            models.Index(fields=["plan_id"]),
            models.Index(fields=["status", "updated_at"]),
        ]

    def __str__(self):
        return f"{self.thread_id} ({self.status})"


class DeepRunLog(models.Model):
    """Event log entries for deep-agent runs.

    Includes optional LLM-call observability fields (system_prompt,
    user_prompt, llm_response, model_used, prompt_tokens,
    completion_tokens, latency_ms, cost_usd) so prompt-engineering
    iteration has the data it needs. The fields are populated by
    instrumented call sites such as ``llm_planner.plan_with_llm``;
    event-only rows leave them blank.
    """

    deep_run = models.ForeignKey(DeepRun, on_delete=models.CASCADE, related_name="logs")
    event_type = models.CharField(max_length=100)
    status = models.CharField(max_length=50, blank=True)
    agent_type = models.CharField(max_length=100, blank=True)
    tool_name = models.CharField(max_length=150, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    # ── LLM observability (populated for ``llm_call`` events) ────────
    system_prompt = models.TextField(blank=True, default="")
    user_prompt = models.TextField(blank=True, default="")
    llm_response = models.TextField(blank=True, default="")
    model_used = models.CharField(max_length=100, blank=True, default="")
    prompt_tokens = models.PositiveIntegerField(null=True, blank=True)
    completion_tokens = models.PositiveIntegerField(null=True, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["deep_run", "created_at"], name="deep_run_log_run_idx"),
            models.Index(fields=["event_type", "created_at"], name="deep_run_log_evt_idx"),
            models.Index(fields=["agent_type", "created_at"], name="deep_run_log_agent_idx"),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.event_type} ({self.deep_run_id})"


class AiActionDailyRollup(models.Model):
    """Per-workspace, per-day rollup of AI action telemetry.

    Recomputed (not incremented) by the ``ai.rollup_ai_action_daily``
    Celery beat task from raw ``DeepRun`` / ``DeepRunLog`` rows, so
    re-runs are idempotent and late-arriving rows converge on the next
    pass — same contract as the AI-quality rollups in
    ``infrastructure.persistence.ai.aggregations.models``.

    This is the read model behind the posture-dashboard governance
    charts (cost/day, runs/day): the dashboard endpoint reads ONLY these
    rollup rows for its daily series — never the raw log — per the
    performance rule that heavy aggregation runs in the background and
    API reads stay indexed and O(window). It complements (does not
    replace) ``AIWorkspaceDailyMetric``: that rollup carries the quality
    lens (feedback, assistant messages); this one carries the action
    ledger the posture surface renders (tool calls, tokens, spend).
    """

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="ai_action_daily_rollups",
    )
    date = models.DateField()

    runs_total = models.PositiveIntegerField(default=0)
    runs_completed = models.PositiveIntegerField(default=0)
    runs_failed = models.PositiveIntegerField(default=0)
    tool_calls = models.PositiveIntegerField(default=0)
    tokens_input = models.PositiveBigIntegerField(default=0)
    tokens_output = models.PositiveBigIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=12, decimal_places=6, default=0)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "date"],
                name="uniq_ws_date_ai_action_rollup",
            ),
        ]
        indexes = [
            # The dashboard window query: workspace + date range.
            models.Index(fields=["workspace", "-date"], name="ai_action_rollup_ws_date_idx"),
        ]
        ordering = ["-date"]

    def __str__(self):
        return f"{self.workspace_id} · {self.date} · runs={self.runs_total} · cost={self.cost_usd}"


class DeepArtifact(models.Model):
    """Artifact references produced during deep-agent runs."""

    deep_run = models.ForeignKey(DeepRun, on_delete=models.CASCADE, related_name="artifacts")
    task_id = models.CharField(max_length=255, blank=True)
    uri = models.CharField(max_length=512)
    summary = models.TextField(blank=True)
    data = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["deep_run", "task_id"]),
        ]

    def __str__(self):
        return f"{self.uri} ({self.task_id})"
