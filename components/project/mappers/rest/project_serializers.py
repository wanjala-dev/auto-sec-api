from django.utils import timezone
from drf_writable_nested.serializers import WritableNestedModelSerializer
from rest_framework import serializers

from components.identity.mappers.rest.identity_serializers import LeanUserSerializer
from components.workspace.mappers.rest.workspace_serializers import WorkspaceContributionsMeansSerializer
from infrastructure.persistence.project.models import (
    Column,
    Project,
    ProjectEntry,
    ProjectMilestone,
    ProjectUpdate,
    Tag,
    Task,
    TaskComment,
)
from infrastructure.persistence.team.models import Team
from infrastructure.persistence.users.models import CustomUser
from infrastructure.persistence.workspaces.models import ContributionMeans, Grant, Workspace


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ["id", "name"]


class TaskCommentSerializer(serializers.ModelSerializer):
    author = LeanUserSerializer(read_only=True)
    likes = LeanUserSerializer(many=True, read_only=True)
    dislikes = LeanUserSerializer(many=True, read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    parent = serializers.PrimaryKeyRelatedField(queryset=TaskComment.objects.all(), allow_null=True, required=False)
    recipients = serializers.SerializerMethodField()
    task_id = serializers.IntegerField(source="task.id", read_only=True)
    is_parent = serializers.SerializerMethodField()

    class Meta:
        model = TaskComment
        fields = [
            "id",
            "comment",
            "created_on",
            "author",
            "task_id",
            "parent",
            "recipients",
            "likes",
            "dislikes",
            "tags",
            "is_parent",
        ]
        read_only_fields = [
            "id",
            "created_on",
            "author",
            "task_id",
            "recipients",
            "likes",
            "dislikes",
            "tags",
            "is_parent",
        ]

    def get_recipients(self, obj):
        replies = obj.replies.order_by("-created_on").all()
        if not replies:
            return []
        serializer = TaskCommentSerializer(
            replies,
            many=True,
            context=self.context,
        )
        return serializer.data

    get_children = get_recipients

    def get_is_parent(self, obj):
        return obj.is_parent

    def validate_parent(self, value):
        task = self.context.get("task")
        if value and task and value.task_id != task.id:
            raise serializers.ValidationError("Parent comment must belong to the same task.")
        return value


class ProjectSerializer(serializers.ModelSerializer):
    team = serializers.SlugRelatedField(queryset=Team.objects.all(), slug_field="id")
    created_by = serializers.SlugRelatedField(queryset=CustomUser.objects.all(), slug_field="id")
    updates = serializers.PrimaryKeyRelatedField(
        queryset=ProjectUpdate.objects.all(), many=True, required=False, allow_null=True
    )
    milestones = serializers.PrimaryKeyRelatedField(
        queryset=ProjectMilestone.objects.all(), many=True, required=False, allow_null=True
    )
    lead = serializers.SlugRelatedField(
        queryset=CustomUser.objects.all(), slug_field="id", required=False, allow_null=True
    )
    contribution_means = serializers.PrimaryKeyRelatedField(
        queryset=ContributionMeans.objects.all(), many=True, required=False, allow_null=True
    )

    class Meta:
        model = Project
        fields = [
            "team",
            "created_by",
            "title",
            "created_at",
            "registered_time",
            "num_tasks_todo",
            "start_date",
            "end_date",
            "lead",
            "priority",
            "status",
            "resources",
            "updates",
            "description",
            "milestones",
            "bgColor",
            "public_goal_amount",
            "contribution_means",
            "board_column",
        ]
        read_only_fields = [
            "team",
            "created_by",
            "created_at",
        ]
        extra_kwargs = {
            "start_date": {"required": False, "allow_null": True},
            "end_date": {"required": False, "allow_null": True},
            "resources": {"required": False, "allow_null": True},
            "description": {"required": False, "allow_null": True},
            "bgColor": {"required": False, "allow_null": True},
            "public_goal_amount": {"required": False, "allow_null": True},
            "priority": {"required": False},
            "status": {"required": False},
        }

    def update(self, instance, validated_data):
        updates_data = validated_data.pop("updates", None)
        milestones_data = validated_data.pop("milestones", None)
        contribution_means_data = validated_data.pop("contribution_means", None)

        instance = super().update(instance, validated_data)

        if updates_data is not None:
            instance.updates.set(updates_data)

        if milestones_data is not None:
            instance.milestones.set(milestones_data)

        if contribution_means_data is not None:
            instance.contribution_means.set(contribution_means_data)

        return instance

    def create(self, validated_data):
        updates_data = validated_data.pop("updates", None)
        milestones_data = validated_data.pop("milestones", None)
        contribution_means_data = validated_data.pop("contribution_means", None)

        instance = super().create(validated_data)

        if updates_data is not None:
            instance.updates.set(updates_data)

        if milestones_data is not None:
            instance.milestones.set(milestones_data)

        if contribution_means_data is not None:
            instance.contribution_means.set(contribution_means_data)

        return instance


class ProjectUpdateSerializer(serializers.ModelSerializer):
    author = serializers.SlugRelatedField(queryset=CustomUser.objects.all(), slug_field="id")
    tags = serializers.PrimaryKeyRelatedField(many=True, queryset=Tag.objects.all(), required=False)

    class Meta:
        model = ProjectUpdate
        fields = [
            "id",
            "Update",
            "workspace",
            "Project",
            "created_on",
            "author",
            "likes",
            "privacy",
            "dislikes",
            "parent",
            "tags",
        ]
        read_only_fields = ["created_on", "author", "likes", "dislikes", "workspace"]


class ProjectMilestoneSerializer(serializers.ModelSerializer):
    creator = LeanUserSerializer(read_only=True)

    class Meta:
        model = ProjectMilestone
        fields = ["id", "name", "description", "target_date", "creator", "created_at"]
        read_only_fields = ["created_at", "creator"]


class ProjectTaskSummarySerializer(serializers.ModelSerializer):
    column = serializers.SerializerMethodField()
    assigned_to = serializers.SerializerMethodField()
    is_completed = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            "id",
            "title",
            "status",
            "order",
            "due_date",
            "is_completed",
            "column",
            "assigned_to",
        ]

    def get_column(self, obj):
        column = getattr(obj, "column", None)
        if not column:
            return None
        return {
            "id": column.id,
            "title": column.title,
        }

    def get_assigned_to(self, obj):
        users = getattr(obj, "_prefetched_objects_cache", {}).get("assigned_to")
        if users is None:
            users = obj.assigned_to.select_related("profile")

        result = []
        for user in users:
            profile = getattr(user, "profile", None)
            result.append(
                {
                    "id": str(user.id),
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "avatar": getattr(profile, "photo_url", None) if profile else None,
                }
            )
        return result

    def get_is_completed(self, obj):
        return obj.status == Task.DONE


