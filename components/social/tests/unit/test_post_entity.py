"""Unit tests for PostEntity invariants."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from components.social.domain.entities.post_entity import PostEntity, PostVisibility


class TestPostEntity:
    def _fresh(self, **overrides):
        base = dict(
            id=1,
            author_id=uuid4(),
            workspace_id=uuid4(),
            team_id=None,
            visibility=PostVisibility.WORKSPACE,
            body="hello team",
            created_on=datetime.now(timezone.utc),
        )
        base.update(overrides)
        return PostEntity(**base)

    def test_workspace_post_is_valid(self):
        post = self._fresh()
        assert post.visibility == PostVisibility.WORKSPACE

    def test_team_post_requires_team_id(self):
        with pytest.raises(ValueError):
            self._fresh(visibility=PostVisibility.TEAM)

    def test_team_post_with_team_id_is_valid(self):
        post = self._fresh(visibility=PostVisibility.TEAM, team_id=7)
        assert post.team_id == 7

    def test_workspace_post_requires_workspace_id(self):
        with pytest.raises(ValueError):
            self._fresh(workspace_id=None)

    def test_empty_body_rejected(self):
        with pytest.raises(ValueError):
            self._fresh(body="   ")

    def test_public_post_does_not_require_workspace(self):
        post = self._fresh(visibility=PostVisibility.PUBLIC, workspace_id=None)
        assert post.visibility == PostVisibility.PUBLIC
