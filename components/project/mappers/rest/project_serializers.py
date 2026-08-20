from django.utils import timezone
from drf_writable_nested.serializers import WritableNestedModelSerializer
from rest_framework import serializers

from components.identity.mappers.rest.identity_serializers import LeanUserSerializer
from components.shared_kernel.domain import triage as _shared_triage
from components.workspace.mappers.rest.workspace_serializers import WorkspaceContributionsMeansSerializer
from infrastructure.persistence.project.models import (
    Column,
    Project,
    ProjectEntry,
    ProjectMilestone,
    ProjectUpdate,
    Task,
    TaskComment,
)
from infrastructure.persistence.team.models import Team
from infrastructure.persistence.users.models import CustomUser
from infrastructure.persistence.workspaces.models import ContributionMeans, Grant, Workspace


class TaskCommentSerializer(serializers.ModelSerializer):
    author = LeanUserSerializer(read_only=True)
    likes = LeanUserSerializer(many=True, read_only=True)
    dislikes = LeanUserSerializer(many=True, read_only=True)
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
        # ``status=ARCHIVED`` is the Task soft-delete state (recycle-bin
        # trash) — soft-deleted tasks must not leak into project reads.
        prefetched_tasks = getattr(obj, "_prefetched_objects_cache", {}).get("tasks")
        if prefetched_tasks is not None:
            tasks = [task for task in prefetched_tasks if task.status != Task.ARCHIVED]
        else:
            tasks = (
                obj.tasks.select_related("column")
                .prefetch_related("assigned_to__profile", "assigned_to")
                .exclude(status=Task.ARCHIVED)
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
    # Autonomous-run telemetry for a handled finding — the rubric/critic
    # verdicts, retry count and budget outcome of the deep run that triaged
    # this card (stamped post-dispatch, task #58). None for everything else.
    run_telemetry = serializers.SerializerMethodField()

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
            "run_telemetry",
        ]
        read_only_fields = [
            "team",
            "workspace_id",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def to_representation(self, instance):
        # Override to include full project object in the response.
        #
        # Serialized once per DISTINCT project and cached in the serializer
        # context: ``ProjectSerializer`` runs ~5 ORM queries per call
        # (updates/milestones/contribution_means M2Ms + the registered_time /
        # num_tasks_todo model methods), so serializing it per TASK made a
        # project-board page cost 5 queries × row count. A board page has a
        # handful of distinct projects at most, and identical input yields
        # identical output within one request.
        representation = super().to_representation(instance)
        if instance.project:
            cache = self.context.setdefault("_project_repr_cache", {})
            key = instance.project_id
            if key not in cache:
                cache[key] = ProjectSerializer(instance.project).data
            representation["project"] = cache[key]
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
                from components.agents.application.providers.agent_permissions_provider import (
                    get_agent_permissions_provider,
                )

                alias = get_agent_permissions_provider().resolve_ai_teammate_alias(action.workspace)
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
        # The finding kinds share the evidence-contract payload shape, so ONE
        # card renders all of them — an error finding (triage agent fills the
        # fix), an optimization finding (optimization agent fills the
        # recommendation), a SAST finding (code_security agent fills the
        # before/after fix; ADR 0019 P2 rides the same field so the frontend's
        # existing finding-card seam lights up without a parallel serializer),
        # and a container CVE finding (the triage agent fills the recommendation
        # + the image-target FIX SNIPPET — its artifact, since a public/unlinked
        # image has no repo to PR against).
        source_type = getattr(obj, "source_type", "") or ""
        if source_type not in ("ai.log_watch", "ai.log_optimization", "ai.code_security", "ai.container_security"):
            return None
        meta = getattr(obj, "metadata", None) or {}
        payload = meta.get("log_watch") or meta.get("payload")
        if not payload:
            return None
        triage = meta.get("triage") or payload.get("triage") or {}
        _KIND_BY_SOURCE = {"ai.code_security": "code_security", "ai.container_security": "container_security"}
        data = {
            "kind": _KIND_BY_SOURCE.get(source_type) or payload.get("kind") or "error",
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
            # Grounded-verifier LABEL (gate → labeler): "unverified" means the
            # suggestion couldn't be grounded in the finding's evidence (or the
            # source content is untrusted) — the fix still ships, its draft PR
            # opens marked [UNVERIFIED], and the HUD renders the gap verbatim.
            "verification": str(payload.get("verification") or ""),
            "verification_gap": str(
                payload.get("verification_gap")
                or (triage.get("verification_gap") if isinstance(triage, dict) else "")
                or payload.get("needs_human_reason")
                or ""
            ),
            # Boolean kept for legacy consumers (posture backlog, older FE).
            "needs_human": bool(
                payload.get("needs_human") or (triage.get("needs_human") if isinstance(triage, dict) else False)
            ),
            "needs_human_reason": str(payload.get("needs_human_reason") or ""),
            # Untrusted-content heuristic hit (SAST): the HUD's prominent
            # planted-instruction warning keys off this. Was previously written
            # to the payload but never surfaced here — the FE read a field that
            # never arrived.
            "source_flagged": bool(payload.get("source_flagged")),
            # WHERE this finding's fix lands (repo | image | cloud | service |
            # none). The board card offers PREVIEW & OPEN DRAFT PR only for
            # ``repo``; an image-target finding renders its FIX SNIPPET instead
            # (no doomed PR affordance for a public/unlinked image).
            "remediation_target": _shared_triage.remediation_target(source_type, payload),
            "fix_snippet": str(payload.get("fix_snippet") or ""),
            "fix_snippet_language": str(payload.get("fix_snippet_language") or ""),
            # Draft-PR outcome (rung 1): set by OpenDraftPrUseCase after the
            # human approves. ``None`` until a PR exists — the UI shows the
            # approve affordance for triaged findings without one. Carries the
            # verification label the engine stamped.
            "draft_pr": payload.get("draft_pr") or None,
        }
        if source_type == "ai.code_security":
            # SAST extras (ADR 0019 P2): the rule + location header, the matched
            # snippet (already masked upstream for secret-class rules, D8), the
            # before/after fix the advisor grounded, and the snippet's language
            # so HudCodeBlock highlights without auto-detect guessing.
            data.update(
                {
                    "rule_id": payload.get("rule_id") or "",
                    "repo": payload.get("repo") or "",
                    "path": payload.get("path") or "",
                    "start_line": payload.get("start_line") or 0,
                    "end_line": payload.get("end_line") or 0,
                    "commit_sha": (payload.get("commit_sha") or "")[:12],
                    "cwe": payload.get("cwe") or [],
                    "snippet": payload.get("snippet") or "",
                    "fix_before": payload.get("fix_before") or "",
                    "fix_after": payload.get("fix_after") or "",
                    "suggested_fix_language": payload.get("language") or "",
                    # MEASURED per-rule confidence (ADR 0032 D11 Surface A).
                    # ``code_security_agent`` has been computing this since #117
                    # step 3 and writing it to the payload — and NO backend
                    # reader rendered it, so the one honest, statistically
                    # grounded number in the product was invisible to the
                    # operator who needed it. It is a different fact from the
                    # two labels beside it: ``confidence`` is the model grading
                    # itself, ``verification`` is this patch grounded against
                    # this finding, and this is how the advisor has HISTORICALLY
                    # scored on this rule against the frozen corpus. Shape:
                    # {tier, reason, trials, passes, lower_bound} — a tier and
                    # the numbers behind it, never a bare percentage.
                    # ``None`` on older cards triaged before the stamp shipped:
                    # absent is not the same as unproven, and the HUD must not
                    # render it as either.
                    "fix_confidence": payload.get("fix_confidence") or None,
                }
            )
        if source_type == "ai.container_security":
            # Container-CVE extras: the CVE header facts the HUD renders next to
            # the fix snippet (the image-target artifact).
            data.update(
                {
                    "vulnerability_id": payload.get("vulnerability_id") or "",
                    "pkg_name": payload.get("pkg_name") or "",
                    "installed_version": payload.get("installed_version") or "",
                    "fixed_version": payload.get("fixed_version") or "",
                    "target": payload.get("target") or "",
                    "primary_url": payload.get("primary_url") or "",
                }
            )
        return data

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

    def get_run_telemetry(self, obj):
        """Expose the autonomous-run telemetry stamped on a handled finding.

        ``None`` for every task without a stamp (human tasks, un-triaged
        findings, findings handled before the stamp shipped). Mechanical
        reshape of ``metadata.run_telemetry`` — no domain logic. The shape is
        what ``stamp_run_telemetry_on_findings`` writes: rubric_verdicts /
        critic_scores (this finding's entry), worker_retries,
        budget_exceeded, source_thread_id, specialist, stamped_at.
        """
        meta = getattr(obj, "metadata", None) or {}
        telemetry = meta.get("run_telemetry")
        if not isinstance(telemetry, dict) or not telemetry:
            return None
        return {
            "rubric_verdicts": telemetry.get("rubric_verdicts"),
            "critic_scores": telemetry.get("critic_scores"),
            "worker_retries": telemetry.get("worker_retries") or 0,
            "budget_exceeded": telemetry.get("budget_exceeded") or None,
            "source_thread_id": telemetry.get("source_thread_id") or "",
            "specialist": telemetry.get("specialist") or "",
            "stamped_at": telemetry.get("stamped_at") or "",
        }

    def get_total_tracked_minutes(self, obj):
        # Computed in Python over ``obj.entries.all()`` so a repository
        # ``prefetch_related("entries")`` (the board reads do this) makes the
        # roll-up query-free per row. The previous filter/aggregate/first
        # chain fired 2 fresh queries per task — and 4 with the display field
        # below re-invoking this method — which scaled a board page's query
        # count with its card count. Result is memoized per instance so the
        # display field reuses it.
        cached = getattr(obj, "_tracked_minutes_cache", None)
        if cached is not None:
            return cached

        user = self._get_request_user()
        if not user:
            return 0

        entries = [e for e in obj.entries.all() if e.created_by_id == user.id]
        completed_total = sum(e.minutes or 0 for e in entries if not e.is_tracked)

        # Include active timer time if one exists
        active_entries = [e for e in entries if e.is_tracked]
        if active_entries:
            active_entry = max(active_entries, key=lambda e: e.created_at)
            try:
                elapsed_seconds = (timezone.now() - active_entry.created_at).total_seconds()
                if elapsed_seconds > 0:
                    completed_total += int(elapsed_seconds // 60)
            except Exception:
                # Fallback: ignore active entry if timestamp arithmetic fails
                pass

        total = int(completed_total)
        obj._tracked_minutes_cache = total
        return total

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
    # Project by id — optional AND nullable with an explicit default: a
    # team-board column has project=None. The conditional UniqueConstraint on
    # Column (uniq_board_column_title_per_team, condition project__isnull=True)
    # makes DRF auto-generate a UniqueTogetherValidator whose condition field
    # ("project") is force-required unless the serializer field carries a
    # default — without it, POST /project/columns/ rejected every team-board
    # column ("project: This field is required." when omitted, "may not be
    # null." when null), breaking the HUD's + Add Column on team boards.
    project = serializers.SlugRelatedField(
        queryset=Project.objects.all(), slug_field="id", required=False, allow_null=True, default=None
    )
    workspace = serializers.SlugRelatedField(queryset=Workspace.objects.all(), slug_field="id")  # Workspace by id
    tasks = serializers.SerializerMethodField()  # Windowed tasks in board order
    # Live-task count for the whole lane (may exceed len(tasks) — the board
    # read windows each lane; clients page the rest via
    # GET /project/columns/<id>/tasks/).
    tasks_total = serializers.SerializerMethodField()
    tasks_has_more = serializers.SerializerMethodField()

    def validate(self, attrs):
        """Explicit duplicate-title guard for TEAM-BOARD columns (project=None).

        DRF's auto-generated conditional ``UniqueTogetherValidator`` evaluates
        its condition via ``Q.check()``, which silently returns False for this
        constraint shape — so without this guard a duplicate team-board title
        surfaces as a 500 (DB IntegrityError) instead of a 400. The DB
        constraint (``uniq_board_column_title_per_team``) remains the
        concurrency backstop; this is the user-facing validation.
        """
        attrs = super().validate(attrs)

        def _resolved(name):
            if name in attrs:
                return attrs[name]
            return getattr(self.instance, name, None) if self.instance is not None else None

        project = _resolved("project")
        team = _resolved("team")
        workspace = _resolved("workspace")
        title = _resolved("title")
        if project is None and team is not None and workspace is not None and title:
            duplicates = Column.objects.filter(team=team, workspace=workspace, title=title, project__isnull=True)
            if self.instance is not None:
                duplicates = duplicates.exclude(pk=self.instance.pk)
            if duplicates.exists():
                raise serializers.ValidationError(
                    {"title": "A column with this title already exists on the team board."}
                )
        return attrs

    def get_tasks(self, obj):
        # Board reads (``OrmColumnQueryRepository``) attach ``windowed_tasks``
        # — the first N live tasks in board order, eager-loaded for every FK/
        # M2M this serializer's ``TaskSerializer`` reads. A lane is NEVER
        # serialized whole on the board endpoint (a 9k-card intake lane
        # produced a 10.8MB / 30s+ response); the remainder pages through
        # GET /project/columns/<id>/tasks/.
        windowed = getattr(obj, "windowed_tasks", None)
        if windowed is not None:
            return TaskSerializer(windowed, many=True, context=self.context).data

        # Fallback for single-column callers (column create/update responses)
        # that don't route through the repository. Task.Meta.ordering is
        # ['-created_at'], so a bare `tasks.all` would ignore the
        # drag-persisted `order` field — board order is ('order',
        # 'created_at'), matching ProjectSerializer's task listing.
        #
        # ``status=ARCHIVED`` is the Task soft-delete state (recycle-bin
        # trash keeps the column FK). Without the exclusion a trashed card
        # reappeared on the board on the very next columns fetch, while also
        # sitting in the recycle bin — mirrors project_repository's task reads.
        tasks = (
            obj.tasks.select_related("team", "column", "grant", "project", "created_by")
            .prefetch_related("assigned_to", "entries")
            .exclude(status=Task.ARCHIVED)
            .order_by("order", "created_at")
        )
        return TaskSerializer(tasks, many=True, context=self.context).data

    def get_tasks_total(self, obj):
        total = getattr(obj, "tasks_total", None)
        if total is not None:
            return total
        return obj.tasks.exclude(status=Task.ARCHIVED).count()

    def get_tasks_has_more(self, obj):
        windowed = getattr(obj, "windowed_tasks", None)
        if windowed is None:
            return False
        return len(windowed) < self.get_tasks_total(obj)

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
            "tasks_total",
            "tasks_has_more",
        ]
        read_only_fields = ["team", "workspace", "created_by", "created_at", "updated_at"]

    def to_representation(self, instance):
        """Exclude soft-deleted columns.

        Belt-and-braces only — the board read's repository already excludes
        soft-deleted columns at the query so a deleted lane costs nothing to
        serialize; this guard covers single-column callers.
        """
        data = super().to_representation(instance)
        if instance.is_deleted:
            return {}
        return data
