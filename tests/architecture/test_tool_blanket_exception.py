"""Fitness function F4 (ADR 0031 D2) — a tool must not swallow everything into a string.

**Ratchet mode.** This test does not fail on the 54 violations that exist today;
it names them, every run, as an explicit remediation list. It *does* fail on a
new one, and the list may only ever shrink — ADR 0031 Phase 4 took it from 63 to
54. Flipping it to fail outright means converting the remaining 54 bodies.

That is the same shape F3 (``test_tool_payload_tenancy.py``) landed in, and for
the same reason ADR 0031 names against itself:

    "The main one is that Phase 1's observe-only mode becomes permanent — the
    middleware lands, nothing is ever enforced, and we have added a layer
    without removing a bug class."

Warn-on-the-known / fail-on-the-new is what stops that. A frozen list plus a
build that bites is a ratchet; a list nobody prints is a mute.

── What the rule is ──────────────────────────────────────────────────────────

::

    try:
        ...
    except Exception as exc:               # blanket
        return f"Error listing tasks: {exc}"   # bare string

This is the house style across the tool layer, and it is the dominant defect
class in the codebase. Three things happen at once:

1. **The reason is destroyed.** "not found", "denied", "the LLM provider is
   down" and "this code has a bug" all leave the tool as the same shape of
   prose. Nothing downstream can tell them apart, so everything downstream
   treats them the same.
2. **The failure becomes indistinguishable from an answer.** The string goes
   back to the model as the tool's result. The model narrates over it. Under
   D2 the middleware can now recover *something* from the ``"Error: "`` prefix
   — but only "a failure, reason unknown" (``INTERNAL``), which is precisely
   the collapse D2 exists to replace.
3. **Implementation bugs are hidden.** ``except Exception`` catches the
   ``AttributeError`` in the tool's own code exactly as readily as the timeout
   it was written for. LangChain's own guidance on ``wrap_tool_call`` is
   explicit about this — handle runtime input errors, let implementation bugs
   bubble — and it cannot bubble if the tool ate it first.

The fix per tool is one line: return
``ToolResult(ok=False, error=..., failure=Failure.<reason>)`` instead of a
string, and narrow the ``except`` to what the body actually expects. The
serialized bytes the model reads are identical (``ToolResult.serialize()``
renders ``"Error: <error>"``), so converting a tool is behaviour-preserving for
the model and outcome-preserving for everything else.

── Why this catches what it catches ──────────────────────────────────────────

The rule is deliberately narrow: **blanket** except (``Exception`` /
``BaseException`` / bare) AND a **bare string** return out of the handler. A
narrow ``except Workspace.DoesNotExist: return "no such workspace"`` is not
flagged — the author named the failure they expected, which is most of the
point. Nor is a blanket except that re-raises, logs, or returns a ``ToolResult``.
"""

from __future__ import annotations

import ast
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: The agent tool layer: the tool bodies and the agent classes that declare them.
#: Same two roots as F3, on purpose — one definition of "the tool layer".
SCANNED_ROOTS = (
    Path("components/agents/infrastructure/adapters/langchain/tools"),
    Path("components/agents/infrastructure/adapters/langchain/agents"),
)

#: Exception types that catch everything. A bare ``except:`` counts too.
BLANKET_EXCEPTION_NAMES = frozenset({"Exception", "BaseException"})

_TASK = "components/agents/infrastructure/adapters/langchain/tools/task_agent.py"
_PROJECT = "components/agents/infrastructure/adapters/langchain/tools/project_agent.py"
_USER = "components/agents/infrastructure/adapters/langchain/tools/user_agent.py"
_WORKSPACE = "components/agents/infrastructure/adapters/langchain/tools/workspace_agent.py"
_GOVERNANCE = "components/agents/infrastructure/adapters/langchain/agents/ai_governance_agent.py"
_POSTURE = "components/agents/infrastructure/adapters/langchain/agents/posture_agent.py"
_REPORT = "components/agents/infrastructure/adapters/langchain/agents/report_agent.py"

