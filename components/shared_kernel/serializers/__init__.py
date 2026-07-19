"""Shared kernel serializers - generic DRF serializers with no context-specific dependencies."""

from rest_framework import serializers


class EmptySerializer(serializers.Serializer):
    """Schema-only serializer for views with no structured request/response body.

    CONSTRAINTS:
    - Do not use for validation or persistence.
    - Intended only to satisfy schema generation for endpoints that return redirects
      or ad-hoc HttpResponse payloads.
    """

    pass


__all__ = ["EmptySerializer"]
