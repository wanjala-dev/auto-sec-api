# Agent tool usage evidence — the answer to ADR 0031 OQ4

Status: **evidence, 2026-08-20.** Read-only measurement against the live local cluster plus a
caller inventory across both repos. Companion to
[`AGENT_TOOL_INVENTORY_2026-08-20.md`](AGENT_TOOL_INVENTORY_2026-08-20.md), which counted the tools;
this counts the *calls*, and answers the question the inventory left open.

> **OQ4 — the CRUD fleet.** `task_agent` (25 tools) and `project_agent` (18) are inherited
> nonprofit-shaped CRUD, both above the tool-count band in D9. Convert them, trim them, or leave
> them?
> — [ADR 0031](../adr/0031-agent-tool-contract-and-registry.md), Open questions

---

## The answer, first

**Convert them — with a named trim of 9 tools and 3 genuinely dead modules. Do not delete the
fleet.**

The expectation going in was that call counts would settle this: ~9,300 recorded tool calls spanning
only 19 distinct tool names, against ~100 registered tools, reads like 80-odd dead tools waiting to
be deleted. The call counts are real and they are reproduced below. **They do not support that
conclusion, and this document says so plainly.**

Three findings, in the order that matters:

1. **Zero of the 53 CRUD tools has ever been called.** True, and stronger than expected — it is 53
   for 53, across the entire life of the database.
2. **"Never called" is not "dead", and this codebase proves it.** 79 tool names have never been
   recorded. **29 of them live on the *security* agents** — including `open_draft_pr`,
   `record_finding`, `query_asset_graph`, `generate_pentest_report`, and all six
   `ai_governance_agent` tools. A rule that deletes what has never been called deletes
   `open_draft_pr`, the draft-PR remediation artifact that is a standing HARD rule of this product.
   Call count alone cannot answer OQ4.
3. **The CRUD fleet is reachable, entitled by default, the configured default on three REST
   endpoints, and deliberately routed to by the *active* planner prompt.** It is not vestigial
   wiring nobody remembers. It is a surface the current SOC-era prompt names in four `because`-backed
   routing bullets and three few-shot examples.

So the honest verdict is **unused-but-reachable**, not dead — and the correct response to
unused-but-reachable code that is one HTTP request from executing is to govern it, not to leave it
undeclared. That is a conversion.

The trim is real but small and specific, and it is listed in §7.

---

## 1. Method

Everything here is read-only. No data was mutated, no scan dispatched, no cluster change made.

| What | How |
|---|---|
| Call counts | `SELECT ... FROM ai_deeprunlog WHERE event_type='tool_observation' GROUP BY tool_name` against `postgres-0` in namespace `autosec` |
| Registered tool surface | `BaseAgent.__init_subclass__`'s `_decorated_tools`, enumerated in a throwaway container from `autosec-api:local` — no instantiation, no ORM |
| Caller inventory | both repos: backend source, `tests/qa/`, this repo's tests, management commands, prompt assets, eval datasets, the frontend `src/` **and** its built bundle |
| Baseline | `components/agents/tests/ tests/architecture/` on untouched `main`: **1 failed, 2283 passed, 33 skipped** (the known `test_clean_source_is_not_flagged`) |

### The window, stated honestly

`tool_observation` recording spans **2026-07-28 → 2026-08-19**. The earliest `django_migrations`
row is **2026-07-26** — the day the docker-compose stack was retired and the k8s cluster came up.

So this is **the complete history of this database, and only of this database** (~24 days). Anything
recorded in the retired compose volume is not here. Every "never called" claim below means *never
called since 2026-07-26*, and it is qualified that way throughout. That caveat is why §2 is not the
end of the argument.

---

## 2. The call counts, re-derived

```
total_rows | distinct_tools |           first_row           |           last_row
       9333 |             19 | 2026-07-28 02:00:25.307644+00 | 2026-08-19 22:19:43.191634+00
```

Every tool name ever recorded, with its agent and window:

