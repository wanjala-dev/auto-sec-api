"""Fitness function F3 (ADR 0031 D1) — a tool must not take its tenant from the model.

**Fail mode, since ADR 0031 Phase 3.** There is no allowlist. A tool body that
resolves its workspace/organization from its own payload fails this test, and
adding an entry to make it pass is not an available move — the entry would have
to be a new constant, in a diff, with a reviewer looking at it.

It shipped in warn mode alongside Phase 2, naming fourteen violations every run:
``workspace_agent._resolve_org_id`` and ``_extract_identifier``, their eleven
call sites, and ``project_agent.check_project_permissions``. Phase 3 fixed all
fourteen; this is the same detector with the allowlist deleted.

── What the rule is ──────────────────────────────────────────────────────────

autosec is single-database for pooled tenants; tenant isolation is enforced in
application code by filtering on ``workspace_id``. A missing filter IS a
cross-tenant data leak, with no database boundary behind it to catch you.

So under D1 the workspace id reaches a tool from the run, never from the model —
``agent.workspace_id``, bound when the run is created from the authenticated
request. This test is the source-level half: no tool body may read a
workspace/organization key out of its payload, whether directly or through a
helper that does it on its behalf.

The framework halves are ``_tenancy_scoped`` (the promotion loop) and
``ToolGovernanceMiddleware._strip_tenancy_args`` (every tool, however
registered), both driven by ``application/policies/tool_tenancy.py``. They mean
a body that violated this rule could not succeed anyway. This test is what stops
one being written, and — more to the point — stops the *next* one being written
by an author copying a neighbouring tool.

── Why the fixed violations were not merely careless ─────────────────────────

``_resolve_org_id`` was a considered helper with a thoughtful docstring citing a
real 2026-05-08 incident, written by someone solving a genuine problem: the LLM
kept omitting the id, so the tool defaulted to the agent's workspace. It was
*still* a cross-tenant escape hatch, and it was advertised to the model in the
tool descriptions that mentioned ``organization_id``. That is the argument for
construction over discipline — the discipline was present and the outcome was
wrong anyway.

Detection is one hop deep: a function that reads a tenancy key out of a dict is
a "payload tenancy reader", and so is any function that calls one. That found
``_resolve_org_id``'s call sites by following the code rather than by
hard-coding the helper's name, so a rename does not blind the rule.
"""

from __future__ import annotations

import ast
from pathlib import Path

from components.agents.application.policies.tool_tenancy import TENANCY_SOURCE_KEYS

ROOT = Path(__file__).resolve().parents[2]

#: The agent tool layer: the tool bodies and the agent classes that declare them.
SCANNED_ROOTS = (
    Path("components/agents/infrastructure/adapters/langchain/tools"),
    Path("components/agents/infrastructure/adapters/langchain/agents"),
)

#: Payload keys that carry a tenant identity. Imported rather than restated so
#: the rule, the promotion-loop wrapper and the middleware cannot disagree about
#: what a tenancy key is.
TENANCY_KEYS = TENANCY_SOURCE_KEYS


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
    read its keys from a loop::

        for key in ("organization_id", "workspace_id", "id"):
            candidate = _coerce_uuid(data.get(key))

    A detector that only matched ``data.get("workspace_id")`` literally would
    have missed the single most consequential violation in the codebase — and
    with it all ten of its call sites. So the rule is: the function mentions a
    tenancy key as a string it does not merely write, and it reads a mapping.
    That is broader than strictly necessary and deliberately so; the exemptions
    above are what keep it from being noisy.
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