#: KNOWN, UNFIXED, and deliberately listed rather than silently tolerated.
#:
#: ``(module path, function name)``. **54 entries, down from 63** — ADR 0031
#: Phase 4 converted the nine bodies the OQ4 evidence found to be *live*:
#: ``user_agent``'s four (all of them), and the five ``task_agent`` functions
#: ``TriageAgent`` re-exports as ``assign_task`` / ``get_team_members`` /
#: ``get_members_without_tasks`` / ``list_open_findings`` / ``record_finding``.
#: Those five carry **874 recorded production calls** between them — they were
#: the only code in the CRUD fleet with any — so they are where a destroyed
#: failure reason actually costs something today.
#:
#: The distribution of what remains is still the finding: **41 are the inherited
#: nonprofit-shaped CRUD fleet** — ``task_agent`` (16), ``project_agent`` (19),
#: ``workspace_agent`` (6) — and **13 are security surface**:
#: ``ai_governance_agent`` (6), ``posture_agent`` (5), ``report_agent`` (2).
#: The security thirteen are the ones worth converting next. A governance read
#: that swallows its own bug and returns prose is a compliance answer nobody can
#: trust.
#:
#: See ``docs/architecture/AGENT_TOOL_USAGE_EVIDENCE_2026-08-20.md`` for why the
#: CRUD fleet is being converted rather than deleted: zero of its 53 tools has
#: ever been called, and it is still reachable, entitled by default, and the
#: configured ``agent_type`` default on three REST endpoints.
#:
#: This list is the remediation scope. **It may only ever shrink.** Adding an
#: entry so a failure goes away is the one thing it must not be used for.
KNOWN_BLANKET_STRING_HANDLERS: frozenset[tuple[str, str]] = frozenset(
    {
        # ── Security surface: convert these first ──
        (_GOVERNANCE, "get_ai_activity"),
        (_GOVERNANCE, "get_capability_grants"),
        (_GOVERNANCE, "get_credential_inventory"),
        (_GOVERNANCE, "get_governance_report"),
        (_GOVERNANCE, "get_hitl_ledger"),
        (_GOVERNANCE, "get_kill_switch_status"),
        (_POSTURE, "get_findings_posture"),
        (_POSTURE, "get_fleet_health"),
        (_POSTURE, "get_forward_outlook"),
        (_POSTURE, "get_posture_report"),
        (_POSTURE, "get_response_kpis"),
        (_REPORT, "_workspace_name"),
        (_REPORT, "generate_pentest_report"),
        # ── The inherited CRUD fleet: ADR 0031 Phase 4 / OQ4 ──
        (_PROJECT, "_calculate_duration"),
        (_PROJECT, "add_project_risk"),
        (_PROJECT, "assign_project_team"),
        (_PROJECT, "check_project_permissions"),
        (_PROJECT, "create_project"),
        (_PROJECT, "create_project_milestone"),
        (_PROJECT, "create_project_task"),
        (_PROJECT, "delete_project_milestone"),
        (_PROJECT, "generate_project_report"),
        (_PROJECT, "get_project_analytics"),
        (_PROJECT, "get_project_info"),
        (_PROJECT, "get_project_risks"),
        (_PROJECT, "get_project_tasks"),
        (_PROJECT, "get_project_timeline"),
        (_PROJECT, "list_projects"),
        (_PROJECT, "manage_project_budget"),
        (_PROJECT, "update_project"),
        (_PROJECT, "update_project_milestone"),
        (_PROJECT, "update_task_status"),
        (_TASK, "add_task_comment"),
        (_TASK, "break_down_task"),
        (_TASK, "delete_task"),
        (_TASK, "get_due_tasks"),
        (_TASK, "get_projects"),
        (_TASK, "get_task_assignment"),
        (_TASK, "get_task_progress"),
        (_TASK, "get_task_timer_status"),
        (_TASK, "get_user_tasks"),
        (_TASK, "list_task_comments"),
        (_TASK, "parse_task_request"),
        (_TASK, "start_task_timer"),
        (_TASK, "stop_task_timer"),
        (_TASK, "update_task_due_date"),
        (_TASK, "update_task_status"),
        (_TASK, "update_task_title"),
        (_WORKSPACE, "create_organization"),
        (_WORKSPACE, "manage_organization_operations"),
        (_WORKSPACE, "manage_organization_privacy"),
        (_WORKSPACE, "manage_organization_tags"),
        (_WORKSPACE, "manage_organization_team"),
        (_WORKSPACE, "update_organization"),
    }
)


