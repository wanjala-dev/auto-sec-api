"""Shared helpers for deep agent components."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel


def to_serializable(value: Any) -> Any:
    """Convert Pydantic models and nested containers into plain Python
    types for JSON storage (DeepRun.state JSONField, LangGraph
    checkpoints, ``run_context`` payload, etc.).

    Why ``model_dump(mode="json")`` instead of plain ``model_dump()``:
    plain mode keeps fields like ``Optional[datetime]`` as live
    ``datetime`` objects, which break the next ``json.dumps`` (the
    JSONField encoder, the LangGraph checkpoint writer, the WS event
    publisher). Setting ``mode="json"`` tells Pydantic to render each
    field through its JSON serializer up front — datetimes become ISO
    strings, UUIDs become strings, Decimals become strings — so the
    resulting dict is safe to hand to ``json.dumps`` without further
    coercion. Caught 2026-05-08 when the per-task agent routing
    prompt nudged the planner to start emitting ``due_date`` and
    every chat after the deploy 5xx'd with "Object of type datetime
    is not JSON serializable".

    The recursive container cases also coerce raw ``datetime`` /
    ``date`` / ``UUID`` / ``Decimal`` values that may end up in a
    plain dict (run_context, telemetry payloads, etc.) without
    passing through a Pydantic model first.
    """
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {k: to_serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_serializable(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    return value
