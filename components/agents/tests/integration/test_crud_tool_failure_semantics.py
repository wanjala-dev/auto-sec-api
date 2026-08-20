"""ADR 0031 Phase 4 — the nine live CRUD bodies classify instead of swallowing.

The OQ4 evidence found that exactly nine functions in the inherited CRUD fleet
are *live*:

* `user_agent`'s four, all of them — `list_workspace_members` is pinned by an
  ungated red-team case, and the module was deliberately maintained by #425 the
  day before this change.
* the five `task_agent` functions `TriageAgent` re-exports as `assign_task`
  (637 recorded calls), `get_members_without_tasks` (117), `get_team_members`
  (73), `list_open_findings` (47) and `record_finding`. **874 recorded
  production calls run through them** — the only calls the CRUD fleet has ever
  had, and they arrive through the busiest agent in the product.

All nine used the house style F4 exists to remove::

    except Exception as exc:
        return f"Error listing workspace members: {exc}"

which does three things at once: destroys the reason, makes the failure
indistinguishable from an answer, and eats the tool's own `AttributeError`
exactly as readily as the timeout it was written for.

These tests pin both halves of the fix — that expected failures are now
*classified*, and, more importantly, that unexpected ones are no longer
*caught*. The second half is the one that matters: a conversion that kept the
blanket `except` and merely returned a `ToolResult` would satisfy F4's letter
and leave the bug-hiding behaviour exactly where it was.
"""

from __future__ import annotations

import pytest

from django.core.exceptions import ValidationError

from components.agents.application.policies.tool_spec import Failure
from components.agents.infrastructure.adapters.langchain.base import ToolResult
from components.agents.infrastructure.adapters.langchain.tools import (
    task_agent as task_tools,
)
from components.agents.infrastructure.adapters.langchain.tools import (
    user_agent as user_tools,
)

pytestmark = pytest.mark.django_db


class _Agent:
    """The surface these tool functions read off an agent. Nothing more."""

    def __init__(self, workspace_id):
        self.workspace_id = workspace_id
        self.user_id = None
        self.config = {}


class _RaisingAgent:
    """An agent whose ``workspace_id`` raises when read.

    Every one of the nine bodies reads ``agent.workspace_id`` inside its ``try``
    — some directly, some through ``getattr(agent, "workspace_id", None)`` — so
    a property that raises is a uniform way to drive each converted handler
    without reaching for nine different per-tool triggers.

    ``getattr(..., default)`` swallows ``AttributeError`` and nothing else, which
    is exactly why the two exception classes below behave differently and why
    that difference is the point of these tests.
    """

    user_id = None
    config: dict = {}

    def __init__(self, exc):
        self._exc = exc

    @property
    def workspace_id(self):
        raise self._exc


#: The realistic caller error: the model hands the tool a workspace-shaped
#: string that is not a UUID, and Django raises ``ValidationError`` out of the
#: queryset. It is in ``_failures.INPUT_ERRORS``, so each converted body
#: classifies it as ``INVALID_INPUT`` rather than swallowing it into prose.
_EXPECTED = ValidationError("'not-a-uuid' is not a valid UUID.")

#: An implementation bug. Deliberately NOT in ``INPUT_ERRORS``, and deliberately
#: not ``AttributeError`` — ``getattr(agent, "workspace_id", None)`` would
#: swallow that one before the handler ever saw it, which would make the test
#: pass for the wrong reason.
_UNEXPECTED = RuntimeError("boom - an implementation bug, not caller error")

#: (label, callable) for every converted body. Each is invoked with an agent
#: whose workspace binding raises, so every one reaches its converted handler.
CONVERTED_READS = [
    ("list_workspace_members", lambda a: user_tools.list_workspace_members(a, {})),
    ("search_workspace_members", lambda a: user_tools.search_workspace_members(a, {"query": "x"})),
    ("get_user_profile", lambda a: user_tools.get_user_profile(a, {"user_id": "00000000-0000-0000-0000-000000000001"})),
    (
        "list_user_activity",
        lambda a: user_tools.list_user_activity(a, {"user_id": "00000000-0000-0000-0000-000000000001"}),
    ),
    ("get_team_members", lambda a: task_tools.get_team_members(a)),
    ("get_members_without_tasks", lambda a: task_tools.get_members_without_tasks(a, {})),
    ("list_workspace_tasks", lambda a: task_tools.list_workspace_tasks(a, {})),
    ("assign_task", lambda a: task_tools.assign_task(a, {"assignee": "someone"})),
]

#: ``create_task`` is deliberately not in the list above. It calls
#: ``check_permissions(agent)`` before it touches the ORM, and *that* helper
#: has its own ``except Exception: return False`` — so any error raised while
#: resolving the workspace comes back as "Permission denied" rather than
#: reaching the converted handler. F4 does not flag it (it returns a bool, not
#: a bare string), it is pre-existing, and it is out of scope here — but it is
#: the same swallow-and-mislead shape one layer down, and it is why this tool
#: needs the guard stubbed to reach its own failure path. Recorded rather than
#: quietly worked around.
CREATE_TASK_PAYLOAD = {"title": "a task"}


