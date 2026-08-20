"""Fitness function F3 (ADR 0031 D1) — a tool must not take its tenant from the model.

**Warn mode.** This test does not fail on the violations that exist today; it
names them, every run, as an explicit remediation list. It *does* fail on a new
one. Flipping it to fail outright is ADR 0031 Phase 3 and requires fixing the
call sites below first.

The list existing rather than being notional is the point. ADR 0031 names one
risk against itself:

    "The main one is that Phase 1's observe-only mode becomes permanent — the
    middleware lands, nothing is ever enforced, and we have added a layer
    without removing a bug class."

Its mitigation is that "F3 should be scheduled with Phase 2 rather than
deferred". This is that. The ratchet — warn on the known, fail on the new — is
what stops warn mode being the same trap in a different shape.

── What the rule is ──────────────────────────────────────────────────────────

autosec is single-database for pooled tenants; tenant isolation is enforced in
application code by filtering on ``workspace_id``. A missing filter IS a
cross-tenant data leak, with no database boundary behind it to catch you.

So under D1 the workspace id reaches a tool through the runtime, never through
the tool's args schema — a tenant id the model cannot write is a tenant id the
model cannot cross. This test is the other half: no tool body may read a
workspace/organization key out of its payload, whether directly or through a
helper that does it on its behalf.

── Why the existing violations are not merely careless ───────────────────────

``_resolve_org_id`` is a considered helper with a thoughtful docstring citing a
real 2026-05-08 incident, written by someone solving a genuine problem: the LLM
kept omitting the id, so the tool defaulted to the agent's workspace. It is
*still* a cross-tenant escape hatch, and it is advertised to the model in the
tool descriptions that mention ``organization_id``. That is the argument for
construction over discipline — the discipline was present and the outcome was
wrong anyway.

Detection is one hop deep: a function that reads a tenancy key out of a dict is
a "payload tenancy reader", and so is any function that calls one. That finds
``_resolve_org_id``'s call sites by following the code rather than by
hard-coding the helper's name, so renaming it does not blind the rule.
"""

from __future__ import annotations

import ast
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: The agent tool layer: the tool bodies and the agent classes that declare them.
SCANNED_ROOTS = (
    Path("components/agents/infrastructure/adapters/langchain/tools"),
    Path("components/agents/infrastructure/adapters/langchain/agents"),
)

#: Payload keys that carry a tenant identity. A tool reading any of these out of
#: its own arguments is taking its tenant from the model.
TENANCY_KEYS = frozenset({"workspace_id", "organization_id"})

#: KNOWN, UNFIXED, and deliberately listed rather than silently tolerated.
#:
#: ``(module path, function name)``. Every entry is a tool body — or a helper a
#: tool body calls — that resolves its tenant from the model's arguments.
#: Fixing them is ADR 0031 Phase 3 (bind the workspace through ``ToolRuntime``
#: and delete the payload read); this list is the remediation scope for that
#: work, not a place to add entries so a failure goes away.
#:
#: ``workspace_agent._resolve_org_id`` + its TEN call sites: the helper prefers
#: an ``organization_id`` supplied by the model over the agent's bound
#: workspace, falling back to ``agent.workspace_id`` only when the model
#: supplied nothing parseable. ``_extract_identifier`` is the same shape, and
#: ``get_organization_info`` is its one caller.
#:
#: ``project_agent.check_project_permissions`` is the sharpest of them: it does
#: ``Workspace.objects.get(id=data["workspace_id"])`` with no fallback and no
#: comparison against ``agent.workspace_id`` at all, so the workspace it
#: reports permissions for is whichever one the model names.
_WORKSPACE_TOOLS = "components/agents/infrastructure/adapters/langchain/tools/workspace_agent.py"
_PROJECT_TOOLS = "components/agents/infrastructure/adapters/langchain/tools/project_agent.py"

