"""
Shared lightweight serializers used across multiple apps.
"""

from rest_framework import serializers

from infrastructure.persistence.project.models import Project, Task
from infrastructure.persistence.workspaces.models import ContributionMeans, Workspace


class EmptySerializer(serializers.Serializer):
    """Schema-only serializer for views with no structured request/response body.

    CONSTRAINTS:
    - Do not use for validation or persistence.
    - Intended only to satisfy schema generation for endpoints that return redirects
      or ad-hoc HttpResponse payloads.
    """

    pass


class SimpleWorkspaceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Workspace
        fields = ["id", "workspace_name"]


class WorkspaceSummarySerializer(serializers.ModelSerializer):
    """Lightweight workspace payload for client bootstrapping.

    NOTE:
    - The underlying model is still `apps.workspaces.models.Workspace`. We expose workspace-friendly
      field names so the frontend does not need to reason about legacy terminology.
    """

    name = serializers.CharField(source="workspace_name")

    class Meta:
        model = Workspace
        fields = [
            "id",
            "workspace_type",
            "name",
            "photo_url",
            "status",
            "is_active",
            "is_verified",
            "privacy",
        ]


class ProjectSimpleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = ["id", "title"]


class TaskSimpleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = ["id", "title"]


class SimpleContributionMeansSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContributionMeans
        fields = ["id", "name", "icon", "description"]