| tool | agent | calls | first | last |
|---|---|--:|---|---|
| `list_pending_log_findings` | TriageAgent | 3384 | 07-28 | 08-19 |
| `list_pending_cloud_exposure_findings` | TriageAgent | 3352 | 07-28 | 08-19 |
| `triage_container_vuln` | TriageAgent | 794 | 08-04 | 08-19 |
| `assign_task` | TriageAgent | 637 | 07-31 | 08-12 |
| `triage_finding` | TriageAgent | 552 | 07-31 | 08-11 |
| `list_pending_code_findings` | CodeSecurityAgent | 120 | 08-09 | 08-19 |
| `get_members_without_tasks` | TriageAgent | 117 | 07-28 | 08-13 |
| `advise_optimization` | OptimizationAgent | 116 | 07-31 | 08-03 |
| `get_team_members` | TriageAgent | 73 | 07-28 | 08-12 |
| `list_pending_optimizations` | OptimizationAgent | 57 | 07-31 | 08-03 |
| `list_open_findings` | TriageAgent | 47 | 07-31 | 08-19 |
| `list_pending_container_vuln_findings` | TriageAgent | 42 | 07-28 | 08-19 |
| `triage_code_finding` | CodeSecurityAgent | 22 | 08-09 | 08-19 |
| `get_posture_report` | PostureAgent | 8 | 07-30 | 08-19 |
| `triage_cloud_exposure` | TriageAgent | 8 | 07-28 | 07-28 |
| `retrieve_workspace_context` | LogAnalyticsAgent | 1 | 07-31 | 07-31 |
| `query_log_metric` | LogAnalyticsAgent | 1 | 07-31 | 07-31 |
| `rank_repos_by_risk` | CodeSecurityAgent | 1 | 08-12 | 08-12 |
| `read_repo_file` | CodeSecurityAgent | 1 | 08-19 | 08-19 |

**19 of 98 distinct registered tool names. 79 never recorded.**

(The registry holds **98 distinct names** across **139** agent×tool registrations — the ADR's "101"
and "46" counted a slightly different surface. The corrected numbers are used throughout; see §3.)

Corroborating rows, same window:

- `ai_agent`: only **five** agent types were ever instantiated — `triage_agent` (2606 executions),
  `code_security_agent` (127), `optimization_agent` (66), `posture_agent` (8),
  `log_analytics_agent` (1). No `task_agent` / `project_agent` / `workspace_agent` / `user_agent`
  row exists.
- `Agent.config.custom_profile.tool_whitelist`: **null in all 10 rows.** No DB-resident tool name
  pins anything on this cluster. (The mechanism is real and a source grep cannot see it — it is
  simply unused here.)

---

## 3. Why call count alone cannot answer OQ4

Of the 79 never-recorded tool names, **29 sit on the security agents**:

```
draft_workflow, enrich_indicator, generate_pentest_report, get_ai_activity,
get_capability_grants, get_credential_inventory, get_findings_posture, get_fleet_health,
get_forward_outlook, get_governance_report, get_hitl_ledger, get_kill_switch_status,
get_metric_trend, get_repo_findings, get_repo_scan_status, get_response_kpis,
get_scan_history, get_top_sources, get_workspace_info, list_available_metrics,
list_recent_log_findings, list_repo_tree, narrate_report_sections, open_draft_pr,
query_asset_graph, record_finding, search_repo, suggest_fix, whoami
```

`open_draft_pr` is in that list. So is `record_finding` — the tool that puts a finding on the board.
So is every tool of `ai_governance_agent`, shipped days ago. Nobody would argue these are dead
weight; several are the product.

The reason is mundane and it applies equally to the CRUD fleet: **this cluster has run one workload
— the scheduled finding-dispatch pipeline.** 12,103 of the log rows belong to TriageAgent. The
tools that get called are the tools that pipeline calls. Everything reachable only from chat reads
as zero, whether it is `open_draft_pr` or `create_task`.

**A zero here measures which surfaces have been exercised, not which tools have value.** That is the
finding, and it is the reason this document does not stop at §2.

---

## 4. The CRUD fleet is reachable — six ways

The four agents are `@register_agent`-ed at Django startup by directory auto-discovery
(`.../langchain/agents/__init__.py:29-49`, invoked from `components/agents/cli/apps.py:11-24`).
Dropping the module in the directory *is* the registration; there is no import list to prune.

