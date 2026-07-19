"""DB-backed tests for the task_agent edit + comment tools (PR-B2).

The tools landed in PR-B2 close the read-only-after-create gap on
task_agent. Henry called these out by name when asking for the GTM
lock-down: "editing tasks, updating tasks", plus comments.

What's covered:
- ``update_task_due_date`` — ISO-format parsing, clearing via null, error path
- ``update_task_title`` — rename, length validation, error path
- ``delete_task`` — soft-delete via status=archived (preserves comments)
- ``add_task_comment`` — top-level + threaded reply
- ``list_task_comments`` — chronological order, eager-loaded author

Each test exercises the actual ORM (no mocks) so we'd catch a model
schema drift or missing migration immediately.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from components.agents.infrastructure.adapters.langchain.tools import (
    task_agent as task_tools,
)


def _make_agent(workspace_id, user=None):
    """Minimal agent stub matching what task tools read.

    Sets workspace_id (required for scoping), user_id (used by
    ``_resolve_user`` for the comment author), and config so user
    resolution can fall back to defaults if needed.
    """
    agent = MagicMock()
    agent.workspace_id = workspace_id
    agent.user_id = user.id if user else None
    agent.config = {"default_user_id": str(user.id) if user else None}
    return agent


@pytest.fixture
def task_setup(workspace_factory, user_factory, team_factory):
    """A workspace + team + user with one Task ready to edit."""
    from infrastructure.persistence.project.models import Task

    user = user_factory()
    workspace = workspace_factory(owner=user)
    team = team_factory(workspace=workspace, created_by=user)
    task = Task.objects.create(
        workspace_id=workspace.id,
        team=team,
        title="Original title",
        created_by=user,
    )
    return {
        "user": user,
        "workspace": workspace,
        "team": team,
        "task": task,
        "agent": _make_agent(workspace.id, user),
    }


# ── update_task_due_date ───────────────────────────────────────────────


@pytest.mark.django_db
class TestUpdateTaskDueDate:
    def test_sets_due_date_from_iso_date(self, task_setup):
        result = task_tools.update_task_due_date(
            task_setup["agent"],
            {"task_id": str(task_setup["task"].id), "due_date": "2026-06-15"},
        )
        task_setup["task"].refresh_from_db()
        assert task_setup["task"].due_date is not None
        assert task_setup["task"].due_date.year == 2026
        assert task_setup["task"].due_date.month == 6
        assert task_setup["task"].due_date.day == 15
        assert "2026-06-15" in result

    def test_sets_due_date_from_iso_datetime(self, task_setup):
        result = task_tools.update_task_due_date(
            task_setup["agent"],
            {
                "task_id": str(task_setup["task"].id),
                "due_date": "2026-06-15T14:30:00",
            },
        )
        task_setup["task"].refresh_from_db()
        assert task_setup["task"].due_date.hour == 14
        assert task_setup["task"].due_date.minute == 30
        assert "Updated" in result

    def test_clears_due_date_with_null(self, task_setup):
        # First set a due date.
        task_setup["task"].due_date = timezone.now() + timedelta(days=7)
        task_setup["task"].save(update_fields=["due_date"])

        result = task_tools.update_task_due_date(
            task_setup["agent"],
            {"task_id": str(task_setup["task"].id), "due_date": None},
        )
        task_setup["task"].refresh_from_db()
        assert task_setup["task"].due_date is None
        assert "no due date" in result

    def test_rejects_unparseable_due_date(self, task_setup):
        result = task_tools.update_task_due_date(
            task_setup["agent"],
            {"task_id": str(task_setup["task"].id), "due_date": "next Friday"},
        )
        assert "Could not parse" in result
        # The task wasn't touched.
        task_setup["task"].refresh_from_db()
        assert task_setup["task"].due_date is None

    def test_rejects_unknown_task(self, task_setup):
        result = task_tools.update_task_due_date(
            task_setup["agent"],
            {"task_id": "00000000-0000-0000-0000-000000000000", "due_date": "2026-06-15"},
        )
        assert "not found" in result

    def test_rejects_cross_workspace_access(
        self, workspace_factory, user_factory, team_factory
    ):
        """An agent in workspace A must not be able to edit workspace B's task."""
        from infrastructure.persistence.project.models import Task

        user = user_factory()
        ws_a = workspace_factory(owner=user)
        ws_b = workspace_factory(owner=user)
        team_b = team_factory(workspace=ws_b, created_by=user)
        task_in_b = Task.objects.create(
            workspace_id=ws_b.id, team=team_b, title="Other-workspace task", created_by=user
        )

        agent_in_a = _make_agent(ws_a.id, user)
        result = task_tools.update_task_due_date(
            agent_in_a,
            {"task_id": str(task_in_b.id), "due_date": "2026-06-15"},
        )
        assert "not found" in result, (
            "Agent in workspace A must not be able to edit a task that "
            "lives in workspace B — workspace scoping is the security "
            "boundary."
        )
        task_in_b.refresh_from_db()
        assert task_in_b.due_date is None