def _module_paths() -> list[Path]:
    paths: list[Path] = []
    for scanned in SCANNED_ROOTS:
        directory = ROOT / scanned
        if not directory.exists():
            continue
        paths.extend(sorted(p for p in directory.rglob("*.py") if p.name != "__init__.py"))
    return paths


def _is_blanket(handler: ast.ExceptHandler) -> bool:
    """True for ``except:``, ``except Exception:``, ``except (Exception, X):``."""
    caught = handler.type
    if caught is None:  # bare `except:`
        return True
    candidates = list(caught.elts) if isinstance(caught, ast.Tuple) else [caught]
    return any(
        (getattr(node, "id", None) or getattr(node, "attr", None)) in BLANKET_EXCEPTION_NAMES for node in candidates
    )


def _returns_bare_string(handler: ast.ExceptHandler) -> bool:
    """True when the handler returns something that is plainly a string.

    Four shapes, which is every one the codebase actually uses:
    an f-string, a literal, string concatenation/``%`` formatting, and a
    ``str(...)`` / ``"...".format(...)`` call. A ``ToolResult(...)`` return is
    none of these, which is the whole distinction the rule draws.
    """
    for node in ast.walk(handler):
        if not isinstance(node, ast.Return) or node.value is None:
            continue
        value = node.value
        if isinstance(value, ast.JoinedStr):
            return True
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return True
        if isinstance(value, ast.BinOp) and isinstance(value.op, (ast.Add, ast.Mod)):
            return True
        if isinstance(value, ast.Call):
            name = getattr(value.func, "id", None) or getattr(value.func, "attr", None)
            if name in {"str", "format"}:
                return True
    return False