| # | Path | Evidence |
|---|---|---|
| 1 | **The active planner prompt** | `planner.system.yaml` `active: v12`. All four get a dedicated `because`-backed routing bullet: `task_agent` `:2591`, `project_agent` `:2592`, `workspace_agent` `:2593`, `user_agent` `:2594`. Plus few-shot examples naming them as the `agent_type` value (`:2669`, `:2821`, `:2851-2857`). |
| 2 | **The planner's agent catalog** | `llm_planner._build_agent_catalog()` (`:55-80`) iterates `AgentRegistry.list_agents()` live. Anything registered is automatically offered to the planner. Its only hardcoded fallback string is `"- workspace_agent: default fallback agent."` |
| 3 | **REST endpoint defaults** | `POST /ai/chat/agent-chat/` → `agent_type=request.data.get("agent_type") or "workspace_agent"` (`controller.py:2584`). `POST /ai/agents/deep/run-plan/` and `.../plan-and-run/` → `or "task_agent"` (`:1313`, `:1376`). Mirrored in four request/command DTO defaults. |
| 4 | **Entitlements** | `resolve_agent_entitlement` is **opt-out** (`agent_entitlements.py:92-145`) — an absent `WorkspaceAgentType` row means *enabled*. On this cluster only `ai_teammate` has explicit rows; the other 13 types are enabled everywhere by omission. |
| 5 | **Celery** | `run_deep_plan_and_run` / `run_deep_run_plan` pass `agent_type` through verbatim, so `task_agent` is the default worker slug on the deep-run queue. |
| 6 | **Seeded `AgentType` rows** | `sync_agent_types_from_registry()` upserts a row per registered agent at boot, `is_active=True`, carrying an importable `class_path`. All 14 are present in the live `ai_agenttype` table. |

### The chat surface *has* been used, and it lands on `workspace_agent`

User-facing conversations (`ai_conversations` where `metadata.internal` is unset):

| agent_type | conversations | messages | first | last |
|---|--:|--:|---|---|
| **`workspace_agent`** | **7** | **20** | 2026-07-30 | **2026-08-19** |
| `code_security_agent` | 4 | 254 | 08-09 | 08-12 |
| `triage_agent` | 2 | 6194 | 07-28 | 07-28 |
| `log_analytics_agent` | 1 | 2 | 07-31 | 07-31 |
| `optimization_agent` | 1 | 132 | 07-31 | 07-31 |
| `posture_agent` | 1 | 16 | 07-30 | 07-30 |

`workspace_agent` is the largest group of real chat sessions, the most recent is *yesterday*, and it
got there by being the endpoint's default. Over those 20 messages **not one workspace_agent tool was
selected** — which is a statement about the tools' usefulness in chat, and a much more interesting
one than a bare zero.

### One live dependency inside the fleet

`TriageAgent` — the most-used agent in the system — does not have its own task tools. It re-exports
five functions from `tools/task_agent.py`:

| TriageAgent tool | delegates to | recorded calls |
|---|---|--:|
| `assign_task` | `task_tools.assign_task` | **637** |
| `get_members_without_tasks` | `task_tools.get_members_without_tasks` | **117** |
| `get_team_members` | `task_tools.get_team_members` | **73** |
| `list_open_findings` | `task_tools.list_workspace_tasks` | **47** |
| `record_finding` | `task_tools.create_task` | 0 (registered) |

**874 recorded calls run through `tools/task_agent.py`.** The module is load-bearing for the SOC
triage path. `components/agents/tests/_helpers/agent_capability_inventory.py:76-78` already records
this as `SHARED_TOOLS`. Any proposal that deletes the module breaks the busiest agent in the
product.

Two DRY defects fall out of this and are worth fixing on their own merits:

- The **same function carries two different risk tiers** depending on which agent registered it.
  `TriageAgent.assign_task` declares `risk=ToolRisk.REVERSIBLE_WRITE`; `TaskAgent.assign_task`
  declares nothing and resolves to `read`.
- The **same function is exposed under two names** — `list_workspace_tasks` / `list_open_findings`,
  and `create_task` / `record_finding`.

---

