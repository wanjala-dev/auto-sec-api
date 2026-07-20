"""Workspace query repository with lazy imports.

Consolidates all ORM queries from the workspace controller into a single
repository following the adapter pattern. All model imports are done lazily
inside methods to avoid driving-side coupling at module load time.
"""

from __future__ import annotations


class WorkspaceQueryRepository:
    """ORM adapter for workspace and related domain queries.

    This repository encapsulates all direct ORM calls for:
    - Workspace queries
    - Country queries
    - Sector queries
    - WorkspaceCategory queries
    - SubCategory queries
    - Tag queries
    - WorkspaceComment queries
    - WorkspaceCard queries
    - WorkspaceOperations queries
    - WorkspacePreference queries
    - ContributionMeans queries
    - Team queries (workspace-scoped)
    - Action queries

    All model imports use lazy import (inside methods) to avoid coupling
    at module load time.
    """

    # ========================================================================
    # Country Queries
    # ========================================================================

    @staticmethod
    def get_all_countries():
        """Fetch all countries."""
        from infrastructure.persistence.countries.models import Country

        return Country.objects.all()

    @staticmethod
    def get_country_by_name(name: str):
        """Fetch a single country by name."""
        from infrastructure.persistence.countries.models import Country

        return Country.objects.get(name=name)

    # ========================================================================
    # Workspace Queries
    # ========================================================================

    @staticmethod
    def get_all_workspaces():
        """Fetch all workspaces."""
        from infrastructure.persistence.workspaces.models import Workspace

        return Workspace.objects.all()

    @staticmethod
    def get_workspace_by_id(workspace_id):
        """Fetch a single workspace by ID."""
        from infrastructure.persistence.workspaces.models import Workspace

        return Workspace.objects.get(id=workspace_id)

    @staticmethod
    def get_workspaces_by_ids(workspace_ids: list):
        """Fetch multiple workspaces by IDs."""
        from infrastructure.persistence.workspaces.models import Workspace

        return Workspace.objects.filter(id__in=workspace_ids)

    @staticmethod
    def get_workspaces_by_owner(owner):
        """Fetch all workspaces owned by a user."""
        from infrastructure.persistence.workspaces.models import Workspace

        return Workspace.objects.filter(workspace_owner=owner)

    @staticmethod
    def count_workspaces_by_owner(owner):
        """Count workspaces owned by a user."""
        from infrastructure.persistence.workspaces.models import Workspace

        return Workspace.objects.filter(workspace_owner=owner).count()

    @staticmethod
    def get_workspaces_by_country(country):
        """Fetch workspaces by country."""
        from infrastructure.persistence.workspaces.models import Workspace

        return Workspace.objects.filter(workspace_country=country)

    @staticmethod
    def get_workspace_with_prefetch(
        workspace_id,
        *,
        include_budget: bool = True,
    ):
        """Fetch workspace with prefetched relations."""
        from django.db.models import Prefetch

        from infrastructure.persistence.workspaces.models import Budget, Workspace

        workspace_qs = Workspace.objects.select_related(
            "workspace_owner",
            "shared_user",
            "plan",
        ).prefetch_related(
            "domains",
            "followers",
            "operations",
            "workspace_categories",
            "workspace_subcategories",
        )

        if include_budget:
            budget_prefetch = Prefetch(
                "budgets",
                queryset=Budget.objects.select_related("user", "workspace").order_by("-start_date"),
            )
            workspace_qs = workspace_qs.prefetch_related(budget_prefetch)

        return workspace_qs.get(id=workspace_id)

    @staticmethod
    def get_all_workspaces_with_relations():
        """Fetch all workspaces with related data."""
        from infrastructure.persistence.workspaces.models import Workspace

        return Workspace.objects.select_related(
            "workspace_owner",
            "shared_user",
            "plan",
        ).prefetch_related(
            "domains",
            "followers",
            "operations",
            "workspace_categories",
            "workspace_subcategories",
        )

    # ========================================================================
    # WorkspaceCategory Queries
    # ========================================================================

    @staticmethod
    def get_all_workspace_categories():
        """Fetch all workspace categories."""
        from infrastructure.persistence.workspaces.models import WorkspaceCategory

        return WorkspaceCategory.objects.all()

    @staticmethod
    def get_workspace_categories_with_subcategories():
        """Fetch workspace categories with prefetched subcategories."""
        from django.db.models import Prefetch

        from infrastructure.persistence.workspaces.models import (
            SubCategory,
            WorkspaceCategory,
        )

        subcategory_prefetch = Prefetch(
            "subcategories",
            queryset=SubCategory.objects.only("id", "name", "category"),
        )

        return WorkspaceCategory.objects.only("id", "name").prefetch_related(subcategory_prefetch)

    @staticmethod
    def get_workspace_category_by_name(name: str):
        """Fetch a workspace category by name."""
        from infrastructure.persistence.workspaces.models import WorkspaceCategory

        return WorkspaceCategory.objects.only("id", "name").get(name=name)

    # ========================================================================
    # SubCategory Queries
    # ========================================================================

    @staticmethod
    def get_all_subcategories():
        """Fetch all subcategories."""
        from infrastructure.persistence.workspaces.models import SubCategory

        return SubCategory.objects.only("id", "name", "category")

    # ========================================================================
    # Tag Queries
    # ========================================================================

    @staticmethod
    def get_all_tags():
        """Fetch all tags."""
        from infrastructure.persistence.workspaces.models import Tag

        return Tag.objects.all()

    # ========================================================================
    # WorkspaceComment Queries
    # ========================================================================

    @staticmethod
    def get_all_workspace_comments():
        """Fetch all workspace comments ordered by creation date."""
        from infrastructure.persistence.workspaces.models import WorkspaceComment

        return WorkspaceComment.objects.all().order_by("-created_on")

    @staticmethod
    def get_workspace_comments_by_workspace(workspace_id):
        """Fetch comments for a specific workspace."""
        from infrastructure.persistence.workspaces.models import WorkspaceComment

        return WorkspaceComment.objects.filter(workspace=workspace_id).order_by("-created_on")

    # ========================================================================
    # WorkspaceCard Queries
    # ========================================================================

    @staticmethod
    def get_workspace_card_by_workspace(workspace):
        """Fetch workspace card configuration."""
        from infrastructure.persistence.workspaces.models import WorkspaceCard

        return WorkspaceCard.objects.get(workspace=workspace)

    @staticmethod
    def get_all_workspace_cards():
        """Fetch all workspace cards."""
        from infrastructure.persistence.workspaces.models import WorkspaceCard

        return WorkspaceCard.objects.all()

    # ========================================================================
    # WorkspaceOperations Queries
    # ========================================================================

    @staticmethod
    def get_all_workspace_operations():
        """Fetch all workspace operations."""
        from infrastructure.persistence.workspaces.models import WorkspaceOperations

        return WorkspaceOperations.objects.all()

    @staticmethod
    def get_workspace_operations_by_workspace(workspace):
        """Fetch operations for a workspace."""
        from infrastructure.persistence.workspaces.models import WorkspaceOperations

        return WorkspaceOperations.objects.filter(workspace_followers=workspace)

    @staticmethod
    def get_workspace_operation_by_id(operation_id, workspace):
        """Fetch a single workspace operation."""
        from infrastructure.persistence.workspaces.models import WorkspaceOperations

        return WorkspaceOperations.objects.get(id=operation_id, workspace_followers=workspace)

    @staticmethod
    def bulk_update_workspace_operations(ids: list, checked: bool):
        """Bulk update workspace operations checked status."""
        from infrastructure.persistence.workspaces.models import WorkspaceOperations

        return WorkspaceOperations.objects.filter(id__in=ids).update(checked=checked)

    # ========================================================================
    # WorkspacePreference Queries
    # ========================================================================

    @staticmethod
    def get_or_create_workspace_preference(workspace):
        """Get or create workspace preference."""
        from infrastructure.persistence.notifications.userpreferences.models import WorkspacePreference

        return WorkspacePreference.objects.get_or_create(workspace=workspace)

    @staticmethod
    def get_all_workspace_preferences():
        """Fetch all workspace preferences."""
        from infrastructure.persistence.notifications.userpreferences.models import WorkspacePreference

        return WorkspacePreference.objects.all()

    # ========================================================================
    # ContributionMeans Queries
    # ========================================================================

    @staticmethod
    def get_contribution_means_by_workspace(workspace_id):
        """Fetch contribution means for a workspace."""
        from infrastructure.persistence.workspaces.models import ContributionMeans

        return ContributionMeans.objects.filter(workspaces__id=workspace_id)

    @staticmethod
    def get_all_contribution_means():
        """Fetch all contribution means."""
        from infrastructure.persistence.workspaces.models import ContributionMeans

        return ContributionMeans.objects.all()

    @staticmethod
    def get_contribution_means_by_ids(ids: list):
        """Fetch contribution means by IDs."""
        from infrastructure.persistence.workspaces.models import ContributionMeans

        return ContributionMeans.objects.filter(id__in=ids)

    # ========================================================================
    # Team Queries (workspace-scoped)
    # ========================================================================

    @staticmethod
    def get_all_teams():
        """Fetch all teams."""
        from infrastructure.persistence.team.models import Team

        return Team.objects.all()

    @staticmethod
    def get_teams_by_workspace(workspace_id):
        """Fetch teams for a workspace."""
        from infrastructure.persistence.team.models import Team

        return Team.objects.filter(workspace=workspace_id)

    # ========================================================================
    # Action Queries
    # ========================================================================

    @staticmethod
    def get_all_actions():
        """Fetch all actions."""
        from infrastructure.persistence.workspaces.models import Action

        return Action.objects.all()

    @staticmethod
    def get_actions_by_workspace(workspace_id):
        """Fetch actions for a workspace."""
        from infrastructure.persistence.workspaces.models import Action

        return Action.objects.filter(workspace=workspace_id)

    # ========================================================================
    # Filter Queries (used by filter endpoint)
    # ========================================================================

    @staticmethod
    def get_filters_map():
        """Get map of available filters for workspace."""
        from infrastructure.persistence.workspaces.models import (
            Workspace,
            WorkspaceComment,
        )

        return {
            "Workspace": Workspace.objects.all(),
            "WorkspaceComment": WorkspaceComment.objects.all(),
        }