# ── update_task_title ──────────────────────────────────────────────────


@pytest.mark.django_db
class TestUpdateTaskTitle:
    def test_renames_task(self, task_setup):
        result = task_tools.update_task_title(
            task_setup["agent"],
            {"task_id": str(task_setup["task"].id), "title": "Brand new title"},
        )
        task_setup["task"].refresh_from_db()
        assert task_setup["task"].title == "Brand new title"
        assert "Brand new title" in result

    def test_rejects_empty_title(self, task_setup):
        result = task_tools.update_task_title(
            task_setup["agent"],
            {"task_id": str(task_setup["task"].id), "title": "   "},
        )
        assert "title is required" in result.lower()
        task_setup["task"].refresh_from_db()
        assert task_setup["task"].title == "Original title"

    def test_rejects_overlong_title(self, task_setup):
        result = task_tools.update_task_title(
            task_setup["agent"],
            {"task_id": str(task_setup["task"].id), "title": "x" * 256},
        )
        assert "too long" in result.lower()

    def test_accepts_json_string_input(self, task_setup):
        result = task_tools.update_task_title(
            task_setup["agent"],
            json.dumps({"task_id": str(task_setup["task"].id), "title": "From JSON"}),
        )
        task_setup["task"].refresh_from_db()
        assert task_setup["task"].title == "From JSON"
        assert "From JSON" in result


# ── delete_task ────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestDeleteTask:
    def test_archives_task(self, task_setup):
        from infrastructure.persistence.project.models import Task

        result = task_tools.delete_task(
            task_setup["agent"],
            {"task_id": str(task_setup["task"].id)},
        )
        task_setup["task"].refresh_from_db()
        assert task_setup["task"].status == Task.ARCHIVED
        assert "Archived" in result

    def test_idempotent_on_already_archived(self, task_setup):
        from infrastructure.persistence.project.models import Task

        task_setup["task"].status = Task.ARCHIVED
        task_setup["task"].save(update_fields=["status"])

        result = task_tools.delete_task(
            task_setup["agent"],
            {"task_id": str(task_setup["task"].id)},
        )
        assert "already archived" in result

    def test_preserves_comments_after_archive(
        self, task_setup, user_factory
    ):
        """Comments must survive archive — that's the soft-delete contract."""
        from infrastructure.persistence.project.models import TaskComment

        comment = TaskComment.objects.create(
            comment="Reference comment",
            task=task_setup["task"],
            author=task_setup["user"],
        )
        task_tools.delete_task(
            task_setup["agent"],
            {"task_id": str(task_setup["task"].id)},
        )
        # Comment still exists, still attached to the (archived) task.
        assert TaskComment.objects.filter(id=comment.id).exists()
        comment.refresh_from_db()
        assert comment.task_id == task_setup["task"].id


