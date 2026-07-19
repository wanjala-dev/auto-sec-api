# Deep Agents Blueprint for `apps.ai`

Goal: evolve today’s ReAct-style agents into a LangGraph-native, plan/execute system that is durable, resumable, human-aware, and ready for multiple domains (charity first, later security/medical/etc.).

## Canonical entry points (read this first)

The legacy ReAct `OrchestratorAgent` has been **retired and deleted**. There is now ONE orchestration path:

| Surface | Module | What it does |
|---|---|---|
| **Interactive chat** | `agents/ai_teammate_agent.py` (`AiTeammateAgent`) | Thin facade. Forces every query through the deep pipeline by setting `context["mode"] = "deep"` and delegating to `AgentService.execute_agent`. No ReAct loop, no sub-agent tools, no detectors. Slugs: `ai_teammate`, `ai_teammate_agent`, `orchestrator`, `orchestrator_agent`, `planner`. |
| **Deep pipeline** | `langchain/deep/` (`runner.execute_plan_once`, `orchestrator.build_orchestrator`) | LangGraph plan → schedule → fan-out workers → synthesize → optional replan. Durable `DeepRun` checkpoints, HITL via `interrupt()`, per-tenant `allowed_agents` enforcement at the worker boundary. |
| **Detector cron** | `application/services/detector_cycle.py` (`run_detector_cycle`) | Plain function called directly by the Celery task `run_ai_teammate_cycle`. Runs every registered detector with timeout/parallelism budgets, persists `AIAction` rows, optionally asks an LLM to summarise signals. **Does not go through any agent class.** |

To run a query through the deep pipeline, just call `AgentService.execute_agent(agent_id, query, context={"mode": "deep"})` — or store `mode: deep` in the agent's config and the routing happens automatically. The service does the planner call + `execute_plan_once` + result extraction.

## Reality check (current state)
- Runtime is LangChain ReAct via `create_react_agent` + `AgentExecutor` in `apps/ai/agents/base.py`; Celery entrypoints call these directly.
- No planner/task graph; delegation is ad hoc (e.g., teammate calling other agents) and state is only conversation memory.
- Artifacts are implicit (stuffed in memory or action logs); no durable plan/task/artifact ledger.
- No interrupt/resume: long or risky actions can’t pause for human review or recover mid-run.

## LangGraph capabilities we should lean on (Context7 guidance)
- **StateGraph + Send fan-out**: use `Send("worker", …)` to parallelize tasks whose deps are met; reducers (`Annotated[..., operator.add]`) keep state append-only.
- **Durable runs**: compile with a checkpointer; always pass `configurable.thread_id` (use `AgentExecution.id` or `plan_id`) so we can resume/retry.
- **Human-in-the-loop**: `interrupt(payload)` pauses; resume with `Command(resume=…)` bound to the same `thread_id`. Payload must be JSON-serializable.
- **Conditional routing**: `add_conditional_edges` (e.g., `should_continue`) for loops/branching; budget checks can short-circuit to END.
- **Persistent checkpointers**: start with `InMemorySaver`, graduate to Postgres/Redis (`PostgresSaver` / `langgraph-redis`) for production durability.

## Target architecture (revised)
1) **Planner node**
   - Emits a typed plan: tasks, deps, agent/tool to use, domain/policy tags, acceptance criteria, budgets.
   - Persists to DB (`DeepPlan`, `DeepTask`) before execution for audit/resume.
2) **Orchestrator graph (LangGraph)**
   - State: `plan`, `ready_tasks`, `inflight_tasks`, `completed_tasks`, `artifacts`, `run_meta` (budgets, user/seed/tenant, domain), `interrupts`.
   - Dispatcher uses `Send("worker", {...})` per ready task; reducer appends completions/artifact handles.
   - Conditional edge decides whether more tasks are runnable, we need approvals, or we finish.
3) **Workers (thin wrappers)**
   - Call `AgentRegistry.create_agent(...).execute(...)` with per-task context; enforce structured JSON output:
     ```json
     {"summary": "...", "artifact_refs": ["artifact://..."], "risks": ["..."], "next_inputs": {...}, "observations": [...]}
     ```
   - Store bulky outputs in an artifact store (DB row + blob/object); prompts receive summaries/handles, not raw payloads.
4) **Human gates**
   - Insert `interrupt` nodes for risky actions (writes, outbound comms, PII/PHI, security-sensitive steps).
   - Resume with `Command(resume={...})` from an approval endpoint; reflect status in `AgentExecution.state`.
5) **Evaluator/guardrails**
   - Schema validation of worker output; cost/step budget checks; optional self-critique node.
   - Tool allowlists per domain/tenant; retries for transient errors only.
6) **Telemetry/observability**
   - Tag Langfuse spans with `plan_id`/`task_id` and `thread_id`; surface budgets and interrupts in state for UI/API.

