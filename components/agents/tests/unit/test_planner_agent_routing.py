"""Planner specialist routing — must not silently mis-route to workspace_agent.

The 2026-05-08 cascade had a follow-up: after the structured-tool +
list-tool fixes, the chat agent could correctly answer "how many tasks
do we have?" (routed to task_agent) and "who is assigned to those
tasks?" (also task_agent), but a follow-up "can you assign those to
me?" got routed to ``workspace_agent`` — which has no task tools and
fabricated a workspace overview instead.

Root cause: the planner system prompt enumerated routing rules for
budget / donation / financial / sponsorship / fundraising / project
/ workspace agents, but **omitted task_agent entirely**. And
workspace_agent's catalog summary mentioned "team membership" — the
planner LLM matched "assign tasks to me" to that magnet and picked
workspace_agent.

These tests pin the routing rules + summary so the gap can't reopen.
"""

from __future__ import annotations

import re

import pytest

from components.agents.infrastructure.adapters.langchain.agents.workspace_agent import (
    WorkspaceAgent,
)
from components.agents.infrastructure.adapters.langchain.deep import llm_planner


class TestSystemPromptRoutingRules:
    """Lock in the explicit routing table — every specialist gets a line."""

    def test_task_agent_is_in_routing_table(self):
        prompt = llm_planner._build_system_prompt()
        # The bug was: task_agent was missing from the routing table
        # entirely. Verify it now has its own bullet.
        assert "task_agent" in prompt
        # And that the rule covers the verbs that previously thrashed.
        assert re.search(r"task_agent.*assign", prompt, re.IGNORECASE | re.DOTALL), (
            "task_agent rule must mention 'assign' so the planner picks it for 'assign those tasks to me' shapes."
        )

    def test_routing_table_disambiguates_team_membership(self):
        """workspace_agent's 'team membership' must NOT swallow task assignment.

        The carve-out can appear in either the original 2026-05 wording
        (``task_agent, NOT workspace_agent``) or the post-prompt-hygiene
        wording with markdown-quoted agent names
        (`` `task_agent`, NOT workspace_agent``). Both encode the same
        invariant — the regex below tolerates either.
        """
        prompt = llm_planner._build_system_prompt()
        # The fix wording explicitly carves out task assignment from
        # workspace_agent's surface. If a future edit drops this, the
        # 2026-05-08 routing failure reopens.
        carveout_match = re.search(
            r"`?task_agent`?,\s+NOT\s+`?workspace_agent`?",
            prompt,
        )
        legacy_regex_match = "NOT task" not in prompt.lower() and re.search(
            r"NOT task-of-team assignment|task assignment is task_agent",
            prompt,
            re.IGNORECASE,
        )
        assert carveout_match or legacy_regex_match, (
            "Prompt must explicitly say task assignment goes to task_agent "
            "rather than workspace_agent — 'team membership' phrasing on "
            "workspace_agent's row is otherwise a magnet for the LLM."
        )

    def test_every_registered_specialist_has_a_rule(self):
        """No specialist may go un-named in the routing table.

        If a future agent ships without a routing rule the planner
        falls back to workspace_agent — exactly the failure mode this
        test is here to prevent.
        """
        prompt = llm_planner._build_system_prompt()
        from components.agents.infrastructure.adapters.langchain.base import (
            AgentRegistry,
        )

        # ai_teammate is the orchestrator, not a specialist destination,
        # so don't require it in the routing table. Aliases ("task",
        # "triage", etc.) also don't need explicit rules. This is the
        # auto-sec fleet — the canonical names mirror
        # tests/_helpers/agent_capability_inventory.py.
        canonical = {
            "task_agent",
            "project_agent",
            "workspace_agent",
            "user_agent",
            "triage_agent",
            "log_watch_agent",
            "optimization_agent",
        }
        registered = set(AgentRegistry.list_agents())
        # Only check specialists that are actually registered.
        for name in canonical & registered:
            # Each specialist needs a ``**name** —`` line OR a
            # ``name`` mention in the routing table.
            assert name in prompt, (
                f"Specialist '{name}' is registered but absent from the "
                "planner system prompt. Add it to the PER-TASK SPECIALIST "
                "ROUTING table or the planner will mis-route to "
                "workspace_agent (default fallback)."
            )