def _functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def find_blanket_string_handlers() -> set[tuple[str, str]]:
    """Every ``(module, function)`` in the tool layer that swallows everything
    into a bare string."""
    violations: set[tuple[str, str]] = set()

    for path in _module_paths():
        rel = path.relative_to(ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover — a syntax error is another test's job
            continue
        for function in _functions(tree):
            handlers = [n for n in ast.walk(function) if isinstance(n, ast.ExceptHandler)]
            if any(_is_blanket(h) and _returns_bare_string(h) for h in handlers):
                violations.add((rel, function.name))

    return violations


class TestToolBlanketExceptionF4:
    def test_no_new_tool_swallows_everything_into_a_string(self):
        """The ratchet. The 54 listed bodies are tolerated; a 55th is not."""
        found = find_blanket_string_handlers()
        new = sorted(found - KNOWN_BLANKET_STRING_HANDLERS)
        assert not new, (
            "A tool body catches `Exception` and returns a bare string, which destroys "
            "the failure reason and hides implementation bugs (ADR 0031 D2).\n\n"
            + "\n".join(f"  - {module}::{function}" for module, function in new)
            + "\n\nReturn `ToolResult(ok=False, error=..., failure=Failure.<reason>)` instead — "
            "the bytes the model reads are identical, and the outcome survives to the run "
            "status. Narrow the `except` to what the body actually expects; let the rest "
            "bubble. Do not add the entry to KNOWN_BLANKET_STRING_HANDLERS to make this pass."
        )

    def test_the_remediation_list_is_reported_every_run(self, capsys):
        """Warn, visibly. A list nobody sees is the same as no list."""
        found = find_blanket_string_handlers()
        outstanding = sorted(found & KNOWN_BLANKET_STRING_HANDLERS)
        if outstanding:
            message = (
                f"ADR 0031 F4 (warn mode): {len(outstanding)} tool body/bodies still swallow "
                "every exception into a bare string. Phase 3/4 remediation list:\n"
                + "\n".join(f"  - {module}::{function}" for module, function in outstanding)
            )
            warnings.warn(message, UserWarning, stacklevel=1)
            print(message)
        assert outstanding, (
            "KNOWN_BLANKET_STRING_HANDLERS matched nothing. Either the remediation "
            "landed — in which case delete the stale entries and flip F4 to fail mode "
            "— or the detector stopped detecting, which is worse."
        )

    def test_the_known_list_has_no_stale_entries(self):
        """An entry that no longer matches is a fix nobody noticed shipping. It
        must be deleted, so the list keeps meaning what it says."""
        found = find_blanket_string_handlers()
        stale = sorted(KNOWN_BLANKET_STRING_HANDLERS - found)
        assert not stale, (
            "These entries no longer match any code — the violation was fixed or the "
            "function was renamed. Remove them from KNOWN_BLANKET_STRING_HANDLERS:\n"
            + "\n".join(f"  - {module}::{function}" for module, function in stale)
        )

    def test_the_security_surface_is_the_short_head_of_the_list(self):
        """Guards the claim the docstring makes, so the "convert these first"
        note cannot quietly stop being true.

        If the CRUD fleet is ever converted or deleted (Phase 4 / OQ4), this
        assertion flips and the list needs re-reading rather than re-baselining.
        """
        crud_modules = {_TASK, _PROJECT, _USER, _WORKSPACE}
        crud = {entry for entry in KNOWN_BLANKET_STRING_HANDLERS if entry[0] in crud_modules}
        security = KNOWN_BLANKET_STRING_HANDLERS - crud
        assert len(crud) > len(security), (
            "The known-violation list is no longer dominated by the inherited CRUD "
            f"fleet ({len(crud)} CRUD vs {len(security)} security). Re-read the list and "
            "update the docstring's remediation ordering rather than adjusting this test."
        )


class TestTheDetectorActuallyDetects:
    """A fitness function that cannot fail is decoration."""

    @staticmethod
    def _handlers(source: str) -> list[ast.ExceptHandler]:
        return [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ExceptHandler)]

    def test_the_house_style_is_caught(self):
        source = "def t():\n    try:\n        x()\n    except Exception as exc:\n        return f'Error: {exc}'\n"
        handler = self._handlers(source)[0]
        assert _is_blanket(handler) and _returns_bare_string(handler)

    def test_a_bare_except_is_caught(self):
        source = "def t():\n    try:\n        x()\n    except:\n        return 'nope'\n"
        handler = self._handlers(source)[0]
        assert _is_blanket(handler) and _returns_bare_string(handler)

    def test_a_tuple_containing_exception_is_caught(self):
        source = "def t():\n    try:\n        x()\n    except (ValueError, Exception):\n        return 'nope'\n"
        assert _is_blanket(self._handlers(source)[0]) is True

    def test_a_narrow_except_returning_a_string_is_not_a_violation(self):
        """The author named the failure they expected. That is most of the point
        of D2 — flagging it would push contributors toward broader excepts."""
        source = (
            "def t():\n    try:\n        x()\n    except Workspace.DoesNotExist:\n        return 'no such workspace'\n"
        )
        assert _is_blanket(self._handlers(source)[0]) is False

    def test_a_blanket_except_returning_a_tool_result_is_not_a_violation(self):
        """The target shape. A tool that classifies its own failure keeps the
        reason, and the run status can act on it."""
        source = (
            "def t():\n"
            "    try:\n"
            "        x()\n"
            "    except Exception as exc:\n"
            "        logger.exception('boom')\n"
            "        return ToolResult(ok=False, error=str(exc), failure=Failure.INTERNAL)\n"
        )
        handler = self._handlers(source)[0]
        assert _is_blanket(handler) is True
        assert _returns_bare_string(handler) is False

    def test_a_blanket_except_that_re_raises_is_not_a_violation(self):
        source = (
            "def t():\n    try:\n        x()\n    except Exception:\n        logger.exception('boom')\n        raise\n"
        )
        assert _returns_bare_string(self._handlers(source)[0]) is False

    def test_the_scan_finds_the_tool_layer_at_all(self):
        """A scanner that finds nothing would make the rule vacuously true."""
        found = find_blanket_string_handlers()
        assert len(found) >= 40, (
            f"the F4 scan found only {len(found)} handlers — the tool layer moved or the AST shapes changed"
        )
