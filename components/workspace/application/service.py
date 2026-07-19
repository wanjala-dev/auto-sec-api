from __future__ import annotations

from components.team.application.ports.team_membership_port import TeamMembershipPort
from components.team.infrastructure.repositories.team_membership_repository import (
    OrmTeamMembershipRepository,
)
from components.workspace.application.providers.workspace_bootstrap_provider import (
    WorkspaceBootstrapProvider,
)
from components.workspace.application.providers.workspace_detail_query_provider import (
    WorkspaceDetailQueryProvider,
)
from components.workspace.application.providers.workspace_setup_query_provider import (
    WorkspaceSetupQueryProvider,
)
from components.workspace.infrastructure.repositories.workspace_query_repository import (
    WorkspaceQueryRepository,
)


class WorkspaceService:
    def __init__(
        self,
        *,
        team_membership_store: TeamMembershipPort = None,
        query_repository: WorkspaceQueryRepository = None,
    ) -> None:
        if team_membership_store is None:
            from components.team.domain.policies.team_membership_policy_service import TeamMembershipPolicyService
            from components.workspace.domain.policies.contributor_enrollment_policy_service import (
                ContributorEnrollmentPolicyService,
            )

            team_membership_store = OrmTeamMembershipRepository(
                team_membership_policy=TeamMembershipPolicyService(),
                contributor_enrollment_policy=ContributorEnrollmentPolicyService(),
            )
        self.team_membership_store = team_membership_store
        self.query_repository = query_repository or WorkspaceQueryRepository()
        self.workspace_bootstrap_provider = WorkspaceBootstrapProvider()
        self.workspace_detail_query_provider = WorkspaceDetailQueryProvider()
        self.workspace_setup_query_provider = WorkspaceSetupQueryProvider()

    def get_or_create_default_team(self, workspace):
        if not workspace:
            return None
        return self.team_membership_store.get_or_create_default_team(workspace)

    def enroll_user_in_team(
        self,
        user,
        workspace,
        team,
        *,
        mark_contributor: bool = True,
        update_active_context: bool = False,
    ) -> None:
        if not user or not team:
            return

        self.team_membership_store.enroll_user_in_team(
            user,
            workspace,
            team,
            mark_contributor=mark_contributor,
            update_active_context=update_active_context,
        )

    def ensure_contributor_membership(self, user, workspace):
        if not user or not workspace:
            return None
        return self.team_membership_store.ensure_contributor_membership(user, workspace)

    def create_workspace(self, **kwargs):
        """Orchestrate workspace creation and bootstrap.

        Delegates to WorkspaceBootstrapProvider.
        """
        use_case = self.workspace_bootstrap_provider.build_create_workspace_use_case()
        return use_case.execute(**kwargs)

    def get_workspace_detail_query(self):
        """Access workspace detail query.

        Delegates to WorkspaceDetailQueryProvider.
        """
        return self.workspace_detail_query_provider.build_query()

    def get_workspace_setup_query_service(self):
        """Access workspace setup query service.

        Delegates to WorkspaceSetupQueryProvider.
        """
        return self.workspace_setup_query_provider.build_service()

    # ========================================================================
    # Query Repository Delegation Methods
    # ========================================================================

    def get_all_countries(self):
        """Fetch all countries."""
        return self.query_repository.get_all_countries()

    def get_country_by_name(self, name: str):
        """Fetch a country by name."""
        return self.query_repository.get_country_by_name(name)

    def get_all_workspaces(self):
        """Fetch all workspaces."""
        return self.query_repository.get_all_workspaces()

    def get_workspace_by_id(self, workspace_id):
        """Fetch a workspace by ID."""
        return self.query_repository.get_workspace_by_id(workspace_id)

    def get_workspaces_by_ids(self, workspace_ids: list):
        """Fetch multiple workspaces by IDs."""
        return self.query_repository.get_workspaces_by_ids(workspace_ids)

    def get_workspaces_by_owner(self, owner):
        """Fetch workspaces owned by a user."""
        return self.query_repository.get_workspaces_by_owner(owner)

    def count_workspaces_by_owner(self, owner):
        """Count workspaces owned by a user."""
        return self.query_repository.count_workspaces_by_owner(owner)

    def get_workspaces_by_country(self, country):
        """Fetch workspaces by country."""
        return self.query_repository.get_workspaces_by_country(country)

    def get_workspace_with_prefetch(self, workspace_id, *, include_budget: bool = True):
        """Fetch workspace with prefetched relations."""
        return self.query_repository.get_workspace_with_prefetch(workspace_id, include_budget=include_budget)

    def get_all_workspaces_with_relations(self):
        """Fetch all workspaces with related data."""
        return self.query_repository.get_all_workspaces_with_relations()

    def get_all_workspace_categories(self):
        """Fetch all workspace categories."""
        return self.query_repository.get_all_workspace_categories()

    def get_workspace_categories_with_subcategories(self):
        """Fetch workspace categories with subcategories."""
        return self.query_repository.get_workspace_categories_with_subcategories()

    def get_workspace_category_by_name(self, name: str):
        """Fetch workspace category by name."""
        return self.query_repository.get_workspace_category_by_name(name)

    def get_all_subcategories(self):
        """Fetch all subcategories."""
        return self.query_repository.get_all_subcategories()

    def get_all_tags(self):
        """Fetch all tags."""
        return self.query_repository.get_all_tags()

    def get_all_workspace_comments(self):
        """Fetch all workspace comments."""
        return self.query_repository.get_all_workspace_comments()

    def get_workspace_comments_by_workspace(self, workspace_id):
        """Fetch comments for a workspace."""
        return self.query_repository.get_workspace_comments_by_workspace(workspace_id)

    def get_workspace_card_by_workspace(self, workspace):
        """Fetch workspace card."""
        return self.query_repository.get_workspace_card_by_workspace(workspace)

    def get_all_workspace_cards(self):
        """Fetch all workspace cards."""
        return self.query_repository.get_all_workspace_cards()

    def get_all_workspace_operations(self):
        """Fetch all workspace operations."""
        return self.query_repository.get_all_workspace_operations()

    def get_workspace_operations_by_workspace(self, workspace):
        """Fetch operations for a workspace."""
        return self.query_repository.get_workspace_operations_by_workspace(workspace)

    def get_workspace_operation_by_id(self, operation_id, workspace):
        """Fetch a workspace operation."""
        return self.query_repository.get_workspace_operation_by_id(operation_id, workspace)

    def bulk_update_workspace_operations(self, ids: list, checked: bool):
        """Bulk update workspace operations."""
        return self.query_repository.bulk_update_workspace_operations(ids, checked)

    def get_or_create_workspace_preference(self, workspace):
        """Get or create workspace preference."""
        return self.query_repository.get_or_create_workspace_preference(workspace)

    def get_all_workspace_preferences(self):
        """Fetch all workspace preferences."""
        return self.query_repository.get_all_workspace_preferences()

    def get_contribution_means_by_workspace(self, workspace_id):
        """Fetch contribution means for a workspace."""
        return self.query_repository.get_contribution_means_by_workspace(workspace_id)

    def get_all_contribution_means(self):
        """Fetch all contribution means."""
        return self.query_repository.get_all_contribution_means()

    def get_contribution_means_by_ids(self, ids: list):
        """Fetch contribution means by IDs."""
        return self.query_repository.get_contribution_means_by_ids(ids)

    def get_all_teams(self):
        """Fetch all teams."""
        return self.query_repository.get_all_teams()

    def get_teams_by_workspace(self, workspace_id):
        """Fetch teams for a workspace."""
        return self.query_repository.get_teams_by_workspace(workspace_id)

    def get_all_actions(self):
        """Fetch all actions."""
        return self.query_repository.get_all_actions()

    def get_actions_by_workspace(self, workspace_id):
        """Fetch actions for a workspace."""
        return self.query_repository.get_actions_by_workspace(workspace_id)

    def get_filters_map(self):
        """Get map of available filters."""
        return self.query_repository.get_filters_map()