## 5. Hidden dependencies — the `LOGIN_REDIRECT_URL` class

These are the references a grep for `def create_task` will not find. Each one is a way a deletion
turns into an outage or a red build.

| # | Dependency | Where | Consequence of deleting the tool/agent |
|---|---|---|---|
| H1 | **`workspace_agent` is the agent-chat default** | `controller.py:2584`, `agent_chat_request.py:24`, `agent_chat_command.py:32`, `agent_chat_use_case.py:447` | Every chat request that omits `agent_type` resolves to a non-existent type. The *default* path breaks, not an unused one. |
| H2 | **`task_agent` is the deep-run default** | `controller.py:1313`, `:1376`, `deep_run_plan_request.py:15`, `deep_plan_and_run_request.py:16` | Same, for both deep-run endpoints and the Celery worker slug. |
| H3 | **`_TOOL_RISK`'s only two keys belong to this fleet** | `tool_risk.py:85-89` — `delete_task`, `delete_project_milestone` | `tests/architecture/test_tool_risk_map_is_live.py` (F6) fails immediately. |
| H4 | **`red_team_v1.json` pins `list_workspace_members`** | `components/agents/tests/prompt_eval/datasets/red_team_v1.json:98`; runner `test_red_team.py:134-148` is **not** env-gated | Red-team suite fails: the case asserts the tool exists on the live agent surface *and* asserts its risk tier. |
| H5 | **`test_planner_agent_routing.py:533-576`** | every agent slug named in a routing bullet or example must exist in `AgentRegistry` | Deleting an agent named in the v12 prompt fails this unit test until the prompt is edited too. |
| H6 | **`test_agent_defaults_contract.py:103-115`** | every `DEFAULT_AGENT_TYPES` `class_path` must import | `task_agent`, `project_agent`, `user_agent` are in that list. Deleting the class breaks the import assertion. |
| H7 | **`CANONICAL_TOOLS` exact-match** | `test_agent_capability_inventory.py`; `test_tool_smoke_runtime.py` parametrizes over it and asserts registration at `:263` | Every removed tool must be removed from the inventory in the same change. |
| H8 | **`perceived_error_scan.py:111`** | `agent_type="workspace_agent"` — the ADR 0032 perceived-error replay agent | A replay scan shipped *this week* names the agent explicitly. |
| H9 | **`agent_domain_map.py:12-14`** | `task_agent`/`project_agent` → `project`, `user_agent` → `identity`; pinned by `test_planner_agent_routing.py:383` | Domain mapping and its test. |
| H10 | **DB-resident `custom_profile.tool_whitelist`** | `base.py:1697-1750`; persisted through `agent_profile_repository.py:196` | Tool names are load-bearing strings in customer data. Null on this cluster, but no source grep can ever prove that for a customer database. ADR 0031 D8 already says names are permanent. |
| H11 | **Seeded `ai_agenttype.class_path`** | 14 live rows carry importable dotted paths | Deleting a class leaves a stale row whose `class_path` no longer imports; the sync upserts but does not prune. |
| H12 | **`ai_conversations.metadata.agent_type`** | 7 historical `workspace_agent` conversations | Existing conversation history references the slug. |

### The frontend, checked both ways

`src/` and the built bundle (`build/static/js/main.*.js`) were both swept for all 53 tool names and
the four agent identifiers.

- **Tool names: zero hits, in `src/` and in the bundle.** Not even as unrelated same-named REST or
  hook functions — the frontend uses camelCase service functions, so there is no collision to
  disambiguate.
- Agent slugs: 6 hits, all in one dead file, `src/domain/agents/agentTypes.ts` (which also maps
  `donation_agent`, `sponsorship_agent`, `fundraising_agent` — contexts this fork deleted). Its only
  consumer, `createAgentInstance`, is reached solely through
  `useAgentCatalogPresentation.createAgent`, which no component ever calls.
- **There is no agent-type picker.** `loadAvailableAgentTypes` exists and is never invoked. The
  visible agent ring (`v2Constants.js` `RING_HEXES`) is Log Intel / Threat Hunt / Recon / Triage /
  Investigate / Detections / Alerts / Playbooks — no Task, Project, Workspace or User agent.
