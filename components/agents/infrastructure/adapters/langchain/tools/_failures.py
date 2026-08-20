"""The narrow exception tiers a tool body can honestly expect (ADR 0031 D2 / F4).

The house style across the tool layer is::

    except Exception as exc:                       # blanket
        return f"Error listing tasks: {exc}"       # bare string

which is the dominant defect class in this codebase: the reason is destroyed, the
failure is indistinguishable from an answer, and an ``AttributeError`` in the
tool's own code is swallowed exactly as readily as the timeout the handler was
written for. ``tests/architecture/test_tool_blanket_exception.py`` names every
remaining instance.

The fix is two-sided and this module owns the first side: **name the exceptions
the body actually expects, and let everything else bubble.** LangChain's own
guidance on ``wrap_tool_call`` is explicit about the split — handle runtime input
errors, let implementation bugs propagate — and a bug cannot propagate if the
tool ate it first.

There are exactly two tiers a database-backed tool needs, so they live here once
rather than being re-derived per module:

``INPUT_ERRORS``
    The model handed the ORM something it cannot use — a malformed UUID, a
    payload of the wrong shape, a non-numeric limit. Caller error, reported as
    ``Failure.INVALID_INPUT``. Not retriable: the same call fails the same way.

``UPSTREAM_ERRORS``
    Postgres is unreachable, or the query was cancelled. Nothing about the call
    is wrong. Reported as ``Failure.UPSTREAM_UNAVAILABLE`` and marked retriable.

Deliberately absent: any tier that means "something else happened". That is
``Failure.INTERNAL``, it is inferred by the governance middleware from an escaped
exception, and it must stay loud. A tool that catches it here would be
re-introducing the blanket handler with better manners.

The model-visible bytes are preserved by construction: ``ToolResult.serialize()``
renders ``f"Error: {error}"``, so passing the same clause the old f-string used
keeps the message the LLM reads recognisably identical (one ``": "`` moves; see
ADR 0031 Phase 3, "Two things worth recording").
"""

from __future__ import annotations

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import DatabaseError

from components.agents.application.policies.tool_spec import Failure
from components.agents.infrastructure.adapters.langchain.base import ToolResult

#: Caller/model error. ``ValidationError`` is what the ORM raises for a malformed
#: UUID; ``ValueError``/``TypeError`` cover a payload field of the wrong type.
INPUT_ERRORS: tuple[type[BaseException], ...] = (ValidationError, ValueError, TypeError)

#: The row the caller named is not there. Separated from ``INPUT_ERRORS`` because
#: "you asked for something that does not exist" and "you asked incoherently" are
#: different answers, and the model can act on the difference.
NOT_FOUND_ERRORS: tuple[type[BaseException], ...] = (ObjectDoesNotExist,)

#: The database is unreachable or the query was killed. Not the caller's fault.
UPSTREAM_ERRORS: tuple[type[BaseException], ...] = (DatabaseError,)


def invalid_input(clause: str, exc: BaseException) -> ToolResult:
    """The call was malformed. ``clause`` is the old f-string's verb phrase."""
    return ToolResult(ok=False, error=f"{clause}: {exc}", failure=Failure.INVALID_INPUT)


def not_found(clause: str, exc: BaseException) -> ToolResult:
    """The named row does not exist (or is not visible to this workspace)."""
    return ToolResult(ok=False, error=f"{clause}: {exc}", failure=Failure.NOT_FOUND)


def upstream_unavailable(clause: str, exc: BaseException) -> ToolResult:
    """The database did not answer. Retriable, and not about this call."""
    return ToolResult(
        ok=False,
        error=f"{clause}: {exc}",
        failure=Failure.UPSTREAM_UNAVAILABLE,
        retriable=True,
    )


__all__ = [
    "INPUT_ERRORS",
    "NOT_FOUND_ERRORS",
    "UPSTREAM_ERRORS",
    "invalid_input",
    "not_found",
    "upstream_unavailable",
]
