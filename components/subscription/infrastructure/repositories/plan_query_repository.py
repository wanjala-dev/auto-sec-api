"""ORM adapter for the PlanQueryPort.

Translates PlanQueryPort calls into Django ORM queries against the
``apps.team.models.Plan`` model.  This is the only file in the
subscription context that touches ORM — everything else stays pure.
"""

from __future__ import annotations

from components.subscription.application.ports.plan_query_port import (
    PlanInfo,
    PlanQuota,
    PlanQueryPort,
)
from components.subscription.domain.entitlements import (
    EntitlementKey,
    EntitlementsResolver,
)


def _plan_to_info(plan) -> PlanInfo:
    """Map an ORM Plan instance to a PlanInfo DTO.

    Numeric quotas are resolved from the data-driven ``Plan.limits`` map.
    ``PlanQuota`` keeps its legacy int contract where ``0`` means unlimited,
    so an unlimited (None) entitlement maps back to 0.
    """
    entitlements = EntitlementsResolver.resolve(plan_limits=getattr(plan, "limits", None))
    return PlanInfo(
        id=str(plan.id),
        title=plan.title,
        quota=PlanQuota(
            max_projects_per_team=entitlements.limit_for(EntitlementKey.MAX_PROJECTS_PER_TEAM) or 0,
            max_members_per_team=entitlements.limit_for(EntitlementKey.MAX_MEMBERS_PER_TEAM) or 0,
            max_tasks_per_project=entitlements.limit_for(EntitlementKey.MAX_TASKS_PER_PROJECT) or 0,
        ),
        price=plan.price,
        billing_interval=plan.billing_interval,
        is_default=plan.is_default,
    )


class OrmPlanQueryRepository(PlanQueryPort):
    """Django ORM implementation of PlanQueryPort."""

    def get_plan_for_team(self, *, team_id: str) -> PlanInfo | None:
        from infrastructure.persistence.team.models import Team

        try:
            team = Team.objects.select_related("plan").get(pk=team_id)
        except Team.DoesNotExist:
            return None
        if team.plan is None:
            return None
        return _plan_to_info(team.plan)

    def get_plan_for_workspace(self, *, workspace_id: str) -> PlanInfo | None:
        """Return the plan for a workspace's default team, or the default plan."""
        from infrastructure.persistence.team.models import Team

        team = (
            Team.objects.select_related("plan")
            .filter(workspace_id=workspace_id)
            .order_by("pk")
            .first()
        )
        if team is None or team.plan is None:
            return self.get_default_plan()
        return _plan_to_info(team.plan)

    def get_default_plan(self) -> PlanInfo | None:
        from infrastructure.persistence.subscription.models import Plan

        plan = Plan.objects.filter(is_default=True).first()
        if plan is None:
            plan = Plan.objects.filter(title__iexact="Free").first()
        if plan is None:
            return None
        return _plan_to_info(plan)

    def list_available_plans(self) -> list[PlanInfo]:
        from infrastructure.persistence.subscription.models import Plan

        return [_plan_to_info(p) for p in Plan.objects.all().order_by("price")]