class TestWorkspaceAgentProfileBoundaries:
    """The user-facing profile must not claim task-agent's territory.

    The summary is rendered as the agent-directory card description in
    the frontend (``AiAgentsDirectory.jsx``), so it stays user-readable.
    The planner-side disambiguation lives in the system prompt's
    PER-TASK SPECIALIST ROUTING table (covered by
    ``TestSystemPromptRoutingRules`` above), NOT in this user copy.

    These tests enforce the lower bar: the profile must not actively
    advertise task assignment as a workspace_agent capability.
    """

    def test_summary_does_not_claim_task_assignment(self):
        summary = WorkspaceAgent.profile["summary"].lower()
        # The 2026-05-08 incident root cause: the catalog summary's
        # phrasing nudged the planner toward workspace_agent for task
        # assignment. We don't require the summary to explicitly
        # disclaim it (that lives in the planner prompt), but the
        # summary MUST NOT mention task assignment as something this
        # agent does.
        offending = ("assign task", "task assign", "manage tasks", "manage task")
        for phrase in offending:
            assert phrase not in summary, (
                f"workspace_agent.profile.summary contains {phrase!r} — "
                "that overlaps with task_agent and re-opens the "
                "2026-05-08 routing failure. Task assignment is owned "
                "by task_agent."
            )

    def test_capabilities_do_not_overload_task_assignment(self):
        capabilities = WorkspaceAgent.profile.get("capabilities") or []
        joined = " ".join(capabilities).lower()
        assert "assign task" not in joined and "task assign" not in joined, (
            "workspace_agent must not advertise task assignment in its "
            "capabilities — task_agent owns that. Mis-advertising "
            "re-introduces the 2026-05-08 mis-routing."
        )