class ProjectGetSerializer(serializers.ModelSerializer):
    team = serializers.SlugRelatedField(queryset=Team.objects.all(), slug_field="id")
    created_by = LeanUserSerializer(read_only=True)
    lead = LeanUserSerializer(read_only=True)
    priority = serializers.CharField(source="get_priority_display", read_only=True)
    status = serializers.CharField(source="get_status_display", read_only=True)
    start_date = serializers.DateField(read_only=True)
    end_date = serializers.DateField(read_only=True)
    milestones = ProjectMilestoneSerializer(many=True, read_only=True)
    updates = ProjectUpdateSerializer(many=True, read_only=True, source="project_updates")
    contribution_means = WorkspaceContributionsMeansSerializer(many=True, read_only=True)
    tasks = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = [
            "pk",
            "team",
            "created_by",
            "lead",
            "title",
            "start_date",
            "end_date",
            "created_at",
            "priority",
            "status",
            "registered_time",
            "resources",
            "description",
            "num_tasks_todo",
            "milestones",
            "updates",
            "bgColor",
            "public_goal_amount",
            "lead",
            "contribution_means",
            "tasks",
            "board_column",
        ]

    def get_tasks(self, obj):
        prefetched_tasks = getattr(obj, "_prefetched_objects_cache", {}).get("tasks")
        if prefetched_tasks is not None:
            tasks = prefetched_tasks
        else:
            tasks = (
                obj.tasks.select_related("column")
                .prefetch_related("assigned_to__profile", "assigned_to")
                .order_by("order", "created_at")
            )
        if isinstance(tasks, list):
            tasks = sorted(tasks, key=lambda task: (task.order, task.created_at))
        return ProjectTaskSummarySerializer(tasks, many=True).data