KNOWN_PAYLOAD_TENANCY_READS: frozenset[tuple[str, str]] = frozenset(
    {
        # ── The helpers that do the payload read ──
        (_WORKSPACE_TOOLS, "_resolve_org_id"),
        (_WORKSPACE_TOOLS, "_extract_identifier"),
        # ── `_resolve_org_id`'s ten call sites: the Phase 3 remediation list ──
        (_WORKSPACE_TOOLS, "update_organization"),
        (_WORKSPACE_TOOLS, "manage_organization_team"),
        (_WORKSPACE_TOOLS, "get_organization_analytics"),
        (_WORKSPACE_TOOLS, "manage_organization_categories"),
        (_WORKSPACE_TOOLS, "manage_organization_tags"),
        (_WORKSPACE_TOOLS, "get_organization_followers"),
        (_WORKSPACE_TOOLS, "manage_organization_privacy"),
        (_WORKSPACE_TOOLS, "get_organization_operations"),
        (_WORKSPACE_TOOLS, "manage_organization_operations"),
        (_WORKSPACE_TOOLS, "check_organization_permissions"),
        # ── `_extract_identifier`'s one call site ──
        (_WORKSPACE_TOOLS, "get_organization_info"),
        # ── A direct read with no fallback at all ──
        (_PROJECT_TOOLS, "check_project_permissions"),
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


#: ``getattr(agent, "workspace_id", None)`` is the CORRECT read — it takes the
#: tenant from the agent, not the payload. A tenancy key inside one of these is
#: never a violation, and excluding them is what keeps the rule from flagging
#: ~10 correctly-scoped list tools in ``task_agent`` / ``user_agent`` /
#: ``project_agent``.
ATTRIBUTE_ACCESS_BUILTINS = frozenset({"getattr", "hasattr", "setattr", "delattr"})


def _exempt_constant_ids(node: ast.AST) -> set[int]:
    """Ids of string constants that are not payload reads.

    Two shapes: a key being *written* into a dict literal, and the name argument
    of ``getattr``/``hasattr``/``setattr``.
    """
    exempt: set[int] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Dict):
            exempt.update(id(key) for key in child.keys if isinstance(key, ast.Constant))
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id in ATTRIBUTE_ACCESS_BUILTINS
        ):
            exempt.update(id(arg) for arg in child.args if isinstance(arg, ast.Constant))
    return exempt


def _reads_tenancy_key(node: ast.AST) -> bool:
    """True when *node* names a tenancy key AND reads out of a mapping.

    Two signals, because the direct form is not the only one. ``_resolve_org_id``
    reads its keys from a loop::

        for key in ("organization_id", "workspace_id", "id"):
            candidate = _coerce_uuid(data.get(key))

    A detector that only matched ``data.get("workspace_id")`` literally would
    miss the single most consequential violation in the codebase — and with it
    all ten of its call sites. So the rule is: the function mentions a tenancy
    key as a string it does not merely write, and it reads a mapping. That is
    broader than strictly necessary and deliberately so; the exemptions above
    are what keep it from being noisy.
    """
    exempt = _exempt_constant_ids(node)
    names_a_tenancy_key = any(
        isinstance(child, ast.Constant)
        and isinstance(child.value, str)
        and child.value in TENANCY_KEYS
        and id(child) not in exempt
        for child in ast.walk(node)
    )
    if not names_a_tenancy_key:
        return False

    for child in ast.walk(node):
        # data.get(<anything>)
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr == "get"
            and child.args
        ):
            return True
        # data[<anything>], read side only
        if isinstance(child, ast.Subscript) and isinstance(child.ctx, ast.Load):
            return True
    return False


