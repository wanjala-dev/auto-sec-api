"""Tests for Social Media agent tooling."""
from types import SimpleNamespace

import pytest

from components.agents.infrastructure.adapters.langchain.tools import social_media_agent as social_tools
from infrastructure.persistence.project.models import Column, Task, TaskComment


@pytest.mark.django_db
def test_queue_social_post_task_creates_backlog_task(user_factory, workspace_factory, team_factory):
    owner = user_factory()
    workspace = workspace_factory(owner=owner)
    team = team_factory(workspace=workspace)
    team.members.add(owner)
    # The social_media agent drafts tasks without a project context, so
    # ``task_agent.create_task`` falls back to a workspace-level column
    # lookup keyed on ``title__iexact``. Seed the Backlog column the
    # test asserts on — the team-board bootstrap helper was removed
    # during the agents/Hex refactor and tasks now rely on the caller
    # (or the project ``ensure_default_columns`` flow) to provide them.
    Column.objects.create(
        workspace=workspace, team=team, project=None, title="Backlog"
    )

    agent = SimpleNamespace(workspace_id=str(workspace.id), user_id=str(owner.id), config={})
    draft = {
        "platform": "tiktok",
        "caption": "Short update about our new well project.",
        "video_script": "Hook, story, CTA.",
        "hashtags": ["#impact", "#water"],
        "cta": "Support the project",
    }

    result = social_tools.queue_social_post_task(
        agent,
        {
            "draft": draft,
            "title": "Publish TikTok well update",
            "assignee": "me",
            "column_title": "Backlog",
        },
    )

    assert "Successfully created task" in result
    task = Task.objects.get(workspace_id=workspace.id, title="Publish TikTok well update")
    assert task.column is not None
    assert task.column.title == "Backlog"
    comment = TaskComment.objects.filter(task=task).first()
    assert comment is not None
    assert "TikTok" in comment.comment