class TestAnExpectedFailureIsClassified:
    """A malformed workspace binding is caller error, and the tool now says so."""

    @pytest.mark.parametrize("label,call", CONVERTED_READS, ids=[c[0] for c in CONVERTED_READS])
    def test_it_returns_a_tool_result_with_a_reason(self, label, call):
        result = call(_RaisingAgent(_EXPECTED))

        assert isinstance(result, ToolResult), (
            f"{label} returned {type(result).__name__} rather than a ToolResult, so its "
            "failure reason is destroyed before anything downstream can read it."
        )
        assert result.ok is False
        assert result.failure == Failure.INVALID_INPUT
        assert result.retriable is False, "the same malformed call fails the same way"

    @pytest.mark.parametrize("label,call", CONVERTED_READS, ids=[c[0] for c in CONVERTED_READS])
    def test_the_string_the_model_reads_still_names_the_operation(self, label, call):
        """`ToolResult.serialize()` renders `"Error: <error>"`, and the clause
        passed to the failure helper is the same phrase the old f-string used.
        So the message stays recognisable to the model — one `": "` moves, which
        ADR 0031 Phase 3 already records as the unavoidable byte shift when the
        hand-rolled `"Error <verb>ing X: {exc}"` style is converted."""
        rendered = call(_RaisingAgent(_EXPECTED)).serialize()
        assert rendered.startswith("Error: ")
        assert rendered == ToolResult(ok=False, error=call(_RaisingAgent(_EXPECTED)).error).serialize()


class TestAnUnexpectedFailureIsNoLongerSwallowed:
    """The half that matters.

    LangChain's own ``wrap_tool_call`` guidance is explicit: handle runtime input
    errors, let implementation bugs bubble. A bug cannot bubble if the tool ate
    it first — and before this change every one of these bodies ate it.

    A conversion that kept ``except Exception`` and merely returned a
    ``ToolResult`` would satisfy F4's letter (the detector only flags a blanket
    except that returns a *bare string*) while leaving the bug-hiding behaviour
    exactly where it was. This is the test that refuses that shortcut.
    """

    @pytest.mark.parametrize("label,call", CONVERTED_READS, ids=[c[0] for c in CONVERTED_READS])
    def test_an_implementation_bug_propagates(self, label, call):
        with pytest.raises(RuntimeError, match="boom"):
            call(_RaisingAgent(_UNEXPECTED))


class TestTheHappyPathDidNotMove:
    """A conversion touches the failure branch only. The success branch must
    return exactly the string it always did — these tools' output is prose the
    model reads, and a `ToolResult` wrapper around a success would have changed
    it."""

    def test_a_successful_read_still_returns_a_plain_string(self, workspace_factory, user_factory):
        workspace = workspace_factory()
        agent = _Agent(str(workspace.id))

        result = user_tools.list_workspace_members(agent, {})

        assert isinstance(result, str), (
            "The success path must stay a bare string. Wrapping it in a ToolResult would "
            "assert an outcome the framework should infer, and would shadow the 'no "
            "outcome' state ADR 0031 Phase 3 deliberately carries as no artifact at all."
        )

    def test_a_missing_workspace_binding_is_still_guidance_not_an_error(self):
        """These bodies check `agent.workspace_id` up front and return a
        human-readable instruction. That is not a failure — it is the tool
        telling the model what to do — and it must not have become one."""
        result = user_tools.list_workspace_members(_Agent(None), {})

        assert isinstance(result, str)
        assert "No workspace context" in result


class TestCreateTaskIsConvertedButStillShadowedFromAbove:
    """``create_task``'s handler is converted; you cannot yet observe it.

    Two helpers sit between the caller and the ORM, and **each swallows
    everything before the converted handler can run**:

    * ``check_permissions`` — ``except Exception: return False``, so a broken
      workspace binding is reported to the model as *"Permission denied"*.
    * ``_get_default_team`` — same shape returning ``None``, so the same broken
      binding is then reported as *"No team found for this workspace."*

    Neither is flagged by F4, because F4's rule is deliberately narrow: a blanket
    except returning a **bare string**. These return a ``bool`` and a ``Team |
    None``. They are the same defect one layer down, wearing a different return
    type — and they turn an infrastructure error into confident, wrong
    *guidance*, which is worse than the prose F4 was written for.

    This is a **characterization test**: it pins today's wrong-but-real answer so
    the defect is recorded rather than forgotten, and it fails the moment someone
    narrows those two helpers — at which point the assertion below should be
    replaced by the classification assertion its siblings use.
    """

    @pytest.fixture()
    def permitted(self, monkeypatch):
        monkeypatch.setattr(task_tools, "check_permissions", lambda *a, **k: True)

    def test_a_broken_binding_is_reported_as_missing_data_not_as_a_failure(self, permitted):
        result = task_tools.create_task(_RaisingAgent(_EXPECTED), CREATE_TASK_PAYLOAD)

        assert isinstance(result, str), (
            "If this is now a ToolResult, `_get_default_team` stopped swallowing — "
            "good. Replace this characterization test with the classification "
            "assertion the other eight tools use."
        )
        assert "No team found" in result

    def test_even_an_implementation_bug_is_swallowed_by_the_helper(self, permitted):
        """The sharper half. A ``RuntimeError`` — an unambiguous bug — still does
        not escape ``create_task``, because ``_get_default_team`` eats it two
        frames before the converted handler. Converting a tool body is necessary
        and, when its helpers swallow, not sufficient."""
        result = task_tools.create_task(_RaisingAgent(_UNEXPECTED), CREATE_TASK_PAYLOAD)

        assert isinstance(result, str)
        assert "No team found" in result
