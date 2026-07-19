"""Application-layer facade exposing workspace serializers to other bounded contexts.

Per Explicit Architecture rule 7, other contexts must not import directly
from our infrastructure layer. This facade provides the approved cross-context interface.
"""
from components.workspace.mappers.rest.workspace_serializers import (
    WorkspaceGetSerializer,
)

__all__ = ["WorkspaceGetSerializer"]
