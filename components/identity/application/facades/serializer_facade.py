"""Application-layer facade exposing identity serializers to other bounded contexts.

Per Explicit Architecture rule 7, other contexts must not import directly
from our infrastructure layer. This facade provides the approved cross-context interface.
"""
from components.identity.mappers.rest.identity_serializers import (
    UserSerializer,
    UserSearchSerializer,
)

__all__ = ["UserSerializer", "UserSearchSerializer"]
