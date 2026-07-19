"""Teammate profile PATCH semantics — name and avatar are independent.

The assistant identity lives on ``AITeammateProfile`` (``display_name`` +
``avatar_url``). The Settings ▸ AI Assistant tab may PATCH either field
alone, so an avatar-only update must never wipe the name (the pre-avatar
repository treated a missing ``display_name`` as "clear it") and a
name-only update must never touch the avatar.
"""
import uuid

import pytest

from components.agents.application.ports.teammate_profile_port import (
    GetTeammateProfileRequest,
    UpdateTeammateProfileCommand,
)
from components.agents.infrastructure.repositories.teammate_profile_repository import (
    OrmTeammateProfileRepository,
)
from infrastructure.persistence.ai.models import AITeammateProfile
from infrastructure.persistence.users.models import CustomUser
from infrastructure.persistence.workspaces.models import Workspace

pytestmark = pytest.mark.django_db


def _setup():
    suffix = uuid.uuid4().hex[:8]
    owner = CustomUser.objects.create_user(
        username=f"owner-{suffix}",
        email=f"owner-{suffix}@example.com",
        password="pw12345",
    )
    ai_user = CustomUser.objects.create_user(
        username=f"ai-{suffix}",
        email=f"ai-{suffix}@example.com",
        password="pw12345",
    )
    workspace = Workspace.objects.create(
        workspace_name=f"WS {suffix}", workspace_owner=owner, status="active"
    )
    AITeammateProfile.objects.create(
        workspace=workspace,
        user=ai_user,
        display_name="Zawadi",
        avatar_url="",
    )
    return owner, workspace


def test_avatar_only_patch_preserves_name():
    owner, workspace = _setup()
    repo = OrmTeammateProfileRepository()

    result = repo.update_teammate_profile(
        command=UpdateTeammateProfileCommand(
            workspace_id=str(workspace.id),
            user=owner,
            avatar_url="https://cdn.example.org/z.png",
        )
    )

    assert result.avatar_url == "https://cdn.example.org/z.png"
    assert result.display_name == "Zawadi"
    profile = AITeammateProfile.objects.get(workspace=workspace)
    assert profile.display_name == "Zawadi"
    assert profile.avatar_url == "https://cdn.example.org/z.png"


def test_name_only_patch_preserves_avatar():
    owner, workspace = _setup()
    AITeammateProfile.objects.filter(workspace=workspace).update(
        avatar_url="https://cdn.example.org/keep.png"
    )
    repo = OrmTeammateProfileRepository()

    result = repo.update_teammate_profile(
        command=UpdateTeammateProfileCommand(
            workspace_id=str(workspace.id),
            user=owner,
            display_name="Mtaalamu",
        )
    )

    assert result.display_name == "Mtaalamu"
    assert result.avatar_url == "https://cdn.example.org/keep.png"
    profile = AITeammateProfile.objects.get(workspace=workspace)
    assert profile.avatar_url == "https://cdn.example.org/keep.png"


def test_empty_avatar_clears_to_default():
    owner, workspace = _setup()
    AITeammateProfile.objects.filter(workspace=workspace).update(
        avatar_url="https://cdn.example.org/old.png"
    )
    repo = OrmTeammateProfileRepository()

    result = repo.update_teammate_profile(
        command=UpdateTeammateProfileCommand(
            workspace_id=str(workspace.id), user=owner, avatar_url=""
        )
    )

    assert result.avatar_url == ""
    # Name untouched by the avatar reset.
    assert result.display_name == "Zawadi"


def test_get_returns_avatar():
    owner, workspace = _setup()
    AITeammateProfile.objects.filter(workspace=workspace).update(
        avatar_url="https://cdn.example.org/z.png"
    )
    repo = OrmTeammateProfileRepository()

    data = repo.get_teammate_profile(
        request=GetTeammateProfileRequest(
            workspace_id=str(workspace.id), user=owner
        )
    )

    assert data.display_name == "Zawadi"
    assert data.avatar_url == "https://cdn.example.org/z.png"


def test_oversized_avatar_is_bounded():
    owner, workspace = _setup()
    repo = OrmTeammateProfileRepository()

    result = repo.update_teammate_profile(
        command=UpdateTeammateProfileCommand(
            workspace_id=str(workspace.id),
            user=owner,
            avatar_url="https://e.org/" + "y" * 2000,
        )
    )

    assert len(result.avatar_url) == 1000
