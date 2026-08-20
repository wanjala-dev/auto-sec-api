"""ADR 0031 Phase 4 — the inherited CRUD fleet now carries a full declaration.

`task_agent` (22 tools), `project_agent` (15), `workspace_agent` (12) and
`user_agent` (4) were **53 registered tools with no `scope`, no `risk`, no
`provenance` and no `failure_mode`** — the largest undeclared surface in the
system, and the one furthest from anybody's attention.

`docs/architecture/AGENT_TOOL_USAGE_EVIDENCE_2026-08-20.md` answers OQ4 with the
measurement: **zero of the 53 has ever been called**, and they are nonetheless
reachable, entitled by default (`resolve_agent_entitlement` is opt-*out*), and
the configured `agent_type` default on three REST endpoints. Unused-but-reachable
code that is one HTTP request from executing is exactly the code that should be
declared, so this is a conversion rather than a deletion.

These tests pin what the conversion asserted, in three groups:

1. **Completeness** — every one of the 53 declares all four fields. This is F1
   (ADR 0031) applied to one fleet ahead of the global flip, so the fleet cannot
   silently regress to `UNDECLARED` while the rest of Phase 3 lands.
2. **Honesty** — the risk tiers say what the bodies do. The count that motivated
   this is pinned as a literal: 25 of the 53 write, and every one of them
   resolved to `read` before this change because `resolve_tool_risk` falls back
   to `read` and none of them set `risk=`.
3. **Behaviour did not move** — a declaration is metadata. The tool definition
   the model is offered must be byte-identical with and without it.
"""

from __future__ import annotations

import pytest

from components.agents.application.policies.tool_risk import (
    ToolRisk,
    autonomous_may_execute,
    requires_human_approval,
    resolve_tool_risk,
)
from components.agents.application.policies.tool_spec import Failure, Provenance, Scope

pytestmark = pytest.mark.unit


#: Tools inherited from `WorkspaceContextMixin` / `WorkspaceRetrievalMixin`.
#: They belong to the mixins, are declared there, and are not this fleet's.
_SHARED = frozenset({"whoami", "get_workspace_info", "retrieve_workspace_context"})

_FLEET = ("task_agent", "project_agent", "workspace_agent", "user_agent")

#: Every tool in the fleet that CHANGES STATE, and therefore must not resolve to
#: `read`. Written out rather than derived from a name heuristic: a heuristic
#: that says "manage_* writes" would have missed `assign_task` and would silently
#: stop covering a tool the day someone renames it.
WRITE_TOOLS = frozenset(
    {
        # task_agent
        "create_task",
        "break_down_task",
        "assign_task",
        "update_task_status",
        "update_task_due_date",
        "update_task_title",
        "delete_task",
        "add_task_comment",
        "start_task_timer",
        "stop_task_timer",
        # project_agent
        "create_project",
        "update_project",
        "assign_project_team",
        "create_project_task",
        "create_project_milestone",
        "update_project_milestone",
        "delete_project_milestone",
        "manage_project_budget",
        # workspace_agent
        "create_organization",
        "update_organization",
        "manage_organization_team",
        "manage_organization_categories",
        "manage_organization_tags",
        "manage_organization_privacy",
        "manage_organization_operations",
    }
)


def _fleet_tools() -> dict[str, dict]:
    """`{tool_name: meta}` for every tool the four CRUD agents declare themselves.

    Reads `_decorated_tools` off the registered classes — the list
    `BaseAgent.__init_subclass__` builds at class-definition time. No
    instantiation and no ORM, so this stays clean under the unit conftest.
    """
    from components.agents.infrastructure.adapters.langchain.base import AgentRegistry

    collected: dict[str, dict] = {}
    for slug in _FLEET:
        agent_class = AgentRegistry.get_agent_class(slug)
        assert agent_class is not None, (
            f"{slug!r} is not in AgentRegistry. Agent discovery imports the module and "
            "SWALLOWS ImportError/SyntaxError, so a broken agent disappears from the "
            "registry silently rather than failing the boot — which is how this very "
            "change nearly shipped with two agents missing."
        )
        for method_name, meta in agent_class._decorated_tools:
            name = meta.get("name") or method_name
            if name not in _SHARED:
                collected[name] = meta
    return collected