def _payload_tenancy_reads_in(rel: str, source: str) -> set[tuple[str, str]]:
    """The ``(module, function)`` violations in one module's *source*.

    Split out from ``find_payload_tenancy_reads`` so the one-hop walk can be
    proven against synthetic source. With the real violations fixed there is
    nothing left in the tree to demonstrate it on, and an unproven detector is
    the failure mode this whole file exists to avoid.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:  # pragma: no cover — a syntax error is another test's job
        return set()

    functions = _functions(tree)
    direct = {fn.name for fn in functions if _reads_tenancy_key(fn)}
    violations: set[tuple[str, str]] = {(rel, name) for name in direct}

    # One hop: a caller of a direct reader is taking the same escape hatch, it is
    # just doing it through the helper. Following the call graph rather than
    # naming the helper keeps the rule alive across a rename.
    for fn in functions:
        if fn.name in direct:
            continue
        if _called_names(fn) & direct:
            violations.add((rel, fn.name))

    return violations


def find_payload_tenancy_reads() -> set[tuple[str, str]]:
    """Every ``(module, function)`` in the tool layer that takes its tenant from
    the payload — directly, or through a helper in the same module that does."""
    violations: set[tuple[str, str]] = set()
    for path in _module_paths():
        violations |= _payload_tenancy_reads_in(
            path.relative_to(ROOT).as_posix(),
            path.read_text(encoding="utf-8"),
        )
    return violations


def _tool_descriptions() -> list[tuple[str, str, str]]:
    """``(module, tool_name, description)`` for every ``@tool(...)`` declaration.

    Only literal descriptions — a description assembled at runtime is out of
    reach of an AST scan, and there are none today.
    """
    found: list[tuple[str, str, str]] = []
    for path in _module_paths():
        rel = path.relative_to(ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if called != "tool":
                continue
            kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
            description = kwargs.get("description")
            try:
                text = ast.literal_eval(description) if description is not None else None
            except (ValueError, TypeError):
                text = None
            if not isinstance(text, str):
                continue
            name = kwargs.get("name")
            try:
                tool_name = ast.literal_eval(name) if name is not None else "<unnamed>"
            except (ValueError, TypeError):
                tool_name = "<unnamed>"
            found.append((rel, str(tool_name), text))
    return found


class TestToolPayloadTenancyF3:
    def test_no_tool_takes_its_tenant_from_the_model(self):
        """F3, in fail mode. Zero tolerance, no allowlist."""
        found = sorted(find_payload_tenancy_reads())
        assert not found, (
            "A tool is resolving its workspace/organization from its own payload, "
            "which lets the model choose the tenant (ADR 0031 D1).\n\n"
            + "\n".join(f"  - {module}::{function}" for module, function in found)
            + "\n\nTake the tenant from the run instead — `agent.workspace_id` — and "
            "delete the payload read. Do not add an allowlist to make this pass; the "
            "fourteen entries this test used to tolerate are exactly what Phase 3 removed."
        )

    def test_no_tool_description_advertises_a_tenancy_parameter(self):
        """The other half of the same hole, and the one that is easy to forget.

        Removing the trust without removing the advertisement leaves the model
        still supplying the value. Eleven descriptions asked for one —
        ``organization_id`` on ten workspace tools and ``workspace_id`` on
        ``check_project_permissions`` — and a description is bytes the model
        reads and acts on. A stale one is now harmless (the framework strips the
        key) but it still spends tokens teaching the model a call shape that
        does nothing, and it is how the next tool author learns the old pattern.
        """
        offenders = [
            (module, tool_name, key)
            for module, tool_name, description in _tool_descriptions()
            for key in sorted(TENANCY_KEYS)
            if key in description
        ]
        assert not offenders, (
            "A tool description tells the model it may supply a workspace/organization "
            "id. It may not — the framework strips the key and the tool reads the run's "
            "bound workspace (ADR 0031 D1).\n\n"
            + "\n".join(f"  - {module}::{tool_name} advertises {key!r}" for module, tool_name, key in offenders)
            + "\n\nRewrite the description to say the tool always acts on the current workspace."
        )

    def test_the_detector_actually_detects(self):
        """A fitness function that cannot fail is decoration. Prove the AST
        walk fires on both shapes it is meant to catch."""
        direct = ast.parse(
            "def t(agent, payload):\n    data = coerce(payload)\n    return Workspace.objects.get(id=data['workspace_id'])\n"
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
            "the loop form is how _resolve_org_id read its keys — missing it "
            "would have hidden the violation this rule exists for, and all ten of its call sites"
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

    def test_a_helper_and_its_call_sites_are_both_found(self):
        """The one-hop walk is what made the ten call sites visible; a
        direct-read-only detector would have reported the helper alone and
        understated the remediation by an order of magnitude.

        Proven on synthetic source because the real instance is fixed — the
        capability has to outlive the violation that motivated it, or the next
        helper of the same shape is reported as one problem instead of eleven.
        """
        source = (
            "def _resolve(data, agent):\n"
            "    for key in ('organization_id', 'workspace_id'):\n"
            "        if data.get(key):\n"
            "            return data.get(key)\n"
            "    return agent.workspace_id\n"
            "\n"
            "def a_tool(agent, payload):\n"
            "    return _resolve(coerce(payload), agent)\n"
            "\n"
            "def unrelated_tool(agent, payload):\n"
            "    return Finding.objects.filter(workspace_id=agent.workspace_id)\n"
        )
        found = _payload_tenancy_reads_in("synthetic.py", source)
        assert ("synthetic.py", "_resolve") in found, "the direct reader must be found"
        assert ("synthetic.py", "a_tool") in found, "its caller takes the same escape hatch, one hop away"
        assert ("synthetic.py", "unrelated_tool") not in found, "a correctly-scoped tool must not be flagged"

    def test_the_bound_workspace_helper_replaced_the_payload_one(self):
        """The specific regression. ``_resolve_org_id`` is gone, and the helper
        that replaced it does not take a payload at all — so there is no
        argument a future edit could reach for."""
        import inspect

        from components.agents.infrastructure.adapters.langchain.tools import workspace_agent as workspace_tools

        assert not hasattr(workspace_tools, "_resolve_org_id"), (
            "_resolve_org_id is the helper this phase deleted; if it is back, so is the hole"
        )
        assert not hasattr(workspace_tools, "_extract_identifier"), (
            "_extract_identifier resolved a workspace by NAME across every tenant"
        )
        params = list(inspect.signature(workspace_tools._bound_workspace_id).parameters)
        assert params == ["agent"], (
            f"_bound_workspace_id must take only the agent, got {params!r} — a payload "
            "parameter is the seam the old helper's cross-tenant preference lived in"
        )