## Multi-domain strategy
- Neutral core schemas: `plan/task/artifact/checkpoint` rows carry `domain`, `tenant`, `policy`, and allowed tools list.
- Domain packs: charity (current), security, medical, etc. Each pack defines tools, prompts, evaluators, approval policies, and PII/PHI redaction rules.
- Storage isolation: artifacts tagged by domain/tenant; sensitive domains prefer encrypted object storage + shorter TTL; DB only holds summaries/handles.
- Cross-domain calls: workers may spawn sub-agents in other domains; enforce tool/PII allowlists and log cross-domain hops for audit.

## Deep vs. shallow (initial cut)
- **Deep candidates (become planners/workers under LangGraph)**
  - **Orchestrator (root)**: owns planner/dispatcher; spins domain plans (budget, sponsorship, fundraising, ops) and aggregates artifacts.
  - **BudgetAgent + FinancialAgent (Finance)**: allocations/variance plans, compliance gates, periodic reporting, schedulable scans (overspend/missing receipts), approvals for risky writes.
  - **SponsorshipAgent (Sponsorship)**: matching, status hygiene, comms drafts, anomaly detection on changes; human-in-loop for outbound messages.
  - **TaskAgent + ProjectAgent (Ops/Projects)**: triage detectors, create/assign tasks, milestone checks, weekly rollups, blocker escalation; assignments stay human-approved.
  - **Donation/FundraisingAgent (Fundraising)**: donor segmentation, campaign drafts, performance monitoring, anomaly flags, CRM hygiene; no auto-send until approvals solid.
  - **SeedAgent (Exec)**: COO/board view that assembles cross-domain artifacts (finance, sponsorship, fundraising, projects) into summaries/exceptions.
- **Keep shallow (tools) for now**
  - **BlogAgent**: content-writing tool invoked by deep agents.
  - **DynamicAgent**: bespoke tool bundle; use as worker, not planner.

## Department mapping (roles → deep agents)
- Finance/Budget → BudgetAgent + FinancialAgent
- Sponsorship → SponsorshipAgent
- Fundraising → Donation/FundraisingAgent
- Ops/Projects → TaskAgent + ProjectAgent
- Exec/Seed → SeedAgent
- Orchestrator stays the root, dispatching into these roles and sharing plan/task/artifact tables, budgets, and policies per role.

## Readiness notes (per agent)
- **Budget/Financial**: high leverage; structured IO; needs artifact store for reports; approvals for write actions.
- **Sponsorship**: high leverage; gate outbound comms; leverage detectors (stale statuses, match recs).
- **Task/Project**: good for recurring reviews and escalations; keep assignment actions human-approved.
- **Donation/Fundraising**: useful for monitoring/drafting; avoid auto-send until approval flows are proven.
- **Seed (Exec)**: aggregator; depends on artifacts from other agents; ensure cross-domain access is audited/allowlisted.

## Integration path (practical, low-blast-radius)
1) **Introduce LangGraph orchestrator**
   - New module (e.g., `ai/agents/orchestrator.py`) building a `StateGraph` with planner → dispatcher → worker → reducer → synthesizer → END.
   - Use `InMemorySaver` initially; pass `thread_id=AgentExecution.id`.
2) **Persist plans/artifacts**
   - Add `DeepPlan`, `DeepTask`, `DeepArtifact` models; planner writes rows, workers append artifact handles, reducers mark completion.
   - Keep state small by storing IDs + summaries; bulk payloads live in object storage.
3) **Route opt-in traffic**
   - In `AgentService.execute_agent_async` / Celery task, branch to orchestrator when `config.mode == "deep"` (or feature flag); default path stays ReAct for stability.
4) **Human approvals**
   - Add approval API that resumes graphs with `Command(resume=...)`; gate writes/notifications/PII by domain policy.
5) **Checkpointer hardening**
   - Swap `InMemorySaver` for Postgres/Redis once stable; thread IDs = execution IDs; include `user_id` in `configurable` for namespacing.
6) **Tests**
   - Add LangGraph unit tests: planner emits plan, dispatcher fans out, interrupt/resume works, budgets stop runs, persistence restores state after simulated crash.

## Patterns/snippets to follow
- **Threaded invocation**: `config = {"configurable": {"thread_id": str(execution.id), "user_id": str(user.id)}}`
- **Interrupt gate**:
  ```python
  def approval_gate(state: State):
      decision = interrupt({"task_id": state["task"]["id"], "summary": state["task"]["summary"]})
      return Command(update={"task": {**state["task"], "approval": decision}})
  ```
- **Send fan-out**:
  ```python
  def dispatch(state: State):
      return [Send("worker", {"task": t}) for t in state["ready_tasks"]]
  ```
- **Reducer fields**: use `Annotated[list, operator.add]` for `completed_tasks` / `artifacts` to keep merges simple.

## Near-term TODOs
- Add LangGraph dependency and orchestrator skeleton + tests.
- Define plan/task/artifact schemas (DB + Pydantic) with domain/policy/budget fields.
- Wrap existing agents as workers with structured JSON IO and artifact writes.
- Add interrupt-capable approval API + resume path; record approvals in `AgentExecution.state`.
- Wire Langfuse tags to `plan_id`/`task_id` and surface budget/interrupt status to UI.