class TestClarifySentinelRouting:
    """Vague goals must route to the ``clarify`` sentinel, not a specialist.

    The 2026-06-08 incident: planner.system v3 routed clarifying tasks
    to ``workspace_agent``, which has no "ask the user" tool. It looped
    through ~17 LLM rounds before the synthesizer's honesty guard
    fired, and the user saw "I couldn't answer that" for every basic
    chat-style query.

    v4 introduces ``agent_type: clarify`` as a first-class routing
    sentinel handled directly by the orchestrator. These tests pin the
    new rule + example so a future prompt edit can't silently regress
    to the v3 shape.

    See ``docs/rca/2026-06-08-clarify-task-thrash.md``.
    """

    def test_clarify_appears_in_routing_rules(self):
        prompt = llm_planner._build_system_prompt()
        # The bullet list of specialists must include ``clarify`` so
        # the planner LLM knows it's a legal ``agent_type``.
        assert "clarify" in prompt, (
            "planner.system must mention `clarify` so the LLM knows "
            "the routing sentinel exists. Otherwise vague goals will "
            "default back to a tool-using specialist and re-open the "
            "2026-06-08 thrash."
        )
        # And it should be near the explanation of vague goals.
        assert re.search(
            r"clarify.*(vague|ambiguous|clarifying|description)",
            prompt,
            re.IGNORECASE | re.DOTALL,
        ), (
            "The `clarify` rule must explain when to use it — vague "
            "goals, clarifying questions, no-specialist-matches. "
            "Without that the LLM will not pick it for the right "
            "shape."
        )

    def test_ambiguous_example_uses_clarify_not_workspace_agent(self):
        """The ambiguous-goal example sets `agent_type: clarify`.

        The example is the strongest signal to the LLM (most recent
        few-shot before the output instruction). If a future edit
        flips this example back to ``workspace_agent``, the 2026-06-08
        bug reopens — the LLM will copy the example faithfully.
        """
        prompt = llm_planner._build_system_prompt()
        # The example block carries the literal JSON the LLM imitates.
        # Either the value is `"clarify"` or there's no ambiguous-goal
        # example at all (also fine — the routing rule alone would
        # suffice). We allow either, but we reject the failed v3 shape
        # of an ambiguous example wired to workspace_agent.
        ambiguous_block = re.search(
            r"<example name=\"ambiguous_goal[^\"]*\">(.*?)</example>",
            prompt,
            re.DOTALL,
        )
        if ambiguous_block is None:
            pytest.skip("No ambiguous-goal example in the active prompt; routing rule alone covers the contract.")
        body = ambiguous_block.group(1)
        # Must NOT route the clarifying task to workspace_agent.
        assert "workspace_agent" not in body, (
            "The ambiguous-goal example must not route to "
            "workspace_agent — that's the 2026-06-08 thrash bug. "
            "Use `agent_type: clarify` instead."
        )
        # And it should explicitly use the sentinel.
        assert '"clarify"' in body or "'clarify'" in body, (
            "The ambiguous-goal example must set "
            '`agent_type: "clarify"` so the LLM has a concrete '
            "shape to imitate when the goal is vague."
        )

    def test_tldr_and_summary_route_to_workspace_agent_not_clarify(self):
        """ "tldr" / "summary" / "overview" are NOT ambiguous goals.

        Tldr means "summarise this workspace" — that has a clear
        specialist answer (``workspace_agent.get_organization_info``).
        Routing it to ``clarify`` was a 2026-06-08 over-correction:
        the user asked for a summary, and the assistant asked a
        question back instead of just summarising.

        The active prompt must carve workspace-summary goals out
        of the clarify bucket and route them to ``workspace_agent``
        with an explicit instruction to use the org-info tool. The
        clarify pattern stays for truly ambiguous goals like "how
        are we doing?" where the dimension isn't even known.
        """
        prompt = llm_planner._build_system_prompt()
        # The rule that routes summary-shaped goals to workspace_agent.
        # Tolerant regex: the phrasing can drift between versions
        # ("Workspace-summary goals", "Tldr / summary / overview", etc.)
        # but the binding "tldr → workspace_agent" must remain.
        tldr_workspace_link = re.search(
            r"tldr.*workspace_agent",
            prompt,
            re.IGNORECASE | re.DOTALL,
        )
        assert tldr_workspace_link, (
            "Prompt must explicitly bind `tldr` to `workspace_agent` "
            "(via get_organization_info). Otherwise the LLM will "
            "treat tldr as ambiguous and emit a clarify task — "
            "Henry's 2026-06-08 feedback: 'this is a tldr should be "
            "able to summerize the workspace not ask more clarifying "
            "questions'."
        )

        # And there should be a tldr-shaped example that demonstrates
        # the routing — concrete few-shot beats prose for the LLM.
        tldr_example = re.search(
            r"<example name=\"tldr_[^\"]*\">(.*?)</example>",
            prompt,
            re.DOTALL,
        )
        assert tldr_example is not None, (
            "Prompt must include a `tldr_*` example so the LLM has a "
            "concrete shape to imitate. Without it, the planner often "
            "regresses to emitting a clarify task for `tldr`."
        )
        body = tldr_example.group(1)
        assert "workspace_agent" in body, "The tldr example must route to workspace_agent, not clarify."
        assert '"clarify"' not in body, "The tldr example must NOT use the clarify sentinel."

    def test_clarify_is_not_in_agent_registry(self):
        """``clarify`` is a routing sentinel, NOT a registered agent.

        The agent catalog is generated from
        ``AgentRegistry.list_agents()``. If someone accidentally
        registers an actual ``ClarifyAgent`` class, the planner would
        treat it like a real specialist and we'd lose the
        short-circuit. The orchestrator-level handling depends on
        ``clarify`` staying a name with no LangChain agent behind it.
        """
        from components.agents.infrastructure.adapters.langchain.base import (
            AgentRegistry,
        )

        assert "clarify" not in set(AgentRegistry.list_agents()), (
            "`clarify` must not be a registered agent — it is a "
            "routing sentinel handled by the orchestrator. "
            "Registering a real agent would route clarifying tasks "
            "through LangChain's AgentExecutor and reopen the "
            "thrash bug."
        )