class TestEveryCrudToolDeclaresItself:
    """Group 1 — completeness. F1, scoped to this fleet, ahead of the global flip."""

    def test_the_fleet_is_the_size_the_evidence_measured(self):
        assert len(_fleet_tools()) == 53, (
            "The CRUD fleet changed size. The OQ4 evidence document counts 53 "
            "(task 22, project 15, workspace 12, user 4); update it in the same "
            "change, because its verdicts are per-tool."
        )

    @pytest.mark.parametrize("field", ["scope", "risk", "provenance", "failure_mode"])
    def test_no_tool_is_missing_a_declaration_field(self, field):
        missing = sorted(name for name, meta in _fleet_tools().items() if getattr(meta["spec"], field, None) is None)
        assert missing == [], (
            f"These CRUD tools declare no {field!r}, so they fall back to "
            f"`tool_spec.UNDECLARED` — which asserts nothing and gates nothing:\n"
            + "\n".join(f"  - {name}" for name in missing)
        )

    def test_every_declared_value_is_from_the_vocabulary(self):
        """A typo'd string is worse than no declaration — it reads as a decision."""
        for name, meta in _fleet_tools().items():
            spec = meta["spec"]
            assert spec.scope in Scope.ALL, f"{name}: scope={spec.scope!r}"
            assert spec.risk in ToolRisk.ALL, f"{name}: risk={spec.risk!r}"
            assert spec.provenance in Provenance.ALL, f"{name}: provenance={spec.provenance!r}"
            assert spec.failure_mode in Failure.ALL, f"{name}: failure_mode={spec.failure_mode!r}"

    def test_provenance_is_none_across_the_fleet_and_that_is_the_honest_answer(self):
        """Not one CRUD tool posts to the board, including the 25 that write.

        Declaring `NONE` records today's behaviour exactly. It deliberately does
        **not** pre-empt OQ3 (does "every AI action posts to the board" bind every
        state-changing tool, or only board-acting specialists?) — that is Henry's
        product call, and when it lands these are the declarations it changes.
        """
        non_none = sorted(n for n, m in _fleet_tools().items() if m["spec"].provenance != Provenance.NONE)
        assert non_none == []


class TestTheRiskTiersAreHonest:
    """Group 2 — the defect this conversion actually fixes.

    `resolve_tool_risk` falls back to `read`, and before this change all 53 set
    no `risk=`. So 25 state-changing tools — including one that creates a tenant
    — were gated as reads. `tool_risk.py`'s own module docstring names this as
    the failure it exists to prevent: *"when in doubt, classify UP."*
    """

    def test_no_write_tool_resolves_to_read(self):
        tools = _fleet_tools()
        under = sorted(
            name for name in WRITE_TOOLS if resolve_tool_risk(name, tools[name]["spec"].risk) == ToolRisk.READ
        )
        assert under == [], f"state-changing tools gated as reads: {under}"

    def test_the_write_set_is_exactly_the_non_read_set(self):
        """Both directions. A read mislabelled as a write is a false alarm that
        trains people to ignore the tier; a write mislabelled as a read is the
        bug above."""
        tools = _fleet_tools()
        non_read = {n for n, m in tools.items() if resolve_tool_risk(n, m["spec"].risk) != ToolRisk.READ}
        assert non_read == WRITE_TOOLS

    def test_twenty_five_tools_were_writes_wearing_a_read_tier(self):
        """The count, as a literal, because it is the number in the PR."""
        assert len(WRITE_TOOLS) == 25

    def test_reversible_write_changes_no_gate_which_is_why_it_is_safe_here(self):
        """24 of the 25 became `reversible_write`, and that is behaviour-neutral:
        the autonomy cap and the approval gate both treat `read` and
        `reversible_write` identically today. The tier becomes *true* without
        changing what runs — which is the whole reason it could be corrected in a
        conversion rather than waiting for a policy decision."""
        for tier in (ToolRisk.READ, ToolRisk.REVERSIBLE_WRITE):
            assert autonomous_may_execute(tier) is True
            assert requires_human_approval(tier) is False


