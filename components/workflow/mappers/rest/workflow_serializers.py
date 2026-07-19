"""Serializers for workflow definitions, execution, and bindings."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from django.utils.text import slugify
from rest_framework import serializers

from infrastructure.persistence.workspaces.models import Workspace
from infrastructure.persistence.workspaces.workflows.models import (
    Workflow,
    WorkflowBinding,
    WorkflowEnrollment,
    WorkflowEvent,
    WorkflowRun,
    WorkflowRunIdempotency,
    WorkflowSchedule,
    WorkflowStepEvent,
    WorkflowStepState,
    WorkflowTemplate,
    WorkflowVersion,
)
from components.workflow.domain.constants import TARGET_TYPES, TRIGGER_CATALOG
from components.workflow.domain.validators import validate_graph


# Catch-all goals impose NO trigger constraint. "general" is the default a
# workflow gets when the author hasn't picked a specific goal chip
# (campaign/event/sponsorship) — it means "no goal", not a goal that happens to
# whitelist zero triggers. Treating it (and its synonyms) as unconstrained is
# what lets a template-created workflow — whose start node carries a real
# triggerType — actually save/publish. Without this, every "general" workflow
# with any trigger fails validation because no TriggerDefinition lists "general"
# in its goal_ids.
_UNCONSTRAINED_GOALS = {"", "general", "all", "any", "none"}


def _allowed_triggers_for_goal(goal: str | None) -> set[str]:
    normalized_goal = str(goal or "").strip().lower()
    unconstrained = normalized_goal in _UNCONSTRAINED_GOALS
    allowed = set()
    for trigger in TRIGGER_CATALOG:
        if unconstrained or not trigger.goal_ids or normalized_goal in trigger.goal_ids:
            allowed.add(trigger.id)
    return allowed


class WorkflowTemplateSerializer(serializers.ModelSerializer):
    """Serialize workflow templates for API use."""

    workspace_id = serializers.PrimaryKeyRelatedField(
        source="workspace",
        queryset=Workspace.objects.all(),
        required=False,
        allow_null=True,
    )
    suggested_trigger_ids = serializers.SerializerMethodField()
    supports_ai_nodes = serializers.SerializerMethodField()
    visible_to_group_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        default=list,
        help_text="Group UUIDs that can see this template. Empty list means visible to all.",
    )

    class Meta:
        model = WorkflowTemplate
        fields = (
            "id",
            "workspace_id",
            "label",
            "description",
            "category",
            "version",
            "is_system",
            "default_graph",
            "suggested_trigger_ids",
            "supports_ai_nodes",
            "visible_to_group_ids",
            "created_by",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("created_by", "created_at", "updated_at")

    def validate_default_graph(self, value: Dict[str, Any]) -> Dict[str, Any]:
        errors = validate_graph(value)
        if errors:
            raise serializers.ValidationError(errors)
        return value

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        is_system = attrs.get("is_system")
        workspace = attrs.get("workspace")
        if is_system and workspace:
            raise serializers.ValidationError(
                {"workspace_id": "System templates cannot be tied to a workspace."}
            )
        # Only enforce workspace requirement on creation, not partial updates
        if self.instance is None and is_system is False and workspace is None:
            # Try to resolve workspace from request context
            request = self.context.get("request")
            workspace_id = None
            if request:
                workspace_id = (
                    request.data.get("workspace_id")
                    or request.query_params.get("workspace_id")
                )
            if not workspace_id:
                raise serializers.ValidationError(
                    {"workspace_id": "Workspace is required for custom templates."}
                )
        return attrs

    def get_suggested_trigger_ids(self, obj: WorkflowTemplate) -> List[str]:
        category = str(getattr(obj, "category", "") or "").lower()
        trigger_map = {
            "sponsorship": ["contact_added", "donation_received", "sponsorship_started"],
            "campaign": ["contact_added", "campaign_opened", "campaign_clicked"],
            "event": ["event_rsvp_yes", "event_checkin", "contact_added"],
        }
        return trigger_map.get(category, ["contact_added"])

    def get_supports_ai_nodes(self, obj: WorkflowTemplate) -> bool:
        graph = getattr(obj, "default_graph", {}) or {}
        for node in graph.get("nodes", []):
            if isinstance(node, dict) and node.get("type") == "ai":
                return True
        return False

    def to_representation(self, instance: WorkflowTemplate) -> Dict[str, Any]:
        data = super().to_representation(instance)
        data["visible_to_group_ids"] = list(
            instance.visible_to_groups.values_list("id", flat=True)
        )
        return data

    def create(self, validated_data: Dict[str, Any]) -> WorkflowTemplate:
        group_ids = validated_data.pop("visible_to_group_ids", [])
        request = self.context.get("request")
        if request and request.user and request.user.is_authenticated:
            validated_data["created_by"] = request.user
        # Staff can create system templates via the controller override;
        # default to user template if not explicitly set by controller.
        if "is_system" not in validated_data:
            validated_data["is_system"] = False
        if not validated_data.get("id"):
            label = validated_data.get("label", "template")
            slug = slugify(label) or "template"
            prefix = "sys" if validated_data.get("is_system") else "org"
            suffix = WorkflowTemplate.objects.filter(id__startswith=f"tmpl-{slug}-{prefix}").count() + 1
            validated_data["id"] = f"tmpl-{slug}-{prefix}-{suffix}"
        instance = super().create(validated_data)
        if group_ids:
            instance.visible_to_groups.set(group_ids)
        return instance

    def update(self, instance: WorkflowTemplate, validated_data: Dict[str, Any]) -> WorkflowTemplate:
        group_ids = validated_data.pop("visible_to_group_ids", None)
        instance = super().update(instance, validated_data)
        if group_ids is not None:
            instance.visible_to_groups.set(group_ids)
        return instance


class WorkflowSummarySerializer(serializers.ModelSerializer):
    """Summary payload for workflow list endpoints."""

    template_id = serializers.PrimaryKeyRelatedField(
        source="template",
        read_only=True,
    )
    # Soonest enabled-schedule fire time, annotated on the queryset by the
    # repository. None when the workflow has no active schedule.
    next_run_at = serializers.DateTimeField(read_only=True, allow_null=True)
    is_scheduled = serializers.SerializerMethodField()
    # Run-completion summary ({total, completed, pct}) from the total_runs /
    # completed_runs subquery annotations, so the board card can show a REAL
    # progress bar (completed runs ÷ all runs) instead of a fabricated one.
    run_completion = serializers.SerializerMethodField()
    # The workflow owner as a lightweight {id, name, avatar, initials} object
    # (not a bare id) so the card can render the creator's avatar like a task's
    # assignee. created_by is select_related on the queryset (no N+1).
    created_by = serializers.SerializerMethodField()

    class Meta:
        model = Workflow
        fields = (
            "id",
            "name",
            "description",
            "status",
            "goal",
            "template_id",
            "updated_at",
            "next_run_at",
            "is_scheduled",
            "run_completion",
            "created_by",
        )

    def get_is_scheduled(self, obj) -> bool:
        return getattr(obj, "next_run_at", None) is not None

    def get_run_completion(self, obj) -> Dict[str, int]:
        total = int(getattr(obj, "total_runs", 0) or 0)
        completed = int(getattr(obj, "completed_runs", 0) or 0)
        pct = round((completed / total) * 100) if total else 0
        return {"total": total, "completed": completed, "pct": pct}

    def get_created_by(self, obj) -> Optional[Dict[str, Any]]:
        user = getattr(obj, "created_by", None)
        if not user:
            return None
        get_full_name = getattr(user, "get_full_name", None)
        full_name = get_full_name() if callable(get_full_name) else None
        name = (
            (full_name or "").strip()
            or getattr(user, "username", "")
            or getattr(user, "email", "")
            or "Owner"
        )
        avatar = (
            getattr(user, "photo_url", None)
            or getattr(user, "avatar_url", None)
            or getattr(user, "avatar", None)
        )
        initials = (
            "".join(part[0] for part in str(name).split()[:2] if part).upper()
            or "?"
        )
        return {
            "id": str(getattr(user, "id", "") or getattr(user, "pk", "")),
            "name": name,
            "avatar": avatar,
            "initials": initials,
            # Nested under `profile.photo_url` too, so the shared UserAvatarGroup
            # (which reads createdBy.profile.photo_url) renders the photo.
            "profile": {"photo_url": avatar},
        }


class WorkflowSerializer(serializers.ModelSerializer):
    """Full workflow serializer used for create/update/detail endpoints."""

    workspace_id = serializers.PrimaryKeyRelatedField(
        source="workspace",
        queryset=Workspace.objects.all(),
        required=False,
    )
    template_id = serializers.PrimaryKeyRelatedField(
        source="template",
        queryset=WorkflowTemplate.objects.all(),
        required=False,
        allow_null=True,
    )
    created_by = serializers.PrimaryKeyRelatedField(read_only=True)
    graph = serializers.JSONField(required=False, allow_null=True)

    class Meta:
        model = Workflow
        fields = (
            "id",
            "workspace_id",
            "name",
            "description",
            "goal",
            "template_id",
            "is_custom",
            "status",
            "version",
            "graph",
            "created_by",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("is_custom", "version", "created_by", "created_at", "updated_at")

    def validate_graph(self, value: Dict[str, Any]) -> Dict[str, Any]:
        # Drafts are incomplete by nature — a user picks a template (whose nodes
        # are intentionally stub configs) and saves before filling in channels /
        # delays / branch labels. So on create/update we only require the graph
        # be structurally a {nodes:[], edges:[]} object. FULL per-node validation
        # (message channel+body, wait delay, branch labels, single start/end) is
        # enforced at PUBLISH time (WorkflowService.publish_workflow), not on
        # every draft save. Without this split, "Save draft" 400s on any
        # template that hasn't been fully configured yet.
        if value is None:
            return value
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("nodes"), list)
            or not isinstance(value.get("edges"), list)
        ):
            raise serializers.ValidationError(
                [
                    {
                        "code": "invalid_graph",
                        "path": "graph",
                        "message": "Graph must include nodes and edges arrays.",
                    }
                ]
            )
        return value

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        if self.instance is None and not attrs.get("workspace"):
            raise serializers.ValidationError({"workspace_id": "workspace_id is required."})

        goal = attrs.get("goal") or getattr(self.instance, "goal", None)
        graph = attrs.get("graph")
        if graph is None and self.instance is not None:
            graph = getattr(self.instance, "graph", None)

        if isinstance(graph, dict) and goal:
            start_node = next(
                (
                    node
                    for node in (graph.get("nodes") or [])
                    if isinstance(node, dict) and node.get("type") == "start"
                ),
                None,
            )
            start_config = (start_node or {}).get("config") or {}
            # A start node may carry multiple triggers (triggerTypes) and/or a
            # single triggerType — validate every selected trigger against the goal.
            trigger_types = list(start_config.get("triggerTypes") or [])
            single = start_config.get("triggerType")
            if single and single not in trigger_types:
                trigger_types.append(single)
            if trigger_types:
                allowed_triggers = _allowed_triggers_for_goal(goal)
                invalid = [t for t in trigger_types if t not in allowed_triggers]
                if invalid:
                    joined = "', '".join(invalid)
                    raise serializers.ValidationError(
                        {
                            "graph": (
                                f"Start trigger '{joined}' is not valid for workflow goal '{goal}'."
                            )
                        }
                    )

        return attrs

    def create(self, validated_data: Dict[str, Any]) -> Workflow:
        request = self.context.get("request")
        template = validated_data.get("template")
        graph = validated_data.get("graph")

        if graph is None:
            validated_data["graph"] = template.default_graph if template else {"nodes": [], "edges": []}

        validated_data["is_custom"] = template is None
        if request and request.user and request.user.is_authenticated:
            validated_data["created_by"] = request.user
        return super().create(validated_data)

    def update(self, instance: Workflow, validated_data: Dict[str, Any]) -> Workflow:
        if validated_data.get("graph") is None:
            validated_data.pop("graph", None)
        return super().update(instance, validated_data)


class WorkflowVersionSerializer(serializers.ModelSerializer):
    """Serializer for workflow versions (internal use)."""

    class Meta:
        model = WorkflowVersion
        fields = ("id", "workflow", "version", "notes", "graph", "created_by", "created_at")


class WorkflowBindingSerializer(serializers.ModelSerializer):
    """Serialize workflow bindings between triggers and workflows."""

    workflow_id = serializers.PrimaryKeyRelatedField(
        source="workflow",
        queryset=Workflow.objects.filter(is_deleted=False),
    )

    class Meta:
        model = WorkflowBinding
        fields = (
            "id",
            "workflow_id",
            "source_type",
            "source_id",
            "trigger_type",
            "config",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("created_at", "updated_at")

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        source_type = attrs.get("source_type")
        trigger_type = attrs.get("trigger_type")
        allowed = {(trigger.id, trigger.source_type) for trigger in TRIGGER_CATALOG}
        if (trigger_type, source_type) not in allowed:
            raise serializers.ValidationError(
                {"trigger_type": "Trigger type is not valid for the source type."}
            )
        workflow = attrs.get("workflow")
        source_id = attrs.get("source_id")
        if workflow and WorkflowBinding.objects.filter(
            workflow=workflow,
            source_type=source_type,
            source_id=source_id,
            trigger_type=trigger_type,
        ).exists():
            raise serializers.ValidationError(
                {"workflow_id": "A binding already exists for this workflow and trigger."}
            )
        return attrs


class WorkflowEnrollmentSerializer(serializers.ModelSerializer):
    """Serialize workflow enrollments for contacts or groups."""

    workflow_id = serializers.PrimaryKeyRelatedField(
        source="workflow",
        queryset=Workflow.objects.filter(is_deleted=False),
    )

    class Meta:
        model = WorkflowEnrollment
        fields = ("id", "workflow_id", "target_type", "target_id", "status", "entered_at")
        read_only_fields = ("status", "entered_at")


class WorkflowRunSerializer(serializers.ModelSerializer):
    """Serialize workflow runs for read endpoints."""

    workflow_id = serializers.PrimaryKeyRelatedField(source="workflow", read_only=True)

    class Meta:
        model = WorkflowRun
        fields = (
            "id",
            "workflow_id",
            "status",
            "trigger_type",
            "trigger_payload",
            "current_node_id",
            "target_type",
            "target_id",
            "started_at",
            "completed_at",
        )


class TargetSerializer(serializers.Serializer):
    """Validate target payloads in run and enrollment requests."""

    target_type = serializers.ChoiceField(choices=TARGET_TYPES)
    target_id = serializers.CharField(max_length=64)


class WorkflowRunCreateSerializer(serializers.Serializer):
    """Validate run creation payloads."""

    trigger_type = serializers.CharField(max_length=64)
    trigger_payload = serializers.JSONField(default=dict, required=False)
    targets = TargetSerializer(many=True, allow_empty=False)
    idempotency_key = serializers.CharField(max_length=128, required=False, allow_blank=True)


class WorkflowStepEventSerializer(serializers.ModelSerializer):
    """Serialize workflow step events for audit logs."""

    run_id = serializers.PrimaryKeyRelatedField(source="run", read_only=True)

    class Meta:
        model = WorkflowStepEvent
        fields = ("id", "run_id", "node_id", "event_type", "payload", "created_at")


class WorkflowGraphValidateSerializer(serializers.Serializer):
    """Validate a workflow graph without persisting changes."""

    graph = serializers.JSONField()

    def validate_graph(self, value: Dict[str, Any]) -> Dict[str, Any]:
        errors = validate_graph(value)
        if errors:
            raise serializers.ValidationError(errors)
        return value


class WorkflowEventSerializer(serializers.ModelSerializer):
    """Internal serializer for workflow outbox events."""

    workspace_id = serializers.PrimaryKeyRelatedField(source="workspace", queryset=Workspace.objects.all())

    class Meta:
        model = WorkflowEvent
        fields = (
            "id",
            "workspace_id",
            "source_type",
            "source_id",
            "trigger_type",
            "payload",
            "idempotency_key",
            "status",
            "created_at",
            "processed_at",
            "last_error",
        )


class WorkflowStepStateSerializer(serializers.ModelSerializer):
    """Internal serializer for workflow step state debugging."""

    class Meta:
        model = WorkflowStepState
        fields = ("id", "run", "node_id", "status", "attempts", "output", "last_error")


class WorkflowRunIdempotencySerializer(serializers.ModelSerializer):
    """Internal serializer for idempotency debugging."""

    class Meta:
        model = WorkflowRunIdempotency
        fields = ("id", "workflow", "target_type", "target_id", "idempotency_key", "run")


class WorkflowScheduleSerializer(serializers.ModelSerializer):
    """Serialize + validate a recurring schedule for a workflow.

    next_run_at / last_run_at are engine-owned (computed by the planner / set on
    fire) and read-only. Cadence-specific shape is validated here so a weekly
    schedule always carries days and a monthly one a day-of-month.
    """

    class Meta:
        model = WorkflowSchedule
        fields = (
            "id",
            "workflow",
            "cadence",
            "days_of_week",
            "day_of_month",
            "interval_minutes",
            "run_time",
            "timezone",
            "audience",
            "enabled",
            "next_run_at",
            "last_run_at",
            "created_at",
        )
        read_only_fields = (
            "id",
            "workflow",
            "next_run_at",
            "last_run_at",
            "created_at",
        )

    def validate_days_of_week(self, value):
        if value in (None, ""):
            return []
        if not isinstance(value, list) or any(
            not isinstance(d, int) or d < 0 or d > 6 for d in value
        ):
            raise serializers.ValidationError(
                "days_of_week must be a list of integers 0 (Mon) to 6 (Sun)."
            )
        return sorted(set(value))

    def validate_audience(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("audience must be a list of targets.")
        for target in value:
            if (
                not isinstance(target, dict)
                or not target.get("target_type")
                or not target.get("target_id")
            ):
                raise serializers.ValidationError(
                    "each audience target needs target_type and target_id."
                )
        return value

    def validate(self, attrs):
        cadence = attrs.get("cadence") or getattr(self.instance, "cadence", None)
        days = attrs.get(
            "days_of_week",
            getattr(self.instance, "days_of_week", None),
        )
        dom = attrs.get(
            "day_of_month",
            getattr(self.instance, "day_of_month", None),
        )
        interval = attrs.get(
            "interval_minutes",
            getattr(self.instance, "interval_minutes", None),
        )
        run_time = attrs.get(
            "run_time",
            getattr(self.instance, "run_time", None),
        )
        if cadence == WorkflowSchedule.Cadence.INTERVAL:
            if not interval or int(interval) < WorkflowSchedule.MIN_INTERVAL_MINUTES:
                raise serializers.ValidationError(
                    {
                        "interval_minutes": (
                            "An interval schedule needs interval_minutes of at "
                            f"least {WorkflowSchedule.MIN_INTERVAL_MINUTES}."
                        )
                    }
                )
        else:
            # Fixed-time cadences require a time-of-day.
            if run_time is None:
                raise serializers.ValidationError(
                    {"run_time": "A time of day is required for this cadence."}
                )
            if cadence == WorkflowSchedule.Cadence.WEEKLY and not days:
                raise serializers.ValidationError(
                    {
                        "days_of_week": (
                            "Pick at least one weekday for a weekly schedule."
                        )
                    }
                )
            if cadence == WorkflowSchedule.Cadence.MONTHLY and not dom:
                raise serializers.ValidationError(
                    {"day_of_month": "Pick a day of month for a monthly schedule."}
                )
            if dom is not None and (dom < 1 or dom > 28):
                raise serializers.ValidationError(
                    {"day_of_month": "day_of_month must be between 1 and 28."}
                )
        return attrs
