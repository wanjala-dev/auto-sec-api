"""SEE-201 — the autonomous AI service principal is a capped reader.

The scheduled detector runs as the workspace's AI teammate user. That principal
must be able to *read* everything (it needs restricted facts to surface
findings) but must never *self-execute* a permission-gated action — it surfaces
a finding for a human instead. Crucially the write cap is by identity, not by an
absent membership row, so it holds even if the AI user is later made an owner or
member (the Agents-as-Teammates roadmap trends that way).
"""

from __future__ import annotations

import pytest

from components.agents.infrastructure.adapters.langchain.base import (
    is_ai_service_principal,
    requires_role,
    resolve_workspace_role,
)
from infrastructure.persistence.ai.models import AITeammateProfile
from infrastructure.persistence.workspaces.models import WorkspaceMembership

AI_REFUSAL_MARKER = "Autonomous AI runs cannot perform this action"


class _GatedAgent:
    """Minimal stand-in carrying only what ``@requires_role`` reads."""

    def __init__(self, user_id, workspace_id):
        self.user_id = str(user_id)
        self.workspace_id = str(workspace_id)

    @requires_role("owner", "admin")
    def sensitive_action(self):
        return "EXECUTED"


@pytest.fixture
def workspace_with_ai(workspace_factory, user_factory):
    def _build():
        workspace = workspace_factory()
        ai_user = user_factory()
        AITeammateProfile.objects.create(workspace=workspace, user=ai_user)
        return workspace, ai_user

    return _build


@pytest.mark.django_db
class TestAiServicePrincipalIdentity:
    def test_identifies_the_ai_teammate_user(self, workspace_with_ai):
        workspace, ai_user = workspace_with_ai()

        assert is_ai_service_principal(ai_user.id, workspace.id) is True

    def test_non_ai_user_is_not_the_service_principal(self, workspace_with_ai, user_factory):
        workspace, _ = workspace_with_ai()
        stranger = user_factory()

        assert is_ai_service_principal(stranger.id, workspace.id) is False

    def test_resolves_to_full_read_ai_service_role(self, workspace_with_ai):
        workspace, ai_user = workspace_with_ai()

        assert resolve_workspace_role(ai_user.id, workspace.id) == "ai_service"


@pytest.mark.django_db
class TestAiServicePrincipalWriteCap:
    def test_gated_tool_denies_the_ai_principal(self, workspace_with_ai):
        workspace, ai_user = workspace_with_ai()

        result = _GatedAgent(ai_user.id, workspace.id).sensitive_action()

        assert AI_REFUSAL_MARKER in result

    def test_cap_holds_even_when_ai_user_is_an_owner_member(self, workspace_with_ai):
        # Future-proofing: granting the AI user an owner membership must NOT
        # unlock gated tools — the identity check runs before role resolution.
        workspace, ai_user = workspace_with_ai()
        WorkspaceMembership.objects.create(
            workspace=workspace,
            user=ai_user,
            role=WorkspaceMembership.Role.OWNER,
            status=WorkspaceMembership.Status.ACTIVE,
        )

        result = _GatedAgent(ai_user.id, workspace.id).sensitive_action()

        assert AI_REFUSAL_MARKER in result

    def test_human_owner_still_passes(self, workspace_factory):
        workspace = workspace_factory()

        result = _GatedAgent(workspace.workspace_owner_id, workspace.id).sensitive_action()

        assert result == "EXECUTED"
