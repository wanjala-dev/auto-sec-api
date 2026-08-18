"""Serializers for the boards-as-views read API (ADR 0030 P2a).

Read-only projections. The lane serializer mirrors ``ColumnSerializer``'s
windowed-lane contract (``tasks`` / ``tasks_total`` / ``tasks_has_more``,
tasks rendered by the same ``TaskSerializer``) so the HUD's flag flip is a
lane-source swap, not a re-plumb; it also exposes ``title`` as an alias of
``name`` because ``HudKanbanBoard`` renders ``lane.title`` today.
"""

from __future__ import annotations

from rest_framework import serializers

from components.project.mappers.rest.project_serializers import TaskSerializer
from infrastructure.persistence.project.models import BoardView, WorkflowStatus


class BoardViewSerializer(serializers.ModelSerializer):
    """One saved view — a row in the views bar.

    ``created_by`` (creator's user id; null on system views) + ``mine``
    (this view belongs to the requester) carry the task #74 personal-view
    affordances: the bar marks yours and only yours grow rename/delete.
    """

    created_by = serializers.PrimaryKeyRelatedField(read_only=True)
    mine = serializers.SerializerMethodField()

    class Meta:
        model = BoardView
        fields = [
            "id",
            "team",
            "workspace",
            "name",
            "slug",
            "filter",
            "group_by",
            "order",
            "is_system",
            "created_by",
            "mine",
        ]
        read_only_fields = fields

    def get_mine(self, obj) -> bool:
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return bool(
            user is not None
            and getattr(user, "is_authenticated", False)
            and obj.created_by_id is not None
            and str(obj.created_by_id) == str(user.id)
        )


class WorkflowStatusLaneSerializer(serializers.ModelSerializer):
    """One status lane of a view board, with its windowed matching tasks.

    Lanes only reach this serializer through ``OrmBoardViewQueryRepository``,
    which attaches ``windowed_tasks`` + ``tasks_total`` (a lane is NEVER
    serialized whole — performance.md §11; the remainder pages through
    GET /project/views/<view_id>/lanes/<status_id>/tasks/). There is
    deliberately no query-the-lane fallback here: a missing window is an
    empty lane, not an unbounded one.
    """

    title = serializers.CharField(source="name", read_only=True)
    tasks = serializers.SerializerMethodField()
    tasks_total = serializers.SerializerMethodField()
    tasks_has_more = serializers.SerializerMethodField()

    class Meta:
        model = WorkflowStatus
        fields = [
            "id",
            "name",
            "title",
            "category",
            "order",
            "tasks",
            "tasks_total",
            "tasks_has_more",
        ]
        read_only_fields = fields

    def get_tasks(self, obj) -> list:
        windowed = getattr(obj, "windowed_tasks", None) or []
        return TaskSerializer(windowed, many=True, context=self.context).data

    def get_tasks_total(self, obj) -> int:
        return getattr(obj, "tasks_total", 0) or 0

    def get_tasks_has_more(self, obj) -> bool:
        windowed = getattr(obj, "windowed_tasks", None) or []
        return self.get_tasks_total(obj) > len(windowed)
