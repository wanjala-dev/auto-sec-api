"""The planner's RAG prefetch must not poison the run's transaction.

``AgentsService.deep_plan_and_run`` dispatches through the command bus, whose
``transaction_middleware`` wraps the whole deep run in one
``transaction.atomic()``.  Inside that block ``_prefetch_retrieved_context``
deliberately swallows retrieval failures so the planner can still run
ungrounded — but a swallowed *database* error is not survivable that way:
Postgres aborts the enclosing transaction, and every later statement in the run
fails with ``current transaction is aborted, commands ignored until end of
transaction block``.

That is not hypothetical.  On the local cluster (2026-08-19) the pgvector
adapter raised ``UndefinedColumn: column "embedding" does not exist`` from
``hybrid_search_rrf``; the blanket ``except Exception`` logged it and returned
``[]``, and every ``POST /ai/agents/deep/plan-and-run/`` run since then landed
``status=failed, last_error='current transaction is aborted…'`` with zero
progress — while the endpoint had already answered ``202 {"status":"pending"}``.

The invariant these tests pin: **a failure inside the prefetch is contained to
the prefetch.**  The caller's transaction survives and the run continues.

The stub models the broken-transaction state the way Django itself does —
``transaction.set_rollback(True)`` is the flag Django raises
``TransactionManagementError`` on, and it is what psycopg's aborted connection
manifests as through ``validate_no_broken_transaction``.  That keeps the test
faithful on SQLite (the suite's backend), where a failed statement does not
abort the transaction at the driver level.  The containment mechanism being
asserted — roll back to a savepoint — is the same one that clears Postgres's
aborted state.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from django.db import InternalError, connection, transaction

from components.agents.infrastructure.services.deep_service import (
    _prefetch_pdf_scoped_context,
    _prefetch_retrieved_context,
)


def _broken_backend(recorder: dict) -> MagicMock:
    """A retrieval backend that fails the way an aborted DB statement does."""

    def _explode(*args, **kwargs):
        # Savepoint stack at the moment of failure: the prefetch must have
        # opened its own, otherwise there is nothing to roll back to.
        recorder["savepoint_ids"] = list(connection.savepoint_ids)
        transaction.set_rollback(True)
        raise InternalError('column "embedding" does not exist')

    port = MagicMock()
    port.search.side_effect = _explode
    port.hybrid_search.side_effect = _explode
    return port


def _assert_own_savepoint(recorder: dict, outer_depth: int) -> None:
    """The failing call must sit one real savepoint deeper than its caller."""
    savepoint_ids = recorder["savepoint_ids"]
    assert len(savepoint_ids) > outer_depth + 1 and savepoint_ids[-1] is not None, (
        "the prefetch must run inside its own savepoint so a caught database error "
        "can be rolled back without taking the caller's transaction with it"
    )


@pytest.mark.django_db
class TestPrefetchFailureIsContained:
    def test_workspace_retrieval_db_error_does_not_abort_the_callers_transaction(self):
        from infrastructure.persistence.ai.agents.models import DeepRun

        recorder: dict = {}
        with (
            patch(
                "components.knowledge.application.providers.workspace_retrieval_provider.workspace_retrieval",
                return_value=_broken_backend(recorder),
            ),
            patch(
                "components.agents.infrastructure.adapters.langchain.base.resolve_workspace_role",
                return_value=None,
            ),
            patch(
                "components.knowledge.application.use_cases."
                "rewrite_query_for_retrieval_use_case."
                "RewriteQueryForRetrievalUseCase.rewrite",
                side_effect=lambda **kwargs: kwargs["query"],
            ),
        ):
            # The command bus's transaction_middleware — the run executes here.
            outer_depth = len(connection.savepoint_ids)
            with transaction.atomic():
                assert _prefetch_retrieved_context(workspace_id="ws-1", goal="newest finding") == []

                # The run's very next statement. Unfixed, this raises
                # TransactionManagementError ("An error occurred in the current
                # transaction…") — the SQLite-side face of Postgres's
                # "current transaction is aborted".
                assert DeepRun.objects.filter(thread_id="never-created").count() == 0

        _assert_own_savepoint(recorder, outer_depth)

    def test_pdf_scoped_db_error_does_not_abort_the_callers_transaction(self):
        """Same contract on the PDF-scoped branch — same swallow, same call site."""
        from infrastructure.persistence.ai.agents.models import DeepRun

        recorder: dict = {}
        with patch(
            "components.knowledge.application.providers.ai_vector_store_provider.AIVectorStoreProvider.get_port",
            return_value=_broken_backend(recorder),
        ):
            outer_depth = len(connection.savepoint_ids)
            with transaction.atomic():
                assert _prefetch_pdf_scoped_context(workspace_id="ws-1", pdf_id="pdf-1", goal="summarise") == []
                assert DeepRun.objects.filter(thread_id="never-created").count() == 0

        _assert_own_savepoint(recorder, outer_depth)