def project_get_serializer_for_version(version):
    """Project read serializer for the resolved API version.

    Used by the project controller AND by the cross-context workspace-detail
    controller, which embeds a project read in its payload.
    """
    return ProjectGetSerializer


class TaskSerializer(WritableNestedModelSerializer, serializers.ModelSerializer):
    team = serializers.SlugRelatedField(queryset=Team.objects.all(), slug_field="id")
    created_by = LeanUserSerializer()
    project = serializers.SlugRelatedField(
        queryset=Project.objects.all(), slug_field="id", allow_null=True, required=False
    )
    grant = serializers.SlugRelatedField(queryset=Grant.objects.all(), slug_field="id", allow_null=True, required=False)
    column = serializers.SlugRelatedField(queryset=Column.objects.all(), slug_field="id", allow_null=True)
    assigned_to = LeanUserSerializer(many=True, read_only=True)
    total_tracked_minutes = serializers.SerializerMethodField()
    total_tracked_display = serializers.SerializerMethodField()
    # AI-originated metadata — populated when this task was created by the
    # post-AIAction-to-Kanban handler. Lets the frontend render an agent
    # chip, domain label, impact indicator, and summary preview on the
    # card without a second round-trip.
    ai_action = serializers.SerializerMethodField()
    # Pending-sign-off reference — populated only when this task is a
    # materialized sign-off item (source_type == SIGN_OFF_SOURCE_TYPE),
    # carrying the artifact ref + risk band + receipts summary from
    # metadata.context. Its presence is the single signal the unified
    # AI-team board uses to render the review affordance (risk badge,
    # receipts, approve/reject) on the real TaskCard. None otherwise.
    sign_off = serializers.SerializerMethodField()
    # Log-Watch finding payload — populated only when this task was filed by the
    # log-error detector (source_type == "ai.log_watch"), carrying the flagged
    # service/level/severity + the LLM's grounded suggested fix from
    # metadata.log_watch. None otherwise, so ordinary tasks are unaffected.
    log_watch = serializers.SerializerMethodField()
    # Provenance trail for any agent-filed task — which detector filed it, which
    # specialist acted, and when. None for human-created tasks.
    provenance = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            "pk",
            "team",
            "workspace_id",
            "created_by",
            "updated_at",
            "title",
            "description",
            "created_at",
            "assigned_to",
            "project",
            "grant",
            "status",
            "column",
            "order",
            "due_date",
            "priority",
            "source_type",
            "requires_review",
            "total_tracked_minutes",
            "total_tracked_display",
            "ai_action",
            "sign_off",
            "log_watch",
            "provenance",
        ]
        read_only_fields = [
            "team",
            "workspace_id",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def to_representation(self, instance):
        # Override to include full project object in the response
        representation = super().to_representation(instance)
        if instance.project:
            representation["project"] = ProjectSerializer(instance.project).data
        return representation

    def _get_request_user(self):
        request = self.context.get("request")
        if request and hasattr(request, "user") and request.user.is_authenticated:
            return request.user
        user = self.context.get("user")
        if user and getattr(user, "is_authenticated", False):
            return user
        return None

    def get_ai_action(self, obj):
        """Expose AIAction metadata when this task was AI-originated.

        Returns None for human-created tasks. Payload is intentionally
        lean — just what the frontend needs to render chips (agent alias,
        domain label, detector, impact) and a summary preview. Full payload
        (the raw detector output) is available via a dedicated endpoint if
        ever needed; we don't ship it here to keep the board-list response
        small.
        """
        action = getattr(obj, "ai_action", None)
        if action is None:
            return None
        # Resolve the AI teammate alias so the chip reads "Zephyr" not
        # "Orchestrator Agent" / the raw agent_type slug.
        alias = None
        try:
            if action.workspace_id:
                from components.agents.infrastructure.services.agent_permissions_service import (
                    resolve_ai_teammate_alias,
                )

                alias = resolve_ai_teammate_alias(action.workspace)
        except Exception:
            alias = None
        return {
            "id": str(action.id),
            "agent_type": action.agent_type or "",
            "agent_alias": alias,
            "source_domain": action.source_domain or "",
            "detector": action.detector or "",
            "action_type": action.action_type or "",
            "summary": action.summary or "",
            "impact_score": action.impact_score or 0,
            "status": action.status or "",
            "created_at": action.created_at.isoformat() if action.created_at else None,
        }

    def get_sign_off(self, obj):
        """Expose the pending-sign-off reference for sign-off tasks.

        Sign-off items are materialized as Kanban tasks on the AI-team
        board (``source_type == SIGN_OFF_SOURCE_TYPE``) with the artifact
        ref + risk band + receipts summary stashed in
        ``metadata.context`` (see
        ``components/sign_off/application/services/materialize_signoff_tasks.py``).
        Surfacing a lean ``sign_off`` object here lets the unified AI-team
        board render the review affordance (risk badge, receipts,
        approve/reject) on the real TaskCard and fire the sign-off
        endpoints — without a second round-trip. Returns ``None`` for every
        non-sign-off task, so regular team tasks are unaffected.

        This mapper does NOT reach into sign-off domain logic; it only
        reshapes the generic ``metadata.context`` the materializer wrote.
        The source-type constant is imported lazily to avoid a module-load
        dependency (and any import cycle) on the sign-off context.
        """
        from components.sign_off.application.services.materialize_signoff_tasks import (
            SIGN_OFF_SOURCE_TYPE,
        )

        if (getattr(obj, "source_type", "") or "") != SIGN_OFF_SOURCE_TYPE:
            return None
        context = (getattr(obj, "metadata", None) or {}).get("context") or {}
        artifact_type = context.get("artifact_type")
        artifact_id = context.get("artifact_id")
        if not artifact_type or not artifact_id:
            return None
        return {
            "artifact_type": artifact_type,
            "artifact_id": str(artifact_id),
            "risk_band": context.get("risk_band") or "",
            "receipts_summary": context.get("receipts_summary") or {},
        }

    def get_log_watch(self, obj):
        """Expose the Log-Watch evidence-contract for a detector-filed task.

        Returns ``None`` for every non-log-watch task. For a log-watch finding,
        surfaces the evidence-based contract (``LogWatchErrorDetector`` writes it
        as the finding ``payload`` via ``persist_finding_as_task`` →
        ``metadata.payload``; the triage worker later fills probable_cause +
        suggested_fix). Carries the SOC-trustable fields: signal, service,
        level, severity, confidence, evidence[], blast_radius, plus the triage
        outputs likely_cause / probable_cause / suggested_fix. Mechanical
        reshape — no domain logic. Reads ``metadata.log_watch`` first for
        back-compat, then ``metadata.payload``.
        """
        # Both detector kinds share the evidence-contract payload shape, so ONE
        # card renders both — an error finding (triage agent fills the fix) and
        # an optimization finding (optimization agent fills the recommendation).
        if (getattr(obj, "source_type", "") or "") not in ("ai.log_watch", "ai.log_optimization"):
            return None
        meta = getattr(obj, "metadata", None) or {}
        payload = meta.get("log_watch") or meta.get("payload")
        if not payload:
            return None
        triage = meta.get("triage") or payload.get("triage") or {}
        return {
            "kind": payload.get("kind") or "error",
            "signal": payload.get("signal") or "",
            "service": payload.get("service") or "",
            "level": payload.get("level") or "",
            "severity": payload.get("severity") or "",
            "confidence": payload.get("confidence") or "",
            "evidence": payload.get("evidence") or [],
            "blast_radius": payload.get("blast_radius") or {},
            # Optimization-only extras (empty on error findings):
            "subject": payload.get("subject") or "",
            "frequency": payload.get("frequency") or {},
            "resource_win": payload.get("resource_win") or "",
            # Agent-filled (empty until the acting specialist runs):
            "probable_cause": payload.get("probable_cause") or payload.get("likely_cause") or "",
            "suggested_fix": payload.get("suggested_fix") or "",
            "recommendation": payload.get("recommendation") or "",
            "triage_status": (triage.get("status") if isinstance(triage, dict) else "") or "pending",
            # Grounded-verifier flag: the suggestion couldn't be grounded in the
            # finding's evidence → committed but downgraded, awaiting a human.
            "needs_human": bool(
                payload.get("needs_human") or (triage.get("needs_human") if isinstance(triage, dict) else False)
            ),
            # Draft-PR outcome (rung 1): set by OpenDraftPrUseCase after the
            # human approves. ``None`` until a PR exists — the UI shows the
            # approve affordance for triaged, grounded findings without one.
            "draft_pr": payload.get("draft_pr") or None,
        }

    def get_provenance(self, obj):
        """Expose the provenance trail for any agent-filed board task.

        Returns ``None`` for human-created tasks. For an agent-filed card it
        surfaces WHO put it on the board (detector), WHO acted on it (specialist)
        and WHEN — the audit trail the HUD renders as a provenance strip.
        Mechanical reshape of ``metadata.provenance`` — no domain logic.
        """
        meta = getattr(obj, "metadata", None) or {}
        prov = meta.get("provenance")
        if not prov:
            return None
        return {
            "created_by_kind": prov.get("created_by_kind") or "",
            "detector": prov.get("detector") or meta.get("detector") or "",
            "assigned_specialist": prov.get("assigned_specialist") or meta.get("agent_type") or "",
            "created_at": prov.get("created_at") or "",
            "confidence": prov.get("confidence") or "",
            "last_handled_by": prov.get("last_handled_by") or "",
            "last_handled_at": prov.get("last_handled_at") or "",
            "events": prov.get("events") or [],
        }

    def get_total_tracked_minutes(self, obj):
        from django.db.models import Sum

        user = self._get_request_user()
        if not user:
            return 0

        entries = obj.entries.filter(created_by=user)
        completed_total = entries.filter(is_tracked=False).aggregate(total=Sum("minutes"))["total"] or 0

        # Include active timer time if one exists
        active_entry = entries.filter(is_tracked=True).order_by("-created_at").first()
        if active_entry:
            try:
                elapsed_seconds = (timezone.now() - active_entry.created_at).total_seconds()
                if elapsed_seconds > 0:
                    completed_total += int(elapsed_seconds // 60)
            except Exception:
                # Fallback: ignore active entry if timestamp arithmetic fails
                pass

        return int(completed_total)

    def get_total_tracked_display(self, obj):
        minutes = self.get_total_tracked_minutes(obj)
        hours, mins = divmod(minutes, 60)
        if hours and mins:
            return f"{hours}h {mins}m"
        if hours:
            return f"{hours}h"
        return f"{mins}m"


class ProjectEntrySerializer(WritableNestedModelSerializer, serializers.ModelSerializer):
    task = serializers.SlugRelatedField(queryset=Task.objects.all(), slug_field="id")
    created_by = serializers.SlugRelatedField(queryset=CustomUser.objects.all(), slug_field="id")
    project = serializers.SlugRelatedField(queryset=Project.objects.all(), slug_field="id")

    class Meta:
        model = ProjectEntry
        fields = ["project", "task", "minutes", "is_tracked", "created_by", "created_at"]


class ColumnSerializer(WritableNestedModelSerializer, serializers.ModelSerializer):
    team = serializers.SlugRelatedField(queryset=Team.objects.all(), slug_field="id")  # Team by id
    created_by = serializers.SlugRelatedField(queryset=CustomUser.objects.all(), slug_field="id")  # User by id
    project = serializers.SlugRelatedField(
        queryset=Project.objects.all(), slug_field="id", required=False
    )  # Project by id, now optional
    workspace = serializers.SlugRelatedField(queryset=Workspace.objects.all(), slug_field="id")  # Workspace by id
    tasks = serializers.SerializerMethodField()  # Related tasks in board order

    def get_tasks(self, obj):
        # Task.Meta.ordering is ['-created_at'], so the bare `tasks.all` used
        # here previously ignored the drag-persisted `order` field — every
        # in-column reorder reverted on the next board fetch. Board order is
        # ('order', 'created_at'), matching ProjectSerializer's task listing.
        tasks = (
            obj.tasks.select_related("column")
            .prefetch_related("assigned_to__profile", "assigned_to")
            .order_by("order", "created_at")
        )
        return TaskSerializer(tasks, many=True, context=self.context).data

    class Meta:
        model = Column
        fields = [
            "pk",
            "team",
            "workspace",
            "created_by",
            "title",
            "project",
            "order",
            "hidden",
            "description",
            "color",
            "is_archived",
            "is_deleted",
            "created_at",
            "updated_at",
            "tasks",
        ]
        read_only_fields = ["team", "workspace", "created_by", "created_at", "updated_at"]

    def to_representation(self, instance):
        """Exclude soft-deleted columns."""
        data = super().to_representation(instance)
        if instance.is_deleted:
            return {}
        return data
