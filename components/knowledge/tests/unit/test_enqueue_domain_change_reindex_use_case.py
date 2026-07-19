"""Unit tests for ``EnqueueDomainChangeReindexUseCase`` (Tier 2 #7).

Pure-application-layer tests — no Django ORM, no DB.  The use case
now takes ``KeyValueCachePort`` + ``CommitHookPort`` (Tier 2 fix-up
for architecture-purity); these tests construct in-memory fakes and
inject them via the shared ``enqueue_reindex_for_workspace`` helper.

See ``docs/plans/RAG_AUDIT_AND_ROADMAP.md`` Tier 2 #7.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable, Optional
from unittest.mock import patch

from components.knowledge.application.ports.commit_hook_port import (
    CommitHookPort,
)
from components.knowledge.application.ports.key_value_cache_port import (
    KeyValueCachePort,
)
from components.knowledge.application.use_cases.enqueue_domain_change_reindex_use_case import (
    DEBOUNCE_SECONDS,
    EnqueueDomainChangeReindexUseCase,
    _resolve_workspace_id,
    enqueue_reindex_for_workspace,
)


def _instance(**kwargs):
    return SimpleNamespace(**kwargs)


class FakeKeyValueCache(KeyValueCachePort):
    """In-memory port double — no Django, no shared state with other
    tests beyond what the fixture stores."""

    def __init__(self) -> None:
        self.store: dict[str, Any] = {}
        self.add_calls: list[tuple[str, Any, int]] = []

    def get(self, key: str) -> Optional[Any]:
        return self.store.get(key)

    def set(self, key: str, value: Any, *, ttl_seconds: int) -> None:
        self.store[key] = value

    def add(self, key: str, value: Any, *, ttl_seconds: int) -> bool:
        self.add_calls.append((key, value, ttl_seconds))
        if key in self.store:
            return False
        self.store[key] = value
        return True


class ImmediateCommitHook(CommitHookPort):
    """Runs callbacks immediately so tests don't need a real
    transaction context."""

    def __init__(self) -> None:
        self.scheduled: list[Callable[[], None]] = []

    def on_commit(self, callback: Callable[[], None]) -> None:
        self.scheduled.append(callback)
        callback()


class NeverCommitHook(CommitHookPort):
    """Records the schedule but never runs the callback — proves the
    debounce-skip path doesn't dispatch.
    """

    def __init__(self) -> None:
        self.scheduled: list[Callable[[], None]] = []

    def on_commit(self, callback: Callable[[], None]) -> None:
        self.scheduled.append(callback)


class TestResolveWorkspaceId:
    def test_reads_workspace_id_directly(self):
        instance = _instance(workspace_id="ws-1")
        assert _resolve_workspace_id(instance) == "ws-1"

    def test_falls_back_to_workspace_dot_id(self):
        workspace = _instance(id="ws-2")
        instance = _instance(workspace=workspace, workspace_id=None)
        assert _resolve_workspace_id(instance) == "ws-2"

    def test_returns_none_when_no_workspace(self):
        instance = _instance(workspace_id=None, workspace=None)
        assert _resolve_workspace_id(instance) is None

    def test_returns_none_when_workspace_id_blank(self):
        instance = _instance(workspace_id="")
        assert _resolve_workspace_id(instance) is None


class TestEnqueueReindexForWorkspaceHappyPath:
    def test_dispatches_on_first_call_with_workspace_id(self):
        cache = FakeKeyValueCache()
        commit_hook = ImmediateCommitHook()
        with patch(
            "components.knowledge.infrastructure.tasks."
            "workspace_index_tasks.reindex_workspace.delay"
        ) as mock_delay:
            result = enqueue_reindex_for_workspace(
                "ws-1",
                domain_label="donation",
                cache_port=cache,
                commit_hook_port=commit_hook,
            )

        assert result is True
        # Cache acquired once with the right key/TTL.
        assert cache.add_calls == [
            ("knowledge:domain_reindex_v1:ws-1", "1", DEBOUNCE_SECONDS)
        ]
        mock_delay.assert_called_once_with("ws-1", False)

    def test_skips_dispatch_when_debounce_lock_held(self):
        cache = FakeKeyValueCache()
        # Pre-seed the lock so the second add() returns False.
        cache.store["knowledge:domain_reindex_v1:ws-1"] = "1"
        commit_hook = NeverCommitHook()
        with patch(
            "components.knowledge.infrastructure.tasks."
            "workspace_index_tasks.reindex_workspace.delay"
        ) as mock_delay:
            result = enqueue_reindex_for_workspace(
                "ws-1",
                domain_label="donation",
                cache_port=cache,
                commit_hook_port=commit_hook,
            )

        assert result is False
        assert commit_hook.scheduled == []
        mock_delay.assert_not_called()

    def test_skips_dispatch_when_no_workspace_id(self):
        cache = FakeKeyValueCache()
        commit_hook = NeverCommitHook()
        result = enqueue_reindex_for_workspace(
            "",
            domain_label="donation",
            cache_port=cache,
            commit_hook_port=commit_hook,
        )

        assert result is False
        # Early return — we never even attempt to acquire the lock.
        assert cache.add_calls == []


class TestUseCaseRoutesThroughHelper:
    """``EnqueueDomainChangeReindexUseCase.execute()`` is a thin
    wrapper around ``enqueue_reindex_for_workspace`` — patching the
    helper proves the wrapping is intact.
    """

    def test_execute_resolves_workspace_and_delegates(self):
        use_case = EnqueueDomainChangeReindexUseCase(domain_label="donation")
        instance = _instance(workspace_id="ws-1")
        with patch(
            "components.knowledge.application.use_cases."
            "enqueue_domain_change_reindex_use_case."
            "enqueue_reindex_for_workspace"
        ) as mock_helper:
            use_case.execute(instance=instance, created=True)

        mock_helper.assert_called_once()
        kwargs = mock_helper.call_args.kwargs
        assert mock_helper.call_args.args == ("ws-1",)
        assert kwargs["domain_label"] == "donation"
        assert kwargs["created"] is True

    def test_execute_silently_drops_orphan_instances(self):
        use_case = EnqueueDomainChangeReindexUseCase(domain_label="donation")
        with patch(
            "components.knowledge.application.use_cases."
            "enqueue_domain_change_reindex_use_case."
            "enqueue_reindex_for_workspace"
        ) as mock_helper:
            use_case.execute(
                instance=_instance(workspace_id=None, workspace=None),
                created=True,
            )

        mock_helper.assert_not_called()


class TestExecuteErrorSwallowing:
    def test_celery_dispatch_failure_does_not_propagate(self):
        """A signal handler that raises would abort the caller's
        save transaction — the dispatch must swallow Celery errors.
        """
        cache = FakeKeyValueCache()
        commit_hook = ImmediateCommitHook()
        with patch(
            "components.knowledge.infrastructure.tasks."
            "workspace_index_tasks.reindex_workspace.delay",
            side_effect=RuntimeError("broker down"),
        ):
            # Must not raise.
            enqueue_reindex_for_workspace(
                "ws-1",
                domain_label="donation",
                cache_port=cache,
                commit_hook_port=commit_hook,
            )


class TestPerWorkspaceDebounce:
    """The cache key includes the workspace_id, so saves on different
    workspaces don't share a lock and both fire their reindex.
    """

    def test_two_workspaces_get_separate_locks(self):
        cache = FakeKeyValueCache()
        commit_hook = ImmediateCommitHook()
        with patch(
            "components.knowledge.infrastructure.tasks."
            "workspace_index_tasks.reindex_workspace.delay"
        ):
            enqueue_reindex_for_workspace(
                "ws-A",
                domain_label="donation",
                cache_port=cache,
                commit_hook_port=commit_hook,
            )
            enqueue_reindex_for_workspace(
                "ws-B",
                domain_label="donation",
                cache_port=cache,
                commit_hook_port=commit_hook,
            )

        captured_keys = [call[0] for call in cache.add_calls]
        assert captured_keys == [
            "knowledge:domain_reindex_v1:ws-A",
            "knowledge:domain_reindex_v1:ws-B",
        ]
