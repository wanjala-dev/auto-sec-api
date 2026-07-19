"""ORM adapter for workspace detail composition queries.

Extracted from WorkspaceDetail.retrieve() in workspace_views_controller.py.
"""

from __future__ import annotations

from collections import defaultdict

from django.db.models import Prefetch

from components.workspace.application.ports.workspace_detail_query_port import (
    WorkspaceDetailData,
    WorkspaceDetailQueryPort,
)


class OrmWorkspaceDetailQueryRepository(WorkspaceDetailQueryPort):
    def fetch_detail(
        self,
        *,
        workspace,
        include_teams: bool = True,
        include_projects: bool = True,
        include_users: bool = True,
        include_categories: bool = True,
        include_teams_summary: bool = False,
    ) -> WorkspaceDetailData:
        teams = []
        team_ids = []
        projects_by_team: dict = defaultdict(list)
        workspace_projects = []
        associated_users = []
        categories = []

        if include_teams:
            teams = self._fetch_teams(workspace)
            team_ids = [t.id for t in teams]

        project_prefetches = self._build_project_prefetches() if include_projects else []

        if include_projects and team_ids:
            team_project_list = self._fetch_projects_for_teams(team_ids, project_prefetches)
            for project in team_project_list:
                projects_by_team[project.team_id].append(project)

        if include_projects:
            workspace_projects = self._fetch_workspace_projects(workspace, project_prefetches)

        if include_users:
            associated_users = self._fetch_associated_users(workspace)

        if include_categories:
            categories = self._fetch_categories(workspace)

        return WorkspaceDetailData(
            teams=teams,
            projects_by_team=dict(projects_by_team),
            workspace_projects=workspace_projects,
            associated_users=associated_users,
            categories=categories,
        )

    @staticmethod
    def _fetch_teams(workspace) -> list:
        from infrastructure.persistence.team.models import Team

        return list(
            Team.objects.filter(workspace=workspace)
            .select_related("plan", "created_by", "workspace")
            .only(
                "id",
                "workspace",
                "title",
                "created_by",
                "created_at",
                "status",
                "privacy",
                "plan",
                "plan_end_date",
                "plan_status",
                "stripe_customer_id",
                "stripe_subscription_id",
            )
            # ``TeamSummaryWithMembersSerializer`` renders members through
            # ``UserSummarySerializer`` (profile summary + sector slugs) —
            # prefetch those chains or every member fires two lazy loads.
            .prefetch_related("members__profile", "members__sectors")
        )

    @staticmethod
    def _build_project_prefetches() -> list:
        from infrastructure.persistence.project.models import (
            ProjectMilestone,
            ProjectUpdate,
            Task,
        )

        task_prefetch = Prefetch(
            "tasks",
            queryset=(
                Task.objects.select_related("column")
                .prefetch_related("assigned_to__profile", "assigned_to")
                .order_by("order", "created_at")
            ),
        )
        # ``ProjectMilestoneSerializer`` renders ``creator`` and
        # ``ProjectUpdateSerializer`` renders ``author`` — nest the
        # select_related inside the prefetch or each milestone/update row
        # lazy-loads its user.
        milestone_prefetch = Prefetch(
            "milestones",
            queryset=ProjectMilestone.objects.select_related("creator"),
        )
        update_prefetch = Prefetch(
            "project_updates",
            queryset=ProjectUpdate.objects.select_related("author"),
        )
        return [
            milestone_prefetch,
            update_prefetch,
            "contribution_means",
            task_prefetch,
        ]

    @staticmethod
    def _fetch_projects_for_teams(team_ids: list, prefetches: list) -> list:
        from infrastructure.persistence.project.models import Project

        return list(
            Project.objects.filter(team_id__in=team_ids)
            .select_related("team", "created_by", "lead", "budget")
            .only(
                "id",
                "team",
                "workspace",
                "created_by",
                "lead",
                "title",
                "start_date",
                "end_date",
                "created_at",
                "priority",
                "status",
                "resources",
                "description",
                "bgColor",
                "budget",
            )
            .prefetch_related(*prefetches)
        )

    @staticmethod
    def _fetch_workspace_projects(workspace, prefetches: list) -> list:
        from infrastructure.persistence.project.models import Project

        return list(
            Project.objects.filter(workspace=workspace)
            .select_related("team", "created_by", "lead", "budget")
            .only(
                "id",
                "team",
                "workspace",
                "created_by",
                "lead",
                "title",
                "start_date",
                "end_date",
                "created_at",
                "priority",
                "status",
                "resources",
                "description",
                "bgColor",
                "budget",
            )
            .prefetch_related(*prefetches)
        )

    @staticmethod
    def _fetch_associated_users(workspace) -> list:
        from infrastructure.persistence.users.models import CustomUser

        return list(CustomUser.objects.filter(teams__workspace=workspace).distinct())

    @staticmethod
    def _fetch_categories(workspace) -> list:
        # Budget categories are not part of the security product's workspace core.
        return []
