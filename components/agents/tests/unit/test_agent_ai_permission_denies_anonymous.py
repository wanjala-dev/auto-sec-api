"""Pin the claim that keeps ``SharedAgentViewSet`` safe without an auth class.

``SharedAgentViewSet`` lists ``RequiresFeatureFlag`` as its only permission
class — the same shape that made ``/social/<pk>/`` exploitable. It is exempted
in ``tests/architecture/test_feature_flag_not_sole_permission.py`` because its
GET is a public share-link lookup (the unguessable token IS the credential) and
its DELETE/revoke path is guarded *below* the view by ``AgentAIPermission``
with ``required_ai_perm="ai_manage"``.

That exemption is only as good as the guard. This module asserts the guard
actually denies an unauthenticated caller, so the justification cannot rot into
a fiction the way the original PostDetail comment did.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import AnonymousUser
from rest_framework.test import APIRequestFactory

from components.agents.api.permissions import AgentAIPermission

pytestmark = pytest.mark.unit


class _View:
    required_ai_perm = "ai_manage"


@pytest.mark.parametrize("method", ["get", "delete", "post"])
def test_agent_ai_permission_denies_anonymous(method):
    request = getattr(APIRequestFactory(), method)("/ai/agents/shared/some-token/")
    request.user = AnonymousUser()

    assert not AgentAIPermission().has_permission(request, _View()), (
        f"AgentAIPermission must deny an anonymous {method.upper()} — it is the only "
        "thing standing between an unauthenticated caller and revoke_share()"
    )


def test_agent_ai_permission_object_check_denies_anonymous():
    request = APIRequestFactory().delete("/ai/agents/shared/some-token/")
    request.user = AnonymousUser()

    assert not AgentAIPermission().has_object_permission(request, _View(), object())
