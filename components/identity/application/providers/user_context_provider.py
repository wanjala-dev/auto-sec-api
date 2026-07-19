"""Composition root for user context queries."""
from __future__ import annotations

from components.identity.application.queries.user_context_query import (
    BuildOrgOnboardingPayloadQuery,
    BuildUserContextQuery,
)
from components.identity.application.ports.user_context_query_port import UserContextQueryPort


class UserContextProvider:
    """Builds application-layer query objects for user context."""

    @staticmethod
    def _build_user_context_port() -> UserContextQueryPort:
        from components.identity.infrastructure.repositories.orm_user_context_query_repository import (
            OrmUserContextQueryRepository,
        )

        return OrmUserContextQueryRepository()

    @classmethod
    def build_org_onboarding_query(cls) -> BuildOrgOnboardingPayloadQuery:
        return BuildOrgOnboardingPayloadQuery(cls._build_user_context_port())

    @classmethod
    def build_user_context_query(cls) -> BuildUserContextQuery:
        return BuildUserContextQuery(cls._build_user_context_port())
