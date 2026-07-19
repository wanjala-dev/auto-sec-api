"""SEE-199 — role-scoped RAG retrieval.

Pins the intra-workspace access-control policy at the layers that run without
pgvector (SQLite skips the extension): the pure sensitivity policy, the SQL
filter-clause rendering that enforces the tier gate, and the adapter wiring that
maps a viewer's role to the tiers it may read.
"""

from __future__ import annotations

from unittest.mock import patch

from components.knowledge.domain.value_objects.retrieval_sensitivity import (
    GENERAL,
    RESTRICTED,
    allowed_sensitivities_for_role,
    sensitivity_for_section,
)


class TestSensitivityPolicy:
    def test_owner_may_read_general_and_restricted(self):
        assert allowed_sensitivities_for_role("owner") == (GENERAL, RESTRICTED)

    def test_admin_may_read_general_and_restricted(self):
        assert allowed_sensitivities_for_role("admin") == (GENERAL, RESTRICTED)

    def test_role_matching_is_case_insensitive(self):
        assert allowed_sensitivities_for_role("Owner") == (GENERAL, RESTRICTED)

    def test_member_may_read_general_only(self):
        assert allowed_sensitivities_for_role("member") == (GENERAL,)

    def test_none_role_is_least_privilege_general_only(self):
        assert allowed_sensitivities_for_role(None) == (GENERAL,)

    def test_unknown_role_is_least_privilege_general_only(self):
        assert allowed_sensitivities_for_role("viewer") == (GENERAL,)

    def test_ai_service_principal_reads_all_tiers(self):
        # SEE-201 — the autonomous detector is a trusted internal reader.
        assert allowed_sensitivities_for_role("ai_service") == (GENERAL, RESTRICTED)

    def test_financial_and_pipeline_sections_are_restricted(self):
        assert sensitivity_for_section("recent_activity") == RESTRICTED
        assert sensitivity_for_section("top_entities") == RESTRICTED

    def test_identity_and_mission_sections_are_general(self):
        assert sensitivity_for_section("identity") == GENERAL
        assert sensitivity_for_section("mission") == GENERAL
        assert sensitivity_for_section("members") == GENERAL


class TestFilterClauseTierGate:
    """The SQL fragment that enforces the tier gate at the store."""

    @staticmethod
    def _build(filters):
        from components.knowledge.infrastructure.adapters.vector_store.pgvector_store_adapter import (
            PgVectorStoreAdapter,
        )

        return PgVectorStoreAdapter._build_filter_clause(filters)

    def test_scalar_value_renders_equality(self):
        sql, params = self._build({"workspace_id": "ws-1"})

        assert sql == " AND metadata->>%s = %s"
        assert params == ["workspace_id", "ws-1"]

    def test_list_value_renders_set_membership(self):
        sql, params = self._build({"sensitivity": [GENERAL, RESTRICTED]})

        assert sql == " AND metadata->>%s = ANY(%s)"
        assert params == ["sensitivity", ["general", "restricted"]]

    def test_member_tier_filter_excludes_restricted(self):
        # A member's allowed set is ANY(['general']); a chunk stamped
        # 'restricted' — or unstamped (NULL) — fails the ANY and is excluded.
        sql, params = self._build({"sensitivity": list(allowed_sensitivities_for_role("member"))})

        assert sql == " AND metadata->>%s = ANY(%s)"
        assert params == ["sensitivity", ["general"]]


class TestAdapterRoleWiring:
    """The adapter maps viewer_role → the sensitivity filter it hands the store."""

    def _search_capturing_filters(self, viewer_role):
        from components.knowledge.infrastructure.adapters import (
            pgvector_workspace_retrieval_adapter as mod,
        )

        captured = {}

        class _FakeStore:
            def hybrid_search_rrf(self, query, *, k, filters):
                captured["filters"] = filters
                return []

        with (
            patch.object(
                mod.PgVectorWorkspaceRetrievalAdapter,
                "_pgvector_available",
                return_value=True,
            ),
            patch(
                "components.knowledge.infrastructure.adapters.vector_store.pgvector_store_adapter.PgVectorStoreAdapter",
                _FakeStore,
            ),
        ):
            mod.PgVectorWorkspaceRetrievalAdapter().search(
                workspace_id="ws-1", query="how are we doing", viewer_role=viewer_role
            )
        return captured["filters"]

    def test_member_scopes_to_general_only(self):
        filters = self._search_capturing_filters("member")

        assert filters["sensitivity"] == [GENERAL]

    def test_owner_scopes_to_general_and_restricted(self):
        filters = self._search_capturing_filters("owner")

        assert filters["sensitivity"] == [GENERAL, RESTRICTED]

    def test_no_role_is_least_privilege_general_only(self):
        filters = self._search_capturing_filters(None)

        assert filters["sensitivity"] == [GENERAL]