def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def _functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def find_payload_tenancy_reads() -> set[tuple[str, str]]:
    """Every ``(module, function)`` in the tool layer that takes its tenant from
    the payload — directly, or through a helper in the same module that does."""
    violations: set[tuple[str, str]] = set()

    for path in _module_paths():
        rel = path.relative_to(ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover — a syntax error is another test's job
            continue

        functions = _functions(tree)
        direct = {fn.name for fn in functions if _reads_tenancy_key(fn)}
        violations.update((rel, name) for name in direct)

        # One hop: a caller of a direct reader is taking the same escape hatch,
        # it is just doing it through the helper. Following the call graph
        # rather than naming the helper keeps the rule alive across a rename.
        for fn in functions:
            if fn.name in direct:
                continue
            if _called_names(fn) & direct:
                violations.add((rel, fn.name))

    return violations


class TestToolPayloadTenancyF3:
    def test_no_new_tool_takes_its_tenant_from_the_model(self):
        """The ratchet. Warn mode tolerates the listed violations; it does not
        tolerate an eleventh."""
        found = find_payload_tenancy_reads()
        new = sorted(found - KNOWN_PAYLOAD_TENANCY_READS)
        assert not new, (
            "A tool is resolving its workspace/organization from its own payload, "
            "which lets the model choose the tenant (ADR 0031 D1).\n\n"
            + "\n".join(f"  - {module}::{function}" for module, function in new)
            + "\n\nBind the workspace through the run instead of accepting it as a tool "
            "argument. Do not add the entry to KNOWN_PAYLOAD_TENANCY_READS to make this pass."
        )

    def test_the_remediation_list_is_reported_every_run(self, capsys):
        """Warn, visibly. A list nobody sees is the same as no list."""
        found = find_payload_tenancy_reads()
        outstanding = sorted(found & KNOWN_PAYLOAD_TENANCY_READS)
        if outstanding:
            message = (
                f"ADR 0031 F3 (warn mode): {len(outstanding)} tool(s) still resolve their "
                "tenant from the model's payload. Phase 3 remediation list:\n"
                + "\n".join(f"  - {module}::{function}" for module, function in outstanding)
            )
            warnings.warn(message, UserWarning, stacklevel=1)
            print(message)
        assert outstanding, (
            "KNOWN_PAYLOAD_TENANCY_READS matched nothing. Either the remediation "
            "landed — in which case delete the stale entries and flip F3 to fail "
            "mode (Phase 3) — or the detector stopped detecting, which is worse."
        )

    def test_the_known_list_has_no_stale_entries(self):
        """An entry that no longer matches is a fix nobody noticed shipping. It
        must be deleted, so the list keeps meaning what it says."""
        found = find_payload_tenancy_reads()
        stale = sorted(KNOWN_PAYLOAD_TENANCY_READS - found)
        assert not stale, (
            "These entries no longer match any code — the violation was fixed or "
            "the function was renamed. Remove them from KNOWN_PAYLOAD_TENANCY_READS:\n"
            + "\n".join(f"  - {module}::{function}" for module, function in stale)
        )

    def test_the_detector_actually_detects(self):
        """A fitness function that cannot fail is decoration. Prove the AST
        walk fires on both shapes it is meant to catch."""
        direct = ast.parse(
            "def t(agent, payload):\n"
            "    data = coerce(payload)\n"
            "    return Workspace.objects.get(id=data['workspace_id'])\n"
        )
        assert _reads_tenancy_key(_functions(direct)[0]) is True

        via_get = ast.parse("def t(agent, payload):\n    return data.get('organization_id')\n")
        assert _reads_tenancy_key(_functions(via_get)[0]) is True

        iterated = ast.parse(
            "def t(agent, payload):\n"
            "    for key in ('organization_id', 'workspace_id', 'id'):\n"
            "        if data.get(key):\n"
            "            return data.get(key)\n"
        )
        assert _reads_tenancy_key(_functions(iterated)[0]) is True, (
            "the loop form is how _resolve_org_id reads its keys — missing it "
            "would hide the violation this rule exists for, and all ten of its call sites"
        )

        clean = ast.parse(
            "def t(agent, payload):\n    return Finding.objects.filter(workspace_id=agent.workspace_id)\n"
        )
        assert _reads_tenancy_key(_functions(clean)[0]) is False

        correctly_scoped = ast.parse(
            "def t(agent, payload):\n"
            "    data = coerce(payload)\n"
            "    if not getattr(agent, 'workspace_id', None):\n"
            "        return 'no workspace'\n"
            "    return Task.objects.filter(workspace_id=agent.workspace_id, status=data.get('status'))\n"
        )
        assert _reads_tenancy_key(_functions(correctly_scoped)[0]) is False, (
            "taking the tenant from the agent is the CORRECT shape; flagging it "
            "would bury the real violations under ~10 false positives"
        )

    def test_the_helper_and_its_call_sites_are_both_found(self):
        """The one-hop walk is what makes the ten call sites visible; a
        direct-read-only detector would report the helper alone and understate
        the remediation by an order of magnitude."""
        found = find_payload_tenancy_reads()
        module = _WORKSPACE_TOOLS
        assert (module, "_resolve_org_id") in found
        callers = {
            function
            for path, function in found
            if path == module and function not in {"_resolve_org_id", "_extract_identifier"}
        }
        assert len(callers) >= 10, callers
