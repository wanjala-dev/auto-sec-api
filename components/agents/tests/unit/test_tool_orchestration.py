"""Unit tests for tool orchestration (concurrent read-only execution)."""

from components.agents.infrastructure.adapters.langchain.tool_orchestration import (
    execute_tools_concurrently,
    is_read_only_tool,
    partition_tool_calls,
)


class TestIsReadOnlyTool:
    def test_list_is_read_only(self):
        assert is_read_only_tool("list_budgets") is True

    def test_get_is_read_only(self):
        assert is_read_only_tool("get_task") is True

    def test_search_is_read_only(self):
        assert is_read_only_tool("search_documents") is True

    def test_create_is_mutation(self):
        assert is_read_only_tool("create_budget") is False

    def test_delete_is_mutation(self):
        assert is_read_only_tool("delete_task") is False

    def test_update_is_mutation(self):
        assert is_read_only_tool("update_project") is False

    def test_unknown_defaults_to_read_only(self):
        assert is_read_only_tool("analyze_data") is True


class TestPartitionToolCalls:
    def test_all_read_only(self):
        calls = [
            {"name": "list_budgets"},
            {"name": "get_task"},
            {"name": "search_docs"},
        ]
        concurrent, serial = partition_tool_calls(calls)
        assert len(concurrent) == 3
        assert len(serial) == 0

    def test_all_mutations(self):
        calls = [
            {"name": "create_budget"},
            {"name": "delete_task"},
        ]
        concurrent, serial = partition_tool_calls(calls)
        assert len(concurrent) == 0
        assert len(serial) == 2

    def test_mixed_partitions_at_first_mutation(self):
        calls = [
            {"name": "list_budgets"},
            {"name": "get_task"},
            {"name": "create_budget"},  # mutation breaks the batch
            {"name": "list_projects"},  # goes serial even though read-only
        ]
        concurrent, serial = partition_tool_calls(calls)
        assert len(concurrent) == 2
        assert len(serial) == 2
        assert concurrent[0]["name"] == "list_budgets"
        assert serial[0]["name"] == "create_budget"

    def test_empty_input(self):
        concurrent, serial = partition_tool_calls([])
        assert concurrent == []
        assert serial == []


class TestExecuteToolsConcurrently:
    def test_single_tool(self):
        def executor(call):
            return {"tool": call["name"], "output": "ok"}

        results = execute_tools_concurrently(
            [{"name": "list_budgets"}],
            executor,
        )
        assert len(results) == 1
        assert results[0]["output"] == "ok"

    def test_multiple_tools_concurrent(self):
        call_order = []

        def executor(call):
            call_order.append(call["name"])
            return {"tool": call["name"], "output": f"result_{call['name']}"}

        calls = [
            {"name": "list_budgets"},
            {"name": "get_task"},
            {"name": "search_docs"},
        ]
        results = execute_tools_concurrently(calls, executor)
        assert len(results) == 3
        # Results should be in original order regardless of execution order
        assert results[0]["tool"] == "list_budgets"
        assert results[1]["tool"] == "get_task"
        assert results[2]["tool"] == "search_docs"

    def test_handles_errors(self):
        def executor(call):
            if call["name"] == "fail_tool":
                raise ValueError("boom")
            return {"tool": call["name"], "output": "ok"}

        results = execute_tools_concurrently(
            [{"name": "list_budgets"}, {"name": "fail_tool"}],
            executor,
        )
        assert results[0]["output"] == "ok"
        assert "error" in results[1]
        assert "boom" in results[1]["error"]

    def test_empty_input(self):
        results = execute_tools_concurrently([], lambda c: {})
        assert results == []