class TestCreateOrganizationIsTheOneDeliberateGate:
    """`create_organization` creates a NEW TENANT from chat — a `Workspace` row
    with `privacy` defaulting to `"public"`, owned by the agent's user — and it
    resolved to `read`.

    Raising it to `irreversible` DOES change behaviour, on purpose: ADR 0031 D8
    says a tier may be raised at any time, and this is the conservative interim
    while its deletion is decided (it is the top trim candidate in the OQ4
    evidence). It is also the only tool in the system declaring
    `Scope.CROSS_WORKSPACE` — which D1 reserves for staff/support surfaces and
    says "adding one is a security review". The declaration makes that visible
    instead of letting a tenant-creating tool wear `WORKSPACE_BOUND`, which would
    have been a false statement.
    """

    @pytest.fixture()
    def spec(self):
        return _fleet_tools()["create_organization"]["spec"]

    def test_it_is_irreversible(self, spec):
        assert resolve_tool_risk("create_organization", spec.risk) == ToolRisk.IRREVERSIBLE

    def test_an_autonomous_run_may_not_create_a_tenant(self, spec):
        assert autonomous_may_execute(spec.risk) is False

    def test_a_human_must_approve_it(self, spec):
        assert requires_human_approval(spec.risk) is True

    def test_it_is_the_only_cross_workspace_tool_in_the_fleet(self, spec):
        assert spec.scope == Scope.CROSS_WORKSPACE
        others = sorted(
            n
            for n, m in _fleet_tools().items()
            if n != "create_organization" and m["spec"].scope != Scope.WORKSPACE_BOUND
        )
        assert others == []


class TestTheDeclarationMovedNoModelVisibleByte:
    """Group 3 — a declaration is metadata the framework reads, never the model.

    Same argument as `test_tool_failure_semantics.py::TestTheModelVisibleBytesDidNotMove`:
    the tool *definition* offered to the LLM is `name` + `description` +
    `args_schema`, and `scope` / `risk` / `provenance` / `failure_mode` are none
    of those. Asserted against the real converter rather than by inspection, so a
    future change to how `@tool` builds its metadata cannot pass this by moving
    both sides at once.
    """

    def test_the_declaration_does_not_reach_the_tool_metadata_the_model_reads(self):
        from components.agents.infrastructure.adapters.langchain.base import tool as tool_decorator

        def probe(self, input_str: str = "") -> str:
            """A probe."""
            return "ok"

        bare = tool_decorator(name="probe", description="A probe.")(probe)._agent_tool_meta
        declared = tool_decorator(
            name="probe",
            description="A probe.",
            scope=Scope.WORKSPACE_BOUND,
            risk=ToolRisk.REVERSIBLE_WRITE,
            provenance=Provenance.NONE,
            failure_mode=Failure.INVALID_INPUT,
        )(probe)._agent_tool_meta

        model_visible = ("name", "description", "args_schema")
        assert {k: bare[k] for k in model_visible} == {k: declared[k] for k in model_visible}

    def test_the_fleet_descriptions_never_mention_the_declaration_vocabulary(self):
        """The values are policy, not prose. If one leaked into a description the
        model would start reasoning about its own risk tier."""
        vocabulary = set(Scope.ALL) | set(Provenance.ALL) | set(Failure.ALL)
        leaked = sorted(
            f"{name}:{token}"
            for name, meta in _fleet_tools().items()
            for token in vocabulary
            if token in (meta.get("description") or "")
        )
        assert leaked == []