- `tests/qa/`: **zero hits** of anything.

So the fleet is reachable from the backend and invisible from the product. That asymmetry is the
real state of things, and it is what makes "unused-but-reachable" the right verdict rather than
either extreme.

---

## 6. A defect the count surfaced: 40+ write tools are classified `read`

`resolve_tool_risk` falls back to `ToolRisk.READ` for any tool with no `@tool(risk=...)` and no
`_TOOL_RISK` entry (`tool_risk.py:92-97`). **All 53 CRUD tools carry no `risk=`**, and `_TOOL_RISK`
names only two of them. So every one of the following resolves to `read`:

`create_organization`, `update_organization`, `manage_organization_privacy`,
`manage_organization_team`, `manage_organization_tags`, `manage_organization_categories`,
`manage_organization_operations`, `create_task`, `assign_task`, `update_task_status`,
`update_task_title`, `update_task_due_date`, `add_task_comment`, `start_task_timer`,
`stop_task_timer`, `create_project`, `update_project`, `assign_project_team`, `create_project_task`,
`create_project_milestone`, `update_project_milestone`, `manage_project_budget`, …

`create_organization` **creates a new tenant** — a `Workspace` row, `privacy` defaulting to
`"public"`, owned by the agent's user — and it is gated as a read. That is the exact failure
`tool_risk.py`'s own module docstring warns about:

> Under-classifying an irreversible money tool as `read` is the failure this module exists to
> prevent — when in doubt, classify UP.

This is independent of whether the fleet stays or goes, and it is the strongest argument for
conversion over "leave them": leaving 40 undeclared write tools at the read tier is a live
misclassification, and Phase 4 is the change that fixes it.

Two related content defects in the same neighbourhood:

- `manage_organization_team` is described to the model as *"Add or remove organization team
  members"* but mutates `Workspace.followers` — the nonprofit social graph, not membership. The v12
  planner prompt routes *"inviting or removing workspace members"* to `workspace_agent`, so the
  prompt promises a capability the tool does not deliver. `get_organization_followers` reads the
  same graph (and leaked follower email addresses cross-tenant until #439).
- The v12 prompt at `:2611` routes report verbs to `workspace_agent.generate_organization_report`
  in older versions; `generate_organization_report` exists in the tool module and **is not
  registered as a tool at all** (§7, D4).

---

## 7. Per-tool verdicts

Three verdicts, per the brief:

- **live** — recorded calls, or delegated into a live security agent, or pinned by an ungated test.
- **unused-but-reachable** — 0 calls, but registered, entitled by default, and named in the active
  planner routing table or reachable as an endpoint default.
- **dead** — not registered, or not reachable by any path.

### 7.1 `tools/task_agent.py` — 22 registered tools

| tool | verdict | evidence |
|---|---|---|
| `assign_task` | **live** | 637 calls via `TriageAgent.assign_task` |
| `get_members_without_tasks` | **live** | 117 calls via TriageAgent |
| `get_team_members` | **live** | 73 calls via TriageAgent |
| `list_workspace_tasks` | **live** | 47 calls via `TriageAgent.list_open_findings` |
| `create_task` | **live** | registered on TriageAgent as `record_finding`; pinned by `test_agents_task_permissions.py` |
| `delete_task` | unused-but-reachable | `_TOOL_RISK` key (H3); `test_task_edit_and_comment_tools.py` |
| `start_task_timer`, `stop_task_timer`, `get_task_timer_status` | unused-but-reachable | `test_task_timer_tools.py` — same use cases as the Kanban play button |
| `update_task_title`, `update_task_due_date`, `add_task_comment`, `list_task_comments` | unused-but-reachable | `test_task_edit_and_comment_tools.py` |
| `get_user_tasks` | unused-but-reachable | `test_agents_task_tools_guidance.py` |
| `parse_task_request`, `break_down_task`, `get_task_assignment`, `get_projects`, `get_due_tasks`, `update_task_status`, `get_task_progress`, `check_task_permissions` | unused-but-reachable | v12 routing bullet `:2591`; deep-run endpoint default (H2) |

**0 dead.** The module is the SOC triage agent's task layer.

### 7.2 `tools/project_agent.py` — 15 registered tools + 4 orphans

| tool | verdict | evidence |
|---|---|---|
| `generate_project_report` | unused-but-reachable | named in v12 `:2592`, `:2611` |
| `list_projects`, `get_project_info` | unused-but-reachable | named in the v12 project-resolution rule |
| `update_project`, `update_project_milestone`, `delete_project_milestone` | unused-but-reachable | `test_project_edit_and_milestone_tools.py`; `delete_project_milestone` is a `_TOOL_RISK` key (H3) |
| `check_project_permissions` | unused-but-reachable | `test_agents_project_permissions.py`; rebound to the run's workspace by #439 |
| `create_project`, `assign_project_team`, `create_project_task`, `get_project_tasks`, `get_project_timeline`, `create_project_milestone`, `get_project_analytics` | unused-but-reachable | v12 routing bullet `:2592` |
| `manage_project_budget` | unused-but-reachable — **trim candidate** | writes `Project.budget` / `spent_amount` and renders `$` amounts. The `budgeting` context was stripped from this fork; this is the last nonprofit money surface reachable from chat. |
| **`update_project_status`** | **dead** | module function, no `@tool` registers it, no caller |
| **`update_task_status`** (project module) | **dead** | duplicate of the task-module tool; no registration, no caller |
| **`get_project_risks`** | **dead** | no registration, no caller. Reads a `Risk` model whose name means something entirely different in a SOC product. |
| **`add_project_risk`** | **dead** | no registration, no caller |

### 7.3 `tools/workspace_agent.py` — 12 registered tools + 1 orphan

| tool | verdict | evidence |
|---|---|---|
| `get_organization_info` | unused-but-reachable | v12 `:2617` routes every "tldr / overview / who are we" goal here; the agent-chat default (H1) |
| `get_organization_analytics` | unused-but-reachable | named in v12 `:2593`, `:2611` |
| `check_organization_permissions`, `update_organization`, `manage_organization_categories`, `manage_organization_tags`, `manage_organization_privacy`, `get_organization_operations`, `manage_organization_operations` | unused-but-reachable | v12 `:2593`; `test_tool_tenancy_binding.py` pins cross-tenant refusal for each |
| **`create_organization`** | unused-but-reachable — **trim candidate, highest priority** | Creates a **new tenant** from chat, `privacy` default `"public"`, classified `read`. Not named in the v12 routing table. ADR 0031 D1 reserves cross-tenant surfaces for staff/support and says adding one is a security review. |
| **`manage_organization_team`** | unused-but-reachable — **trim candidate** | Mutates `Workspace.followers`, not membership, while describing itself to the model as team-member management (§6). |
| **`get_organization_followers`** | unused-but-reachable — **trim candidate** | Reads the same nonprofit social graph; leaked follower emails cross-tenant until #439. |
| **`generate_organization_report`** | **dead** | module function, no `@tool` registers it — yet archived planner versions route report verbs to it by name |

### 7.4 `tools/user_agent.py` — 4 registered tools

All four are **live**, and this is the one part of the fleet with an unambiguous SOC reading — "who
is in this workspace, and what did they do".

| tool | verdict | evidence |
|---|---|---|
| `list_workspace_members` | **live** | pinned by the **ungated** `red_team_v1.json:98` + `test_red_team.py:134-148` (existence *and* risk tier) |
| `search_workspace_members` | **live** | v12 `:2613` — *"workspace members are the only people directory in this system"* |
| `get_user_profile` | **live** | v12 `:2613` |
| `list_user_activity` | **live** | actor-scoped `EntityAuditLog` read behind an owner/admin gate; `test_user_agent.py` |

`tools/user_agent.py` was deliberately maintained **yesterday** by #425, which rewrote its
docstrings to record that `search_workspace_members` is now the *only* people lookup in the system
because identity's `UserSearch` endpoint was deleted. That is the opposite of abandonment.

### 7.5 Outside the fleet — three genuinely dead modules

Found while tracing reachability; each is unreferenced, not merely uncalled.

| module | verdict | evidence |
|---|---|---|
| `tools/agent_bridge.py` | **dead** | `create_agent_tool` has **zero production call sites**. The only references anywhere are a comment in `test_tool_risk_map_is_live.py:116`, two doc mentions, and a README snippet importing a path that no longer exists. ADR 0031 D4 says "Path 3 → keep"; the evidence says nothing has ever used it. |
| `infrastructure/adapters/actions/detectors/tasks.py` | **dead** | 7 detector classes calling `context.invoke_agent('task_agent', ...)`. `detector_cycle.py:61-76` imports six detector modules and this is not one of them; detectors register at import time, so none of these ever enter `_DETECTOR_REGISTRY`. |
| `infrastructure/adapters/actions/detectors/projects.py` | **dead** | same — `agent_type="project_agent"` at `:169`, module never imported |

---

## 8. Verdict tally

| verdict | count | |
|---|--:|---|
| **live** | 9 | 5 task functions the SOC triage agent depends on (874 recorded calls) + all 4 user_agent tools |
| **unused-but-reachable** | 44 | registered, default-entitled, named in the active v12 planner routing table |
| **dead** | 5 tool-module functions | `update_project_status`, `update_task_status` (project module), `get_project_risks`, `add_project_risk`, `generate_organization_report` |
| **dead** | 3 modules | `agent_bridge.py`, `detectors/tasks.py`, `detectors/projects.py` |
| **trim candidates** (registered and reachable, but arguably should not be) | 4 | `create_organization`, `manage_organization_team`, `get_organization_followers`, `manage_project_budget` |

The trim named in §"The answer, first" is those **4 registered tools + the 5 dead functions = 9**,
plus the 3 dead modules. Separately, §4's duplicate-name pairs (`list_workspace_tasks` /
`list_open_findings`, `create_task` / `record_finding`) are a DRY fix, not a deletion.