class TestUserAgentRouting:
    """user_agent owns workspace-member identity and per-user audit activity.

    Before planner v5, user-shaped questions ("who is logged in", "list
    workspace members", "what has Alice done") fell into the clarify
    bucket because no specialist owned them — workspace_agent has
    aggregate-count tools but no member-listing tools. The v5 prompt
    adds an explicit ``user_agent`` rule and a worked example; these
    tests lock in the contract per §5.13 (prompts and the execution
    layer are one contract — pair the prompt edit with a runtime test).
    """

    def test_user_agent_is_registered(self):
        from components.agents.infrastructure.adapters.langchain.base import (
            AgentRegistry,
        )

        assert "user_agent" in set(AgentRegistry.list_agents()), (
            "user_agent must be in the registry — the v5 planner prompt "
            "routes user-identity questions to it, so it has to exist "
            "as a real specialist."
        )

    def test_user_agent_appears_in_routing_table(self):
        prompt = llm_planner._build_system_prompt()
        assert "user_agent" in prompt, (
            "planner.system v5+ must include a `user_agent` routing rule. "
            "Without it the planner falls back to clarify (or worse, to "
            "workspace_agent which lacks member-listing tools)."
        )

    def test_user_agent_routing_rule_has_a_because_clause(self):
        """Every routing bullet carries a ``because:`` clause per §12.4."""
        prompt = llm_planner._build_system_prompt()
        # Anchor on the bullet marker (``* `user_agent` —``) so we
        # don't accidentally match the ``user_agent`` token inside the
        # workspace_agent rule's "live with `user_agent`, not
        # workspace_agent" carve-out.  The rule body runs from there
        # to the next bullet (``\n * ``) or blank line.
        user_rule = re.search(
            r"\*\s+`user_agent`.*?(?=\n\s*\*|\n\n)",
            prompt,
            re.DOTALL,
        )
        assert user_rule is not None, "user_agent rule must be a single bullet in <routing_rules>."
        assert "because:" in user_rule.group(0), (
            "user_agent rule must carry a `because:` clause so the LLM "
            "generalises from the reason, not just the rule (§12.4)."
        )

    def test_workspace_member_query_routes_away_from_workspace_agent(self):
        """The prompt must steer member queries to user_agent, not workspace_agent."""
        prompt = llm_planner._build_system_prompt()
        # The user_agent bullet should mention members / member listing,
        # AND the workspace_agent bullet should disclaim per-user identity.
        assert re.search(
            r"user_agent.*?(workspace members|list our team|who is on the team|individual user)",
            prompt,
            re.IGNORECASE | re.DOTALL,
        ), (
            "user_agent rule must explicitly name workspace-member "
            "listing / team-membership questions so the LLM picks it "
            "for those shapes."
        )

    def test_user_agent_example_is_present(self):
        """A worked few-shot example beats prose for the LLM (§12.6)."""
        prompt = llm_planner._build_system_prompt()
        user_example = re.search(
            r"<example name=\"(?:list_workspace_members|user_agent[^\"]*)\">(.*?)</example>",
            prompt,
            re.DOTALL,
        )
        assert user_example is not None, (
            "planner.system v5+ must include a worked example that "
            "routes a member-listing goal to user_agent. The example "
            "is the strongest signal to the LLM (§12.6 multishot)."
        )
        body = user_example.group(1)
        assert '"user_agent"' in body, (
            'The user_agent example must set `agent_type: "user_agent"` so the LLM has a concrete shape to imitate.'
        )

    def test_user_agent_maps_to_identity_domain(self):
        """Findings emitted by user_agent must land in the identity bucket.

        Without this entry the kanban_sync_service falls back to
        "general" and the V2 dashboard groups identity findings under
        the wrong header.
        """
        from components.agents.domain.agent_domain_map import resolve_source_domain

        assert resolve_source_domain("user_agent") == "identity"


