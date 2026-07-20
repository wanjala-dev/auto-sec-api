"""Search API controller — workspace suggest for the HUD omnibox."""

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from components.search.api.requests.suggest_request import SuggestRequest
from components.search.api.resources.suggest_resources import SuggestSectionsResource
from components.search.application.providers.search_service_provider import (
    get_search_suggest_service,
)
from components.search.domain.errors import WorkspaceAccessDenied


class SearchSuggestController(APIView):
    """GET /search/suggest/?q=<str>&limit=<int, default 6, cap 10>&workspace_id=<uuid?>

    Returns ``{"sections": {<section>: [{id, title, subtitle, url}, …]}}``
    with only non-empty sections. Sections: findings, tasks, agents,
    conversations, members, log_services.

    Scope: ``workspace_id`` must be a workspace the requester is an active
    member of (403 otherwise); when absent, all their active memberships
    are searched. Conversations are always the requester's own.
    """

    permission_classes = (permissions.IsAuthenticated,)
    name = "search-suggest"

    def get(self, request, *args, **kwargs):
        suggest_request = SuggestRequest.from_query_params(request.query_params)
        service = get_search_suggest_service()
        try:
            sections = service.suggest(
                user_id=request.user.id,
                q=suggest_request.q,
                limit=suggest_request.limit,
                workspace_id=suggest_request.workspace_id,
            )
        except WorkspaceAccessDenied:
            return Response(
                {"detail": "You are not a member of that workspace."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response(
            SuggestSectionsResource(sections=sections).to_dict(),
            status=status.HTTP_200_OK,
        )