**53 CRUD tools. 0 recorded calls. 0 dead by reachability. 5 dead functions behind them.**

That sentence is the whole answer. The tools are not called; they are also not dead; and the
distance between those two facts is entirely explained by which surfaces this cluster has exercised.

---

## 9. What follows from this

1. **Convert the 53.** They carry no `scope`, no `risk`, no `provenance`, no `failure_mode` — while
   being one HTTP request from executing, with 40+ writes gated as reads. Declaring them is the
   Phase 3 contract applied to the surface that most needs it. See the conversion PR.
2. **Correct the risk tiers.** Writes → `reversible_write` (behaviour-neutral: the autonomy cap and
   the approval gate both treat `read` and `reversible_write` identically today, so the tier becomes
   *true* without changing what runs). `create_organization` → `irreversible`, which is a
   deliberate, ADR-D8-sanctioned raise and the conservative interim while its deletion is decided.
3. **Trim, on Henry's word only.** The deletion proposal is a separate document —
   [`AGENT_TOOL_DELETION_PROPOSAL_2026-08-20.md`](AGENT_TOOL_DELETION_PROPOSAL_2026-08-20.md). Nothing
   is deleted here.
4. **D9's tool-count ceiling still bites.** `task_agent` at 25 and `project_agent` at 18 remain
   above the ~10-15 band. Trimming the 9 named tools takes `workspace_agent` to 9 and
   `project_agent` to 14. `task_agent` stays at 25 and the honest fix there is decomposition, not
   deletion — five of its tools already belong to TriageAgent's surface.

## 10. What could not be verified

- **Any usage before 2026-07-26.** The compose-era database is gone. Every zero in this document is
  a zero *since the k8s pivot*.
- **Customer `tool_whitelist` data.** Null in all 10 rows here; a source grep can never establish
  that for a deployed customer database. Treated as a live constraint (H10) regardless.
- **The MCP surface.** `POST /ai/chat/agent-chat/` is auto-exposed as an MCP tool and the route is
  mounted unconditionally, so the fleet is reachable there too. Read from code, not exercised —
  and it is ADR 0031 OQ1, not this document's question.
- **Whether the 20 `workspace_agent` chat messages produced no tool calls because the planner
  re-routed, or because the model declined the tools.** The run-level attribution needed to separate
  those is not in `tool_observation`. Either reading supports the same verdict.
