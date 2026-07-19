"""Tool orchestration — partition and execute tools with concurrency.

Read-only tools execute concurrently (up to ``max_concurrent``).
Mutation tools execute serially for safety.

Inspired by Clear Code's tool orchestration pattern.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

logger = logging.getLogger(__name__)

# Default concurrency limit for read-only tool calls
MAX_CONCURRENT_READ_TOOLS = 8

# Tool names that are always safe to run concurrently (read-only by nature)
_READ_ONLY_TOOL_PREFIXES = frozenset({
    "list_", "get_", "count_", "fetch_", "search_", "find_",
    "check_", "show_", "describe_", "view_", "lookup_",
})

# Tool names that always require serial execution
_MUTATION_TOOL_PREFIXES = frozenset({
    "create_", "update_", "delete_", "remove_", "add_",
    "set_", "assign_", "approve_", "reject_", "send_",
})


def is_read_only_tool(tool_name: str) -> bool:
    """Heuristic: determine if a tool is read-only based on its name."""
    name = tool_name.lower().strip()
    if any(name.startswith(prefix) for prefix in _MUTATION_TOOL_PREFIXES):
        return False
    if any(name.startswith(prefix) for prefix in _READ_ONLY_TOOL_PREFIXES):
        return True
    # Default: assume read-only (safer to run in parallel than block)
    return True


def partition_tool_calls(
    tool_calls: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split tool calls into (concurrent_batch, serial_batch).

    All consecutive read-only calls at the front of the list run concurrently.
    As soon as a mutation is encountered, everything from that point runs serially.
    """
    concurrent: list[dict[str, Any]] = []
    serial: list[dict[str, Any]] = []

    hit_mutation = False
    for call in tool_calls:
        if hit_mutation:
            serial.append(call)
        elif is_read_only_tool(call.get("name", "")):
            concurrent.append(call)
        else:
            hit_mutation = True
            serial.append(call)

    return concurrent, serial


def execute_tools_concurrently(
    tool_calls: list[dict[str, Any]],
    tool_executor: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    max_concurrent: int = MAX_CONCURRENT_READ_TOOLS,
) -> list[dict[str, Any]]:
    """Execute a batch of read-only tool calls concurrently.

    ``tool_executor`` is a callable that takes a single tool-call dict
    and returns a result dict.
    """
    if not tool_calls:
        return []

    if len(tool_calls) == 1:
        return [tool_executor(tool_calls[0])]

    results: list[dict[str, Any]] = [{}] * len(tool_calls)

    with ThreadPoolExecutor(max_workers=min(max_concurrent, len(tool_calls))) as pool:
        future_to_idx = {
            pool.submit(tool_executor, call): idx
            for idx, call in enumerate(tool_calls)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception as exc:
                logger.warning(
                    "Concurrent tool call %d failed: %s", idx, exc, exc_info=True
                )
                results[idx] = {
                    "tool": tool_calls[idx].get("name", "unknown"),
                    "error": str(exc),
                }

    return results