class TestSocBoundaryDisambiguations:
    """planner.system v9 sharpens the SOC pipeline boundaries.

    Three specialists share the log pipeline (triage / log_watch /
    optimization), and the verbs overlap ("fix", "findings", "logs").
    These tests pin the disambiguation paragraphs so future edits can't
    silently drop them.
    """

    def test_pending_findings_write_flow_routes_to_triage(self):
        prompt = llm_planner._build_system_prompt()
        # Acting on the board (list-then-triage) is triage_agent's flow.
        assert re.search(
            r"list_pending_log_findings.*?triage_finding",
            prompt,
            re.DOTALL,
        ), (
            "v9 must teach the list_pending_log_findings → triage_finding "
            "write flow on triage_agent so 'process the pending log "
            "findings' acts on the board instead of just reading it."
        )
        assert re.search(
            r"triage_agent[^*]*?(board|write)",
            prompt,
            re.IGNORECASE | re.DOTALL,
        ), "triage_agent's rule must frame it as the board-write specialist."

    def test_suggest_fix_boundary_present(self):
        """Ad-hoc fix advice is log_watch; fix-on-a-card is triage."""
        prompt = llm_planner._build_system_prompt()
        assert re.search(
            r"log_watch_agent.*?suggest_fix|suggest_fix.*?log_watch_agent",
            prompt,
            re.DOTALL,
        ), "v9 must bind suggest_fix to log_watch_agent so 'suggest a fix for this error' routes to the ad-hoc advisor."
        assert re.search(
            r"(finding card|card|board).*?triage_agent.*?triage_finding",
            prompt,
            re.IGNORECASE | re.DOTALL,
        ), (
            "v9 must route fix-requests that target a pending board card "
            "to triage_agent (triage_finding comments the fix and moves "
            "the card) — log_watch_agent cannot write to the card."
        )

    def test_error_vs_recurring_pattern_boundary_present(self):
        """A discrete error is log_watch; a measured recurring pattern
        (over-scheduled job, health-check noise, volume hotspot) is
        optimization."""
        prompt = llm_planner._build_system_prompt()
        assert re.search(
            r"(discrete|specific) error.*?log_watch_agent|log_watch_agent.*?(discrete|traceback)",
            prompt,
            re.IGNORECASE | re.DOTALL,
        ), "v9 must place discrete errors with log_watch_agent."
        assert re.search(
            r"(recurring|measured|pattern|noise|over-scheduled).*?optimization_agent"
            r"|optimization_agent.*?(recurring|over-scheduled|noise|hotspot)",
            prompt,
            re.IGNORECASE | re.DOTALL,
        ), (
            "v9 must place recurring measured patterns (over-scheduled "
            "jobs, health-check noise, volume hotspots) with "
            "optimization_agent."
        )

    def test_draft_pr_gating_on_triage_agent(self):
        """open_draft_pr belongs to triage_agent, requires an already-
        triaged finding, and pauses for human approval."""
        prompt = llm_planner._build_system_prompt()
        assert re.search(
            r"draft PR.*?triage_agent|triage_agent.*?open_draft_pr",
            prompt,
            re.IGNORECASE | re.DOTALL,
        ), "v9 must route draft-PR goals to triage_agent."
        assert re.search(
            r"(human approval|approval|irreversible)",
            prompt,
            re.IGNORECASE,
        ), (
            "v9 must carry the human-approval / irreversible-tier "
            "framing on the draft-PR rule so the planner doesn't teach "
            "autonomous PR creation."
        )

    def test_soc_finding_processing_example_present(self):
        """A worked SOC-delegation example beats prose (§12.6)."""
        prompt = llm_planner._build_system_prompt()
        example = re.search(
            r"<example name=\"soc_pending_findings_processing\">(.*?)</example>",
            prompt,
            re.DOTALL,
        )
        assert example is not None, (
            "v9 must include the soc_pending_findings_processing example "
            "so the LLM has a concrete finding-processing shape to "
            "imitate."
        )
        assert '"triage_agent"' in example.group(1), (
            'The SOC finding-processing example must set `agent_type: "triage_agent"`.'
        )