# ── add_task_comment ───────────────────────────────────────────────────


@pytest.mark.django_db
class TestAddTaskComment:
    def test_creates_top_level_comment(self, task_setup):
        from infrastructure.persistence.project.models import TaskComment

        result = task_tools.add_task_comment(
            task_setup["agent"],
            {"task_id": str(task_setup["task"].id), "comment": "First comment"},
        )
        comments = TaskComment.objects.filter(task=task_setup["task"])
        assert comments.count() == 1
        assert comments.first().comment == "First comment"
        assert comments.first().parent_id is None
        assert "First comment" in result

    def test_creates_threaded_reply(self, task_setup):
        from infrastructure.persistence.project.models import TaskComment

        parent = TaskComment.objects.create(
            comment="Parent comment",
            task=task_setup["task"],
            author=task_setup["user"],
        )
        task_tools.add_task_comment(
            task_setup["agent"],
            {
                "task_id": str(task_setup["task"].id),
                "comment": "Reply to parent",
                "parent_comment_id": str(parent.id),
            },
        )
        reply = TaskComment.objects.filter(parent=parent).first()
        assert reply is not None
        assert reply.comment == "Reply to parent"

    def test_rejects_empty_comment(self, task_setup):
        result = task_tools.add_task_comment(
            task_setup["agent"],
            {"task_id": str(task_setup["task"].id), "comment": "   "},
        )
        assert "required" in result.lower()

    def test_rejects_overlong_comment(self, task_setup):
        result = task_tools.add_task_comment(
            task_setup["agent"],
            {"task_id": str(task_setup["task"].id), "comment": "x" * 5001},
        )
        assert "too long" in result.lower()

    def test_rejects_unknown_parent(self, task_setup):
        result = task_tools.add_task_comment(
            task_setup["agent"],
            {
                "task_id": str(task_setup["task"].id),
                "comment": "Reply",
                "parent_comment_id": "00000000-0000-0000-0000-000000000000",
            },
        )
        assert "Parent comment" in result and "not found" in result


# ── list_task_comments ─────────────────────────────────────────────────


@pytest.mark.django_db
class TestListTaskComments:
    def test_returns_helpful_when_empty(self, task_setup):
        result = task_tools.list_task_comments(
            task_setup["agent"],
            {"task_id": str(task_setup["task"].id)},
        )
        assert "No comments" in result

    def test_lists_comments_most_recent_first(self, task_setup):
        from infrastructure.persistence.project.models import TaskComment

        TaskComment.objects.create(
            comment="oldest",
            task=task_setup["task"],
            author=task_setup["user"],
            created_on=timezone.now() - timedelta(hours=2),
        )
        TaskComment.objects.create(
            comment="middle",
            task=task_setup["task"],
            author=task_setup["user"],
            created_on=timezone.now() - timedelta(hours=1),
        )
        TaskComment.objects.create(
            comment="newest",
            task=task_setup["task"],
            author=task_setup["user"],
        )

        result = task_tools.list_task_comments(
            task_setup["agent"],
            {"task_id": str(task_setup["task"].id)},
        )
        assert "3 total" in result
        # Order: newest first, oldest last.
        newest_idx = result.find("newest")
        middle_idx = result.find("middle")
        oldest_idx = result.find("oldest")
        assert newest_idx < middle_idx < oldest_idx

    def test_marks_replies(self, task_setup):
        from infrastructure.persistence.project.models import TaskComment

        parent = TaskComment.objects.create(
            comment="parent",
            task=task_setup["task"],
            author=task_setup["user"],
        )
        TaskComment.objects.create(
            comment="reply",
            task=task_setup["task"],
            author=task_setup["user"],
            parent=parent,
        )
        result = task_tools.list_task_comments(
            task_setup["agent"],
            {"task_id": str(task_setup["task"].id)},
        )
        assert "(reply)" in result
