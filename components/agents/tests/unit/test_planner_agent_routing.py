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
            "task_agent rule must mention 'assign' so the planner picks "
            "it for 'assign those tasks to me' shapes."
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
        legacy_regex_match = (
            "NOT task" not in prompt.lower()
            and re.search(
                r"NOT task-of-team assignment|task assignment is task_agent",
                prompt,
                re.IGNORECASE,
            )
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
        # "donation", etc.) also don't need explicit rules.
        canonical = {
            "task_agent",
            "project_agent",
            "budget_agent",
            "financial_agent",
            "sponsorship_agent",
            "donation_agent",
            "fundraising_agent",
            "workspace_agent",
            "user_agent",
            "blog_agent",
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
            pytest.skip(
                "No ambiguous-goal example in the active prompt; "
                "routing rule alone covers the contract."
            )
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
            "`agent_type: \"clarify\"` so the LLM has a concrete "
            "shape to imitate when the goal is vague."
        )

    def test_tldr_and_summary_route_to_workspace_agent_not_clarify(self):
        """"tldr" / "summary" / "overview" are NOT ambiguous goals.

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
        assert "workspace_agent" in body, (
            "The tldr example must route to workspace_agent, not clarify."
        )
        assert '"clarify"' not in body, (
            "The tldr example must NOT use the clarify sentinel."
        )

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
        assert user_rule is not None, (
            "user_agent rule must be a single bullet in <routing_rules>."
        )
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
            "The user_agent example must set "
            "`agent_type: \"user_agent\"` so the LLM has a concrete "
            "shape to imitate."
        )

    def test_user_agent_maps_to_identity_domain(self):
        """Findings emitted by user_agent must land in the identity bucket.

        Without this entry the kanban_sync_service falls back to
        "general" and the V2 dashboard groups identity findings under
        the wrong header.
        """
        from components.agents.domain.agent_domain_map import resolve_source_domain

        assert resolve_source_domain("user_agent") == "identity"


class TestBoundaryDisambiguations:
    """v5 sharpens three boundary cases the v4 ``because:`` clauses
    underspecified. Lock the disambiguations in so future edits can't
    silently drop them.
    """

    def test_donor_history_disambiguation_present(self):
        prompt = llm_planner._build_system_prompt()
        # The disambiguation must tie "donor" → donation_agent and
        # "teammate" → user_agent so the planner doesn't conflate the
        # two tables when the user says "Alice's history".
        assert re.search(
            r"giving.*?donation_agent|donor.*?donation_agent",
            prompt,
            re.IGNORECASE | re.DOTALL,
        ), (
            "v5 must include a 'donor giving history → donation_agent' "
            "disambiguation so 'Alice's giving history' routes to "
            "donation_agent, not user_agent."
        )

    def test_campaign_vs_budget_disambiguation_present(self):
        prompt = llm_planner._build_system_prompt()
        assert re.search(
            r"campaign.*fundraising_agent",
            prompt,
            re.IGNORECASE | re.DOTALL,
        ), (
            "v5 must keep the 'campaign goal → fundraising_agent' rule "
            "so 'what's the goal on campaign Y' does not get routed to "
            "budget_agent."
        )

    def test_project_spend_disambiguation_present(self):
        prompt = llm_planner._build_system_prompt()
        # Either project_agent.get_project_spend (the rollup) or
        # financial_agent.list_transactions (the raw list) must be
        # disambiguated by scope.
        assert re.search(
            r"(project_agent\.get_project_spend|get_project_spend|rollup)",
            prompt,
            re.IGNORECASE | re.DOTALL,
        ), (
            "v5 must disambiguate project-spend rollups (project_agent) "
            "from raw transaction lists (financial_agent) so 'what did "
            "we spend on project Y' doesn't randomly pick one."
        )


class TestV6BareFindRouting:
    """v6 closes the bare-find routing gap.

    The 2026-06-09 demo smoke showed "Find Henry Wanjala" routing to
    ``donation_agent`` because the retrieved_context surfaced Henry as a
    top donor — but for a teammate who isn't in any donor index, the
    same query would have produced no answer. v6 introduces explicit
    rules for bare ``Find <name>`` that use retrieved_context's section
    to disambiguate, and multi-routes when the chunks don't name the
    person.

    Paired with the Tier 3 #14 snapshot indexer change that adds a
    ``members`` section to the embedding so member-shaped queries get
    a typed chunk to surface.
    """

    def test_bare_find_routing_paragraph_is_present(self):
        prompt = llm_planner._build_system_prompt()
        # Must explicitly mention bare-find handling so the LLM does not
        # fall through to whichever retrieved chunk it finds first.
        assert re.search(
            r"bare-find routing|`Find <name>`|Find/Look up/Who is <name>|bare\s+find",
            prompt,
            re.IGNORECASE,
        ), (
            "v6 must include an explicit bare-find routing paragraph so "
            "`Find Henry Wanjala` doesn't fall through to whichever "
            "retrieved chunk happens to mention the name."
        )

    def test_bare_find_uses_section_to_disambiguate(self):
        """The rule must lean on ``section`` (members/top_entities) to
        route, not just the chunk body."""
        prompt = llm_planner._build_system_prompt()
        assert re.search(
            r"section.*?members|members.*?section|members.*?chunk",
            prompt,
            re.IGNORECASE | re.DOTALL,
        ), (
            "v6 must tell the planner to use the retrieved chunk's "
            "`section` field to distinguish members from donors when "
            "routing a bare `Find <name>` query."
        )

    def test_multi_route_is_specified_when_chunks_dont_name_the_person(self):
        prompt = llm_planner._build_system_prompt()
        assert re.search(
            r"three parallel tasks|3 parallel tasks|three tasks|multi-route",
            prompt,
            re.IGNORECASE,
        ), (
            "v6 must instruct the planner to emit multiple tasks for "
            "bare `Find <name>` when retrieved_context doesn't name the "
            "person — otherwise a teammate not in any indexed chunk is "
            "unfindable."
        )

    def test_qualified_find_skips_multi_route(self):
        """Explicit qualifiers (find donor X / find member X / find
        sponsor X / find recipient X) must NOT trigger multi-route."""
        prompt = llm_planner._build_system_prompt()
        assert re.search(
            r"find donor|find member|find sponsor|find recipient",
            prompt,
            re.IGNORECASE,
        ), (
            "v6 must mention qualified bare-find shapes so the planner "
            "knows to skip multi-route when the user has named the "
            "entity type explicitly."
        )

    def test_find_member_example_routes_to_user_agent(self):
        prompt = llm_planner._build_system_prompt()
        example = re.search(
            r"<example name=\"find_member_routes_to_user_agent\">(.*?)</example>",
            prompt,
            re.DOTALL,
        )
        assert example is not None, (
            "v6 must include a worked example that routes "
            "`Find <member>` to user_agent when retrieved_context has a "
            "members chunk identifying the person. Few-shot examples "
            "are the strongest signal to the LLM (§12.6)."
        )
        assert '"user_agent"' in example.group(1), (
            "find_member_routes_to_user_agent example must set "
            "`agent_type: \"user_agent\"` so the LLM has a concrete "
            "shape to imitate."
        )

    def test_find_bare_name_multi_route_example_emits_three_tasks(self):
        prompt = llm_planner._build_system_prompt()
        example = re.search(
            r"<example name=\"find_bare_name_multi_route\">(.*?)</example>",
            prompt,
            re.DOTALL,
        )
        assert example is not None, (
            "v6 must include a worked example showing the 3-task emit "
            "for bare `Find <name>` when chunks don't name the person."
        )
        body = example.group(1)
        for agent_type in ("user_agent", "donation_agent", "sponsorship_agent"):
            assert f'"{agent_type}"' in body, (
                f"find_bare_name_multi_route example must include a "
                f"task with agent_type {agent_type!r} so all three "
                "identity tables get queried."
            )


class TestWritingAgentRouting:
    """Drafting verbs route to writing_agent, not workspace_agent or a sentinel.

    Pre-v7 the planner had no explicit `writing_agent` routing rule —
    writing tools were reachable only through the dynamic agent
    catalog, so the LLM picked whichever alias slug was closest to the
    user's noun (`letter_agent` for "draft a letter"). v7 carves the
    drafting verb family + entity-update flow into the routing table
    with `because:` clauses and three worked examples.

    These tests pin the v7 contract so a future prompt edit can't
    silently drop the rule.

    Per §5.13: the runtime side (`writing_agent` tools persist via
    `CreateWritingDraftUseCase`) lands in the same PR — the runtime
    handler is real, not a sentinel, so no separate runner test
    is needed (covered by `test_writing_agent_tools.py`).
    """

    def test_writing_agent_has_a_routing_rule(self):
        prompt = llm_planner._build_system_prompt()
        assert "writing_agent" in prompt, (
            "planner.system v7 must include a `writing_agent` rule. "
            "Without it the LLM falls back to alias matching against "
            "the dynamic catalog and surfaces `letter_agent` / "
            "`newsletter_agent` rather than the canonical name."
        )
        # The rule must explain WHEN to pick writing_agent — the verb
        # family. The §12.4 hygiene rule requires every routing bullet
        # to carry a `because:` clause; this also enforces that the
        # rule is grounded in the canonical reason (WritingDraft
        # persistence).
        writing_bullet = re.search(
            r"\*\s+`?writing_agent`?\s+—.*?because:.*?(?=\n\s*\*\s+`?\w+_agent`?|\Z)",
            prompt,
            re.IGNORECASE | re.DOTALL,
        )
        assert writing_bullet is not None, (
            "The `writing_agent` rule must follow the `* name — body. "
            "because: reason` shape used by every other specialist."
        )
        bullet_text = writing_bullet.group(0)
        # The drafting verbs that should trigger the route. v7's
        # phrasing is `(draft, write, create, compose, generate, "
        # "produce, make)`; the planner uses verb intent rather than
        # keyword match, so we test for presence of the canonical
        # subset that the rule names.
        for verb in ("draft", "write", "compose", "generate"):
            assert verb in bullet_text.lower(), (
                f"The `writing_agent` rule must name the verb "
                f"'{verb}' so the LLM knows the verb family that "
                "routes here."
            )
        # The rule must mention WritingDraft persistence — that's the
        # justification for routing here over alternatives.
        assert "WritingDraft" in bullet_text, (
            "The `writing_agent` rule must reference WritingDraft "
            "persistence so the LLM has the canonical reason for "
            "preferring this agent."
        )

    def test_drafting_verbs_paragraph_exists(self):
        """v7 adds a `Drafting verbs route by artifact` paragraph
        mirroring the existing `Report verbs route by scope` paragraph.
        The block enumerates specific tool routes (draft_letter,
        draft_mission, etc.) so the planner emits the right tool name
        in the description even before the LLM tools fire.
        """
        prompt = llm_planner._build_system_prompt()
        assert re.search(
            r"drafting\s+verbs?\s+route\s+by\s+artifact",
            prompt,
            re.IGNORECASE,
        ), (
            "v7 must include the `Drafting verbs route by artifact` "
            "paragraph. Without it the LLM may route drafting verbs "
            "to whichever agent shares a noun (e.g. `donation_agent` "
            "for a donor letter)."
        )
        # The paragraph must name the canonical tools.
        for tool_name in (
            "draft_letter",
            "draft_mission",
            "draft_newsletter_from_period",
        ):
            assert tool_name in prompt, (
                f"The drafting-verbs paragraph must name the "
                f"`{tool_name}` tool so the planner's task description "
                "field cites the exact tool name."
            )

    def test_entity_update_paragraph_requires_two_task_plan(self):
        """The entity-update flow needs a two-task plan: resolve UUID
        via the entity-owning specialist first, then call writing_agent
        with the resolved id. The writing tool verifies workspace
        ownership and rejects a UUID it can't find — passing the entity
        name as `entity_id` fails at the persistence layer.
        """
        prompt = llm_planner._build_system_prompt()
        assert re.search(
            r"entity-update\s+drafting",
            prompt,
            re.IGNORECASE,
        ), (
            "v7 must include the `Entity-update drafting` paragraph. "
            "Without it the planner emits a one-task plan that passes "
            "the entity name as entity_id, which the persistence "
            "layer rejects."
        )
        # The paragraph must name the four entity-update tools and the
        # specialists that resolve their UUIDs.
        for entity_tool in (
            "draft_recipient_update",
            "draft_project_update",
            "draft_event_update",
            "draft_campaign_update",
        ):
            assert entity_tool in prompt, (
                f"Entity-update paragraph must name `{entity_tool}` "
                "so the planner picks the right writing tool per "
                "entity type."
            )
        # The resolve-first specialists must be named.
        for resolver in ("sponsorship_agent", "project_agent", "fundraising_agent"):
            assert resolver in prompt, (
                f"Entity-update paragraph must name `{resolver}` as "
                "an entity-resolution specialist so the planner emits "
                "the resolve-first task."
            )

    def test_draft_thank_you_letter_example_present(self):
        """The two-task example: donor lookup then writing_agent.draft_letter."""
        prompt = llm_planner._build_system_prompt()
        example = re.search(
            r"<example name=\"draft_thank_you_letter\">(.*?)</example>",
            prompt,
            re.DOTALL,
        )
        assert example is not None, (
            "v7 must include the `draft_thank_you_letter` worked "
            "example. Few-shot examples are the strongest signal to "
            "the LLM (§12.6)."
        )
        body = example.group(1)
        # The first task resolves the donor.
        assert '"donation_agent"' in body, (
            "First task in draft_thank_you_letter must route to "
            "`donation_agent` to surface the top donor."
        )
        # The second task drafts via writing_agent.
        assert '"writing_agent"' in body, (
            "Second task in draft_thank_you_letter must route to "
            "`writing_agent` so the letter persists as a WritingDraft."
        )
        assert "draft_letter" in body, (
            "The drafting task's description must name the "
            "`draft_letter` tool so the worker LLM picks it."
        )

    def test_draft_recipient_update_example_resolves_first(self):
        """The two-task example for entity-scoped updates: sponsorship
        resolves the recipient UUID, then writing_agent drafts the
        update with the resolved id."""
        prompt = llm_planner._build_system_prompt()
        example = re.search(
            r"<example name=\"draft_recipient_update_resolves_first\">(.*?)</example>",
            prompt,
            re.DOTALL,
        )
        assert example is not None, (
            "v7 must include the `draft_recipient_update_resolves_first` "
            "example showing the two-task entity flow."
        )
        body = example.group(1)
        # The resolve task routes to sponsorship_agent.
        assert '"sponsorship_agent"' in body, (
            "First task must route to `sponsorship_agent` to resolve "
            "the recipient UUID."
        )
        # The draft task routes to writing_agent and names the tool.
        assert '"writing_agent"' in body, (
            "Second task must route to `writing_agent`."
        )
        assert "draft_recipient_update" in body, (
            "Second task must name the `draft_recipient_update` tool "
            "so the writing worker picks the entity-scoped variant."
        )

    def test_draft_mission_statement_example_single_task(self):
        """The single-task example for free-form drafting: no entity
        lookup, one writing_agent task that calls draft_mission."""
        prompt = llm_planner._build_system_prompt()
        example = re.search(
            r"<example name=\"draft_mission_statement\">(.*?)</example>",
            prompt,
            re.DOTALL,
        )
        assert example is not None, (
            "v7 must include the `draft_mission_statement` example "
            "showing the single-task free-form draft flow."
        )
        body = example.group(1)
        assert '"writing_agent"' in body, (
            "draft_mission_statement example must route to "
            "`writing_agent` (free-form drafts don't need an entity "
            "lookup)."
        )
        assert "draft_mission" in body, (
            "draft_mission_statement example must name the "
            "`draft_mission` tool."
        )

    def test_writing_agent_is_registered(self):
        """The writing_agent class must be registered under its canonical
        name and its aliases — the runtime side of the v7 routing rule
        depends on this. If a future refactor drops the registration,
        v7's routing rule sends users to an agent that doesn't exist."""
        from components.agents.infrastructure.adapters.langchain.base import (
            AgentRegistry,
        )

        registered = set(AgentRegistry.list_agents())
        assert "writing_agent" in registered, (
            "writing_agent must be registered under its canonical "
            "name — v7's routing rule depends on it."
        )
        # The aliases the planner may still emit (the routing rule
        # tells it to prefer writing_agent, but the catalog still
        # contains the aliases so backward-compat planner emissions
        # resolve to the same class).
        for alias in ("newsletter_agent", "letter_agent", "draft_agent"):
            assert alias in registered, (
                f"alias `{alias}` must remain registered so the "
                "frontend's canonical-name resolver (which maps "
                "alias → canonical via the registry) can resolve "
                "older snapshots."
            )

    def test_writing_agent_canonical_name_resolves(self):
        """The AgentRegistry must expose canonical_name_for() so the
        chat-header resource can resolve aliases to the canonical name.

        Without this lookup, the frontend would surface whichever
        alias the planner picked (`letter_agent`, etc.) rather than
        the consistent canonical name (`writing_agent`)."""
        from components.agents.infrastructure.adapters.langchain.base import (
            AgentRegistry,
        )

        # Canonical resolution: alias resolves to canonical slug.
        assert AgentRegistry.canonical_name_for("letter_agent") == "writing_agent", (
            "`letter_agent` is a registered alias of writing_agent — "
            "canonical_name_for() must resolve it to the canonical "
            "slug so the chat header is consistent."
        )
        assert AgentRegistry.canonical_name_for("writing_agent") == "writing_agent", (
            "canonical_name_for() must be idempotent for the "
            "canonical slug itself."
        )
        # Sentinel passthrough: clarify is a routing sentinel, not
        # an agent — the resolver must pass it through unchanged so
        # the frontend can render its own label.
        assert AgentRegistry.canonical_name_for("clarify") == "clarify", (
            "`clarify` is a routing sentinel, not an agent. "
            "canonical_name_for() must pass it through unchanged."
        )
        # Display-name resolution: alias resolves to the human label
        # from the registered profile.
        display = AgentRegistry.display_name_for("letter_agent")
        assert display == "Writing Agent", (
            f"display_name_for('letter_agent') returned {display!r} "
            "— the frontend chat header expects the registered "
            "profile['name'] ('Writing Agent')."
        )