class TestPersonLookupRouting:
    """Person-shaped lookups route to user_agent.

    The wanjala prompt multi-routed bare ``Find <name>`` across the
    donor / sponsor / member tables. This fork has exactly one people
    directory — workspace membership — so v9 collapses the rule to a
    single user_agent task.
    """

    def test_person_lookup_rule_is_present(self):
        prompt = llm_planner._build_system_prompt()
        assert re.search(
            r"(Find <name>|who is <name>|look up <name>).*?user_agent",
            prompt,
            re.IGNORECASE | re.DOTALL,
        ), (
            "v9 must route person-shaped lookups (Find <name> / who is "
            "<name>) to user_agent — the only people directory in this "
            "system is workspace membership."
        )

    def test_members_section_disambiguates_grounding(self):
        """The grounding block still leans on the typed ``section`` key."""
        prompt = llm_planner._build_system_prompt()
        assert re.search(
            r"section.*?members|members.*?section|members.*?chunk",
            prompt,
            re.IGNORECASE | re.DOTALL,
        ), (
            "The grounding block must tell the planner that a retrieved "
            "chunk's `section: members` identifies a workspace teammate "
            "— the typed key beats the chunk body for routing."
        )


class TestPromptTargetsAreRegistered:
    """§5.13 prompt-runtime contract: every agent_type the prompt
    teaches must have a runtime handler.

    The pre-v9 drift this guards against: the routing table taught
    wanjala specialists (donation_agent, budget_agent, writing_agent,
    …) that were never registered in this fork, so the planner could
    emit an ``agent_type`` the runner cannot resolve. The prompt's
    routing targets must always be a subset of the live registry plus
    the ``clarify`` sentinel.
    """

    @staticmethod
    def _allowed_targets() -> set[str]:
        from components.agents.domain.value_objects.plan_schemas import (
            CLARIFY_AGENT_TYPE,
        )
        from components.agents.infrastructure.adapters.langchain.base import (
            AgentRegistry,
        )

        return set(AgentRegistry.list_agents()) | {CLARIFY_AGENT_TYPE}

    def test_routing_bullet_targets_are_registered(self):
        prompt = llm_planner._build_system_prompt()
        bullets = re.findall(r"^\s*\*\s+`([a-z_]+)`", prompt, re.MULTILINE)
        assert bullets, "No routing bullets found — the prompt structure changed."
        unknown = sorted(set(bullets) - self._allowed_targets())
        assert not unknown, (
            f"Routing bullets teach unregistered agent_types: {unknown}. "
            "Every specialist the prompt names must be resolvable by the "
            "runner (registry ∪ {clarify}) — teaching a ghost agent "
            "reintroduces the wanjala-fleet drift v9 removed."
        )

    def test_example_agent_types_are_registered(self):
        prompt = llm_planner._build_system_prompt()
        example_types = re.findall(r'"agent_type":\s*"([a-z_]+)"', prompt)
        assert example_types, "No example agent_types found — the prompt structure changed."
        unknown = sorted(set(example_types) - self._allowed_targets())
        assert not unknown, (
            f"Examples emit unregistered agent_types: {unknown}. The "
            "few-shot examples are the strongest routing signal — an "
            "example naming a ghost agent guarantees unresolvable plans."
        )


# NOTE (2026-07-19, planner.system v9): the wanjala-era classes
# TestBoundaryDisambiguations (donor/campaign/project-spend) and
# TestV6BareFindRouting (bare-find multi-route across donor/sponsor
# tables) were replaced by TestSocBoundaryDisambiguations and
# TestPersonLookupRouting when the routing prompt was retuned to the
# SOC fleet. TestWritingAgentRouting was already deleted in the fork
# retune (writing_agent was never ported). The v9 prompt carries no
# wanjala specialists; TestPromptTargetsAreRegistered keeps it that way.
