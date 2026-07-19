from __future__ import annotations

from functools import wraps

from rest_framework.response import Response
from rest_framework import status

from components.shared_platform.infrastructure.services.feature_flags import is_feature_enabled, resolve_workspace_id_from_request


def feature_flag_enabled(flag_key: str):
    """
    Decorator for function-based DRF views to enforce a feature flag.

    Example:
        @api_view(["GET"])
        @permission_classes([IsAuthenticated])
        @feature_flag_enabled("ai.orchestrator")
        def my_view(request):
            ...
    """

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            user = getattr(request, "user", None)
            if not user or not getattr(user, "is_authenticated", False):
                user = None
            workspace_id = resolve_workspace_id_from_request(request, view=None)
            if not is_feature_enabled(flag_key, user=user, workspace_id=workspace_id, request=request):
                return Response({"error": "Feature not enabled"}, status=status.HTTP_403_FORBIDDEN)
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator

