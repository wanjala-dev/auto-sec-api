"""Unit tests for SearchSuggestService — pure logic against a fake port."""

from __future__ import annotations

import pytest

from components.search.application.ports.search_index_port import SearchIndexPort
from components.search.application.service import SearchSuggestService
from components.search.domain.errors import WorkspaceAccessDenied


class FakeSearchIndex(SearchIndexPort):
    """In-memory fake — records calls, returns canned section results."""

    def __init__(self, *, memberships=None, results=None):
        self.memberships = list(memberships or [])
        self.results = results or {}
        self.calls = []

    def active_workspace_ids(self, *, user_id):
        self.calls.append(("active_workspace_ids", {"user_id": user_id}))
        return list(self.memberships)

    def _record(self, section, **kwargs):
        self.calls.append((section, kwargs))
        return list(self.results.get(section, []))

    def suggest_findings(self, *, workspace_ids, q, limit):
        return self._record("findings", workspace_ids=workspace_ids, q=q, limit=limit)

    def suggest_tasks(self, *, workspace_ids, q, limit):
        return self._record("tasks", workspace_ids=workspace_ids, q=q, limit=limit)

    def suggest_agents(self, *, workspace_ids, q, limit):
        return self._record("agents", workspace_ids=workspace_ids, q=q, limit=limit)

    def suggest_conversations(self, *, user_id, q, limit):
        return self._record("conversations", user_id=user_id, q=q, limit=limit)

    def suggest_members(self, *, workspace_ids, q, limit):
        return self._record("members", workspace_ids=workspace_ids, q=q, limit=limit)

    def suggest_log_services(self, *, workspace_ids, q, limit):
        return self._record("log_services", workspace_ids=workspace_ids, q=q, limit=limit)


def _item(title):
    return {"id": "1", "title": title, "subtitle": "", "url": "/"}


class TestQueryValidation:
    def test_query_shorter_than_two_chars_returns_empty(self):
        index = FakeSearchIndex(memberships=["ws-1"], results={"tasks": [_item("t")]})
        service = SearchSuggestService(index=index)

        assert service.suggest(user_id="u1", q="a") == {}
        assert service.suggest(user_id="u1", q="") == {}
        assert service.suggest(user_id="u1", q=None) == {}
        # No section query should have fired at all.
        assert index.calls == []

    def test_query_is_stripped_before_length_check(self):
        index = FakeSearchIndex(memberships=["ws-1"])
        service = SearchSuggestService(index=index)

        assert service.suggest(user_id="u1", q="  a  ") == {}

    def test_stripped_query_is_passed_to_port(self):
        index = FakeSearchIndex(memberships=["ws-1"])
        service = SearchSuggestService(index=index)

        service.suggest(user_id="u1", q="  nmap  ")

        section_calls = [call for call in index.calls if call[0] == "tasks"]
        assert section_calls[0][1]["q"] == "nmap"


class TestLimitCapping:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [(None, 6), (0, 6), (-3, 6), (4, 4), (10, 10), (11, 10), (999, 10)],
    )
    def test_limit_defaults_and_caps(self, raw, expected):
        index = FakeSearchIndex(memberships=["ws-1"])
        service = SearchSuggestService(index=index)

        service.suggest(user_id="u1", q="scan", limit=raw)

        section_calls = [call for call in index.calls if call[0] == "findings"]
        assert section_calls[0][1]["limit"] == expected


class TestWorkspaceScoping:
    def test_defaults_to_all_member_workspaces(self):
        index = FakeSearchIndex(memberships=["ws-1", "ws-2"])
        service = SearchSuggestService(index=index)

        service.suggest(user_id="u1", q="scan")

        findings_call = next(call for call in index.calls if call[0] == "findings")
        assert findings_call[1]["workspace_ids"] == ["ws-1", "ws-2"]

    def test_explicit_workspace_narrows_scope(self):
        index = FakeSearchIndex(memberships=["ws-1", "ws-2"])
        service = SearchSuggestService(index=index)

        service.suggest(user_id="u1", q="scan", workspace_id="ws-2")

        findings_call = next(call for call in index.calls if call[0] == "findings")
        assert findings_call[1]["workspace_ids"] == ["ws-2"]

    def test_non_member_workspace_raises(self):
        index = FakeSearchIndex(memberships=["ws-1"])
        service = SearchSuggestService(index=index)

        with pytest.raises(WorkspaceAccessDenied):
            service.suggest(user_id="u1", q="scan", workspace_id="ws-other")

    def test_no_memberships_still_searches_own_conversations(self):
        index = FakeSearchIndex(memberships=[], results={"conversations": [_item("chat")]})
        service = SearchSuggestService(index=index)

        result = service.suggest(user_id="u1", q="chat")

        assert list(result.keys()) == ["conversations"]
        # Workspace-scoped sections were never queried without a scope.
        assert all(call[0] in {"active_workspace_ids", "conversations"} for call in index.calls)


class TestSectionShaping:
    def test_only_non_empty_sections_returned_in_display_order(self):
        index = FakeSearchIndex(
            memberships=["ws-1"],
            results={
                "members": [_item("Jane")],
                "findings": [_item("Suspicious login")],
                "conversations": [],
                "tasks": [],
                "agents": [],
                "log_services": [],
            },
        )
        service = SearchSuggestService(index=index)

        result = service.suggest(user_id="u1", q="ja")

        assert list(result.keys()) == ["findings", "members"]

    def test_conversations_scoped_to_requesting_user(self):
        index = FakeSearchIndex(memberships=["ws-1"])
        service = SearchSuggestService(index=index)

        service.suggest(user_id="user-42", q="scan")

        conv_call = next(call for call in index.calls if call[0] == "conversations")
        assert conv_call[1]["user_id"] == "user-42"
