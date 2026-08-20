# Agent Tool Inventory & Cross-Cutting Audit — 2026-08-20

Evidence base for [ADR 0031](../adr/0031-agent-tool-contract-and-registry.md). Every claim carries a
`file:line`. Anything inferred rather than read is labelled **hypothesis**.

Verified against `origin/main` @ `f85804f`, and against the live cluster image for the LangChain
version facts (`kubectl -n autosec exec deploy/api -- python -c "import langchain; ..."`).

---

## 0. Headline numbers

| | |
|---|---|
| Registered agent classes | **14** (`@register_agent`, `agents/*.py`) |
| `@tool`-decorated methods | **101** |
| Universal tools appended by the framework | **1** (`retrieve_workspace_context`, `base.py:1022`) |
| Distinct tool names reachable by an agent | **102** |
| Tools declaring a risk tier | **46 / 101** (46%) |
| Tools declaring `@requires_role` | **1 / 101** (`user_agent.py:124`) |
| Tools returning a structured result (`ToolResult`) | **4 / 101** — and all 4 are flattened to a string before anything can read the `ok` bit (`base.py:513`) |
| Tool bodies wrapping the whole body in `except Exception` → flat string | **50 / 83** tool-body functions in `tools/*.py` |
| Distinct routes by which a capability reaches an agent | **4** (§2) |
| Distinct, non-communicating "may the AI do this" policies | **4** (§3.2) |

---

## 1. The tool inventory

`_setup_tools` (`base.py:824-899`) promotes `@tool` methods to `StructuredTool`s and then appends
`retrieve_workspace_context` to **every** agent. `WorkspaceContextMixin` (`agents/_mixins.py:18`)
adds `whoami` + `get_workspace_info` to every agent that inherits it — all except
`workspace_agent` (`agents/workspace_agent.py:29`, which inherits `BaseAgent` alone).

"Effective" = declared + mixin (2, where inherited) + RAG (1).

| Agent (slug) | file | declared | effective | Risk tiers declared | `handles` a routable source? |
|---|---|---:|---:|---|---|
| `task_agent` | `agents/task_agent.py:16` | 22 | **25** | 0 / 22 | — |
| `project_agent` | `agents/project_agent.py:17` | 15 | **18** | 0 / 15 | — |
| `triage_agent` | `agents/triage_agent.py:54` | 14 | **17** | 11 / 14 | `ai.log_watch`, `ai.cloud_exposure`, `ai.container_security` |
| `workspace_agent` | `agents/workspace_agent.py:29` | 12 | **13** | 0 / 12 | — |
| `code_security_agent` | `agents/code_security_agent.py:41` | 10 | **13** | 10 / 10 | `ai.code_security` |
| `ai_governance_agent` | `agents/ai_governance_agent.py:70` | 6 | 9 | 6 / 6 | — |
| `posture_agent` | `agents/posture_agent.py:66` | 5 | 8 | 5 / 5 | — |
| `log_analytics_agent` | `agents/log_analytics_agent.py:38` | 4 | 7 | 4 / 4 | — |
| `user_agent` | `agents/user_agent.py:37` | 4 | 7 | 0 / 4 | — |
| `log_watch_agent` | `agents/log_watch_agent.py:36` | 2 | 5 | 0 / 2 | — |
| `optimization_agent` | `agents/optimization_agent.py:39` | 2 | 5 | 2 / 2 | `ai.log_optimization` |
| `report_agent` | `agents/report_agent.py:57` | 2 | 5 | 2 / 2 | — |
| `workflow_agent` | `agents/workflow_agent.py:53` | 1 | 4 | 1 / 1 | — |
| `ai_teammate` (orchestrator) | `agents/ai_teammate_agent.py:39` | 0 | 0 | n/a | n/a — `NON_SPECIALIST_AGENT_TYPES` (`shared_kernel/domain/triage.py:171`) |

Full per-tool listing with input schema and write targets is reproducible in one command — this is
deliberate, because a hand-maintained list is exactly the drift shape
`.claude/rules/skills-and-plugins.md` was written about:

```bash
python3 - <<'EOF'
import ast, pathlib
for f in sorted(pathlib.Path("components/agents/infrastructure/adapters/langchain/agents").glob("*.py")):
    t = ast.parse(f.read_text())
    for c in (n for n in ast.walk(t) if isinstance(n, ast.ClassDef)):
        for m in (i for i in c.body if isinstance(i, ast.FunctionDef)):
            d = [ast.unparse(x) for x in m.decorator_list]
            if any(x.startswith("tool(") for x in d):
                print(f"{f.name}:{m.lineno}\t{c.name}.{m.name}\t{d}")
EOF
```

### 1.1 The two shapes of tool body

Tool methods on the agent class are thin; the body lives in a sibling module under `tools/`.

- **Board-acting specialists** (`triage_agent`, `code_security_agent`, `optimization_agent`)
  delegate into the shared choreography `tools/_finding_processing.py::process_pending_finding`
  (`:194`) — fetch the pending card, run an advisor, then under a `select_for_update` row lock
  re-check status, comment, move the column, stamp `triaged`, append provenance.
- **CRUD agents** (`task_agent`, `project_agent`, `workspace_agent`, `user_agent`) call a
  per-tool function in `tools/<agent>.py` that opens its own queryset, does its own scoping, and
  wraps everything in `except Exception → "Error ...: {exc}"`.

That split is the whole story of this audit. The first shape is good and its cross-cutting concerns
are handled once. The second shape re-implements everything per tool.

---

## 2. Registration paths — **there are four, not one**

This is the headline finding, because it is the thing that makes "add a tool once, use it anywhere"
impossible today.

| # | Path | Where | Gets `_risk_gated`? | Gets `_serialize_tool_result`? | Gets rubric / DeepRun / Langfuse? |
|---|---|---|---|---|---|
| 1 | `@tool` decorator → `_decorated_tools` → promotion loop | `base.py:73-100`, collected `base.py:683-713`, promoted `base.py:842-892` | **yes** (`base.py:875`) | **yes** (`base.py:883`) | yes |
| 2 | Universal RAG tool, constructed directly | `base.py:1022-1035` | **no** | **no** | yes |
| 3 | Sub-agent-as-tool bridge | `tools/agent_bridge.py:92` (`StructuredTool.from_function`) | **no** | **no** | partial |
| 4 | MCP JSON-RPC server, auto-derived from the OpenAPI schema | `infrastructure/api/mcp/views.py:475-521`, routed unconditionally at `api/urls.py:40` | **no** | n/a | **no** |

**Path 2 is the sharpest illustration of why the current seam is wrong.** The one tool that *every
single agent* has is the one tool that bypasses the framework's gate wrappers — not because anyone
decided that, but because the wrappers are applied inside a `for` loop over `_decorated_tools`
(`base.py:844`) and this tool never enters that loop. It is read-only today, so there is no live
exposure; the *structure* is the defect. Any future tool built the same way inherits the same hole
silently.

**Path 4 is a different product surface wearing the same word.** `infrastructure/api/mcp/views.py`
does not expose agent tools at all — it walks `schema["paths"]` and emits one MCP tool per
`(path, method)` DRF operation (`:485`), then executes by proxying an HTTP request back into the
same Django app (`:855`, `:871-880`). Two consequences worth stating plainly:

- Its authentication is **presence of a non-empty `Authorization` header** — `views.py:91-95`:
  ```python
  auth_header = request.headers.get("Authorization")
  return bool(auth_header and auth_header.strip())
  ```
  The module docstring is honest about it (`views.py:6-7`) and a test pins the behaviour
  (`tests/test_mcp_views.py:64-70`). The route is unconditional — no flag, no setting
  (`api/urls.py:40`, inside the `infra_patterns` block concatenated at `:100-102`).
- `POST /api/v1/ai/chat/agent-chat/` (`components/agents/api/controller.py:2459`) is itself a DRF
  operation, so it is **in** the MCP tool list. The full deep-agent pipeline is therefore reachable
  by a second route with a materially weaker gate. `is_money_write_operation` does not exclude it
  (`views.py:544-556` — it is not a money path).

  *(Adjacent, out of scope for this ADR but worth a ticket:* `_get_auto_token` mints with a bare
  `AccessToken.for_user` (`views.py:116`), which carries no `sid` claim, and
  `SessionAwareJWTAuthentication` fails closed on a missing `sid`
  (`components/identity/api/authentication.py:59-66`). **Hypothesis, not runtime-verified:** in the
  service-identity configuration `tools/call` 401s on every authenticated endpoint while
  `tools/list` still works, because only the schema fetch has a 401-retry fallback
  (`views.py:396-402`).)*

There is also a **fifth, unrelated** thing called MCP in the tree:
`components/agents/infrastructure/adapters/tool_access/mcp_adapter.py:31-74` is an *outbound*
client for calling external MCP servers. Not connected to path 4. Naming collision only.

---

## 3. Cross-cutting concerns — handled once, or per tool?

### 3.1 Workspace / tenant scoping — **per tool, and one shared helper gets it backwards**

autosec is pooled-by-default (ADR 0029); `WorkspaceManager`
(`infrastructure/persistence/workspaces/models.py:51-53`) filters only on `status="active"`, so a
missing `workspace_id=` in a tool body *is* the tenant boundary with nothing behind it.

`self.workspace_id` is bound in `BaseAgent.__init__` (`base.py:728`) from the invocation context and
is not LLM-writable. **Roughly 60 tool bodies re-implement `workspace_id=agent.workspace_id`
inline.** Most get it right. Four helpers exist; three are safe, one is not.

| Helper | file:line | Behaviour |
|---|---|---|
| `_resolve_task_for_update` | `tools/task_agent.py:896` | safe — always `AND workspace_id=agent.workspace_id` (`:914`) |
| `_resolve_project_for_update` | `tools/project_agent.py:764` | safe (`:779`) |
| `pending_findings_qs` / `process_pending_finding` | `tools/_finding_processing.py:145` / `:254`,`:339` | safe; the best-designed seam in the layer |
| **`_resolve_org_id`** | **`tools/workspace_agent.py:138-157`** | **prefers the caller's value; the agent's workspace is only the fallback** |

```python
# tools/workspace_agent.py:153-157
    for key in ("organization_id", "workspace_id", "id"):
        candidate = _coerce_uuid(data.get(key))
        if candidate:
            return candidate
    return _coerce_uuid(getattr(agent, "workspace_id", None))
```

It feeds `_fetch_workspace`, which does **not** cross-check against `agent.workspace_id`:

```python
# tools/workspace_agent.py:131
        return Workspace.objects.get(id=org_id), None
```

Used at 10 call sites (`:253, 289, 326, 354, 390, 428, 456, 484, 514, 570`). The parameter is
**advertised to the model** in nine tool descriptions — e.g. `agents/workspace_agent.py:84`:
`"Input: organization_id (optional, defaults to current workspace), field, new_value"`. Sharpest
consequences:

- `update_organization` (`tools/workspace_agent.py:249`) does `setattr(org, field, new_value)`
  (`:269`) with `hasattr` as the only guard (`:266`) — an arbitrary-field write on an
  LLM-named workspace.
- `get_organization_followers` (`:425`) prints `username`, `email`, `date_joined` (`:443-447`).

`project_agent` has the same shape with **no fallback at all**:

```python
# tools/project_agent.py:667
        workspace = Workspace.objects.get(id=data["workspace_id"])
```

`check_project_permissions` never reads `agent.workspace_id`; `:673`/`:676` then derive `Team` /
`Project` from that workspace and return team titles (`:682`). Advertised at
`agents/project_agent.py:220`: `"Input: user_id, workspace_id."`

Related, same class: `_resolve_user_id` (`tools/project_agent.py:148-150`) lets the caller name
**whose** permissions get checked, and it is consumed by the `project:write` gate at
`tools/project_agent.py:1011-1013`.

**Read this as a design signal, not a bug list.** Nothing in the framework can tell the difference
between a tool that binds tenancy from the runtime and one that reads it out of an LLM-authored JSON
blob, because tenancy is not something a tool declares — it is something each tool remembers. That
is the gap ADR 0031 D1 closes.

Secondary, lower severity, same root: unscoped PK lookups (`tools/task_agent.py:74-88` global user
directory; `tools/project_agent.py:314`, `:340`, `:851`; `tools/workspace_agent.py:306`), name-based
cross-tenant workspace resolution (`tools/workspace_agent.py:205-207`, `__icontains`), and global
vocabulary pools where the sibling Tag pool was already fixed (`tools/workspace_agent.py:362`,
`:366`, `:526` vs the fixed `:405`).

### 3.2 Authorization — **four policies that do not know about each other**

| Policy | Where | Keyed on | Enforced at |
|---|---|---|---|
| `@requires_role` | `base.py:333-393` | membership role | tool call — **used once**, `agents/user_agent.py:124` |
| `ToolRisk` tiers | `application/policies/tool_risk.py:26-101` | tool **name** or `@tool(risk=)` | `_risk_gated`, `base.py:467-497` |
| MCP money denylist | `infrastructure/api/mcp/views.py:534-556` | **URL path substring** + verb | `build_tools` `:494`, `call_tool` `:830` |
| `AIPermissionGrant` / `ai_can` | `infrastructure/services/agent_permissions_service.py:185-224` | coarse action strings | inside 4 tool bodies |

Zero imports between the second and third. They encode the same intent in two vocabularies at two
layers with two enforcement points and two test suites, and they demonstrably disagree:
`_TOOL_RISK` marks `delete_transaction` IRREVERSIBLE (`tool_risk.py:84`) while the MCP predicate
returns `False` for `PATCH /budget/transaction/{id}/` — asserted as expected behaviour in
`infrastructure/api/mcp/tests/test_money_write_denylist.py:36`.

Two further facts about the risk map:

- **8 of its 10 entries are dead nonprofit fork-drift.** Verified — `manage_sponsorship_payments`,
  `cancel_sponsorship`, `cancel_recurring_donation`, `send_sponsor_update`, `delete_transaction`,
  `delete_news_article`, `delete_event`, `delete_estimate` are declared on **zero** agents. Only
  `delete_task` and `delete_project_milestone` are live.
- **55 of 101 tools declare no tier**, so `resolve_tool_risk` (`tool_risk.py:96-101`) defaults them
  to `READ` (`:40`). That silently includes `create_task`, `update_task_status`, `create_project`,
  `manage_project_budget`, `create_organization`, `update_organization`,
  `manage_organization_privacy`. The module's own docstring names this exact failure —
  *"Under-classifying an irreversible money tool as `read` is the failure this module exists to
  prevent"* — and the coverage gap means it is prevented only where someone remembered.

⚠️ **`ai_can` fails open on an empty action list**: `agent_permissions_service.py:220-221` —
`if "*" in actions or not actions: return True` — and `AIPermissionGrant.actions` defaults to `[]`
(`infrastructure/persistence/ai/models.py:222`). Any active `ai_executor` grant created without an
explicit action list authorises everything. Flagged for a separate ticket; not this ADR's scope.

### 3.3 Provenance / board write — **shared, and it reaches exactly the routed pillars**

`process_pending_finding` (`tools/_finding_processing.py:194`) is the cited good example, and it
holds up. Its reach, verified:

| Tool | call site |
|---|---|
| `triage_finding` | `tools/triage_agent.py:106` |
| `triage_cloud_exposure` | `tools/triage_agent.py:194` |
| `triage_container_vuln` | `tools/triage_agent.py:291` |
| `triage_code_finding` | `tools/code_security_agent.py:344` |
| `advise_optimization` | `tools/optimization_agent.py:108` |

Exactly five tools — one per entry in `ROUTABLE_SOURCE_TYPES`
(`shared_kernel/domain/triage.py:67-73`). The pattern is real, it is DRY, and every board-acting
specialist uses it.

**But the hard rule is "every AI action posts to the board as provenance", and the other 96 tools
are not board-acting.** `create_task`, `update_organization`, `open_draft_pr`,
`generate_pentest_report`, `draft_workflow` all mutate state and none writes provenance through a
shared path. Whether that rule is meant to bind every tool or only board-acting specialists is a
product question — ADR 0031 OQ3.

### 3.4 Failure semantics — **the dominant defect class, and it is structural**

Three sound-looking mechanisms exist and **none of them is connected to the other two**:

1. `ToolResult(ok=False)` (`base.py:48-67`) — used by exactly one module
   (`tools/log_analytics_agent.py:94,97,116,119,139,144,147`), and `_serialize_tool_result`
   (`base.py:499-515`, applied `base.py:883`) flattens it to `f"Error: {...}"` (`:60-61`) before
   anything can read `ok`. Byte-identical to the 49 hand-rolled error strings.
2. The `tool_observation` DeepRunLog row has a `status` field
   (`infrastructure/gateways/deep/logging.py:15`, default `""` at `:32`) — and
   `_persist_tool_observations` (`base.py:2253-2262`) **never passes it**. Every tool observation,
   success or failure, is written with `status=""`.
3. The honesty guard `_is_agent_failure_summary` (`deep/orchestrator.py:266-286`) matches seven
   `AgentExecutor` stop-strings (`:246-254`) against the **worker's final summary** — which is the
   LLM's own narration (`deep/adapters.py:70-76` → `base.py:1860`), not the tool output. It is
   structurally blind to the tool layer.

The consequence, traced end to end: `execute()` sets `success=True` (`base.py:1872`) and
`status=EXECUTION_STATUS_COMPLETED` (`base.py:1876`) **unconditionally** — `result_text` is never
inspected. The only path to FAILED is the outer `except Exception` (`base.py:1929`), which the 50
per-tool `except Exception` handlers have already prevented from firing.

`_invoke_graph_executor` makes it explicit — it moves the error into the success channel:

```python
# base.py:1592-1595
error = result.get("error")
if error:
    return {"output": f"Error: {error}"}
```

**Live instance of the defect class.** Six advisor services share
`logger.exception(...); return None` — `components/integrations/application/log_fix_advisor_service.py:128-130`,
`log_optimization_advisor_service.py:123-124`, `log_patch_advisor_service.py:405-406`,
`sast_patch_advisor_service.py:223-224`, `components/code_security/application/sast_fix_advisor_service.py:308-309`.
`process_pending_finding` consumes that `None` at `:270` and treats it as the *legitimate business
outcome* "no confident fix": it stamps `triage.status = "triaged"` with `suggested: False`
(`:412-424`), skips the draft-PR dispatch (`:465`), and returns
`f"Handled {task.title[:70]}: {', '.join(actions)}."` (`:488`).

An LLM-provider outage therefore produces "Handled CVE-xxxx: reviewed; no confident fix" on every
finding, marks every card triaged, opens no PRs, and reports a completed triage sweep — with
`DeepRunLog.status=""`, `AgentExecution.status="completed"`, `run_telemetry status="success"`, and
`worker_completed status="completed"`. Nothing anywhere distinguishes "the model had nothing to
say" from "the model was never reached".

Also: `agents/workflow_agent.py:136-146` returns `json.dumps({"status": "drafted_not_saved", ...})`
on a persistence failure — a JSON envelope that *looks* like success and carries `name`, `steps`,
`valid`. Highest narration risk in the fleet.

### 3.5 Idempotency / retries

Handled well where it is handled, and only there. `process_pending_finding` re-checks status under
`select_for_update` (`:339`); the dispatch engine leases per `(workspace, specialist)`
(`finding_dispatch_service.py:211-221`) and per finding (`:364-375`); enqueues go through
`transaction.on_commit` (`:235-237`, `:458`). `OpenDraftPrUseCase` short-circuits on an existing
`payload.draft_pr`.

Outside that path there is **no framework-level idempotency contract**. `create_task`,
`create_project`, `create_organization`, `draft_workflow`, `record_finding` have no dedup key. A
re-run after a worker crash replays them.

⚠️ `components/agents/infrastructure/tasks/agent_tasks.py:676` returns `{"success": True, ...}` even
when `outcome` is a `_record_draft_pr_blocked` result (`:905, :921, :924`) or
`{"pr_url": "", "reason": "design_change_no_pr"}` (`:902`).

### 3.6 Sign-off gating and the kill switch

The autonomy/approval ladder is real and correctly composed — `tool_risk.py:53-71` denies
`irreversible` to an autonomous run outright, and denies it to anyone until
`config["approval_granted"]` (`base.py:488`). `is_ai_service_principal` (`base.py:441-464`) gives
the autonomous detector a distinct principal, and `requires_role` checks it *before* the owner
resolution (`base.py:365-372`) so the write cap holds even if the AI is later granted a membership.

The kill switch is checked at three entry points — `application/service.py:86-99`,
`application/services/detector_cycle.py:211-218`, `finding_dispatch_service.py:171-208` — and it
fails safe (`:206-208`).

**The gap is coverage, not design.** The ladder only bites for the 46 tools that declared a tier
(§3.2). It is a good policy with a 46%-populated input.

### 3.7 Entitlement / feature-flag gating

**No feature flag is consulted anywhere in the LangChain tool layer.** Exhaustive grep over
`components/agents/infrastructure/adapters/langchain/**` returns zero hits for `is_feature_enabled`
/ `feature_flags_provider`. Flags gate *detectors* (`detectors/cloud_graph_sync.py:42-44`,
`cloud_graph_attack_paths.py:44-46`, `provenance.py:48-50`,
`finding_observed_bridge.py:53-58`) and the *board handler* (`finding_raised_board_handler.py:472`),
never tools.

**Hypothesis, high confidence:** capability flags enforced at the API/task boundary —
`feature.code_security` (`components/code_security/api/controller.py:41`),
`feature.container_security` (`components/container_security/api/controller.py:52`) — are **not**
re-checked when the same capability is reached through an agent tool.
`CodeSecurityAgent.get_repo_findings` / `search_repo` / `read_repo_file`
(`agents/code_security_agent.py:104-172`) read SAST findings and repo contents with no
`feature.code_security` check on the path.

The live trap named in the brief is already fenced on the *API* side —
`tests/architecture/test_feature_flag_not_sole_permission.py` exists and its docstring documents the
real incident that motivated it. Nothing equivalent exists for tools, because tools have no
permission-class concept to assert over. That is itself the argument for a declared contract.

How tool→agent availability is expressed today: **purely "the method is defined on that agent
class."** The only declarative controls are *subtractive* name filters —
`Agent.config.custom_profile.tool_whitelist` (`base.py:1355-1409`) and
`run_context.allowed_tools` / `blocked_tools` (`base.py:1323-1347`) — neither of which can grant a
tool the class does not define. `ALLOWED_AGENT_CAPABILITIES`
(`application/config/agent_capabilities.py:24`) is a frozenset of **one** element,
`{"open_draft_pr"}`, and it is enforced not in the tool but downstream in
`open_draft_pr_use_case.py:962-973`. Note it is always read off the workspace's **`triage_agent`**
row (`orm_agent_capability_repository.py:58-71`) even when `CodeSecurityAgent.open_draft_pr`
(`agents/code_security_agent.py:188-204`) is the caller.

### 3.8 Rubric grading — narrower than the skill suggests

- Flag `DEEP_RUBRIC_MIDDLEWARE_ENABLED`: **`False` in `api/settings/base.py:479`**; `True` in
  `local.py:665` and `dev.py:529`. **In production the RubricMiddleware is off** and the hand-rolled
  `WorkerCritic` (`deep/critic.py`) is the only verifier.
- Rubrics exist for **3** agent types — `deep/critic.py:58-67` (`triage_agent`), `:68-73`
  (`optimization_agent`), `:83-96` (`code_security_agent`) — gated by
  `CRITIC_ENABLED_AGENTS` (`critic.py:36`). `rubric.py:43` imports both from `critic.py`, so the two
  verifiers share one opt-in set and one rubric table. The other 11 agents are ungraded.
- Bypasses: the legacy `use_langgraph=True` path (`base.py:768` → `:1606-1608`) builds a separate
  graph with **no middleware and no rubric state** (`base.py:1569-1596`). Default off. And on
  `POST /ai/agents/<id>/execute/` the loop *runs* but the verdict is **discarded** — only
  `deep/adapters.py:216` consumes `rubric_evaluations`, so the direct-execute path re-runs the agent
  and leaves no telemetry.

Grading is applied to **agent output**, never to a tool call. Nothing grades whether a tool did what
it said.

### 3.9 Observability of a single tool call

| Signal | Written where | Per-tool? | Condition |
|---|---|---|---|
| `tool_usage[name]` count | `callbacks/telemetry.py:175-177` | yes (count only) | always |
| `tool_events[]` `{tool, input_chars, input_preview, output_chars}` | `telemetry.py:181-203` | yes, capped at 50 | always |
| `_durations_ms["tool"]` | `telemetry.py:194-197` | **no — summed across all tools** | always |
| `DeepRunLog` `tool_observation` | `base.py:2253-2262` | yes | **deep runs only** — early-returns without `run_id`/`plan_id` (`base.py:2213-2219`) |
| Langfuse span | `base.py:1093-1109` | via LC nesting | only if configured |
| Cost | — | **never** | — |

`DeepRunLog` has `latency_ms` and `cost_usd` columns
(`infrastructure/persistence/ai/agents/models.py:405-406`), but `log_deep_event`
(`gateways/deep/logging.py:11-36`) does not accept them — they are populated only on `llm_call` rows.
Per-tool wall clock *is* measured (`telemetry.py:180,194-197`) and then discarded into one summed
bucket, so **there is no way to answer "which tool was slow"** from anything this stack persists.
Cost is attributed per-run and per-*task* (`deep/adapters.py:231-240`), never per tool —
`cost_tracker.record_llm_call` is fed only from `on_llm_end` (`telemetry.py:246-254`); there is no
hook in `on_tool_start`/`on_tool_end`.

Tracing and telemetry are applied **once, by the framework** (`base.py:1069-1109`) and propagate to
nested tool runs. Exactly one tool emits bespoke events: the universal
`retrieve_workspace_context` closure uses `DeepRunContext.info/warn/report_progress`
(`base.py:926, 930, 985, 996, 1000, 1008, 1013`). **Zero tools under `tools/` accept a `ctx`.**

For a non-deep chat turn or `POST /ai/agents/<id>/execute/`, a tool executing produces **no durable
per-tool record at all**.

### 3.10 "Routable ≠ handled"

The invariant holds today — and only by hand. `is_routable_to_specialist`
(`shared_kernel/domain/triage.py:174-176`) returns True whenever `source_type ∈
ROUTABLE_SOURCE_TYPES` and the declared `agent_type ∉ NON_SPECIALIST_AGENT_TYPES`. It does **not**
check that the named specialist exists in `AgentRegistry`, has an `AgentType` row, or owns a tool
that can process that source type. The dispatched goal is generic —
*"Use your tools to list them and process each one"* (`finding_dispatch_service.py:89-96`) — so a
specialist with no matching tool produces nothing and the run still reports completed (§3.4).

Current state, cross-checked source-by-source:

| routable `source_type` | stamped `agent_type` | handling tool | OK? |
|---|---|---|---|
| `ai.log_watch` | `triage_agent` (`finding_raised_board_handler.py:452`) | `triage_finding` (`tools/triage_agent.py:106`) | ✅ |
| `ai.log_optimization` | `optimization_agent` (`:459`) | `advise_optimization` (`tools/optimization_agent.py:108`) | ✅ |
| `ai.cloud_exposure` | `triage_agent` (`:156`) | `triage_cloud_exposure` (`tools/triage_agent.py:194`) | ✅ |
| `ai.container_security` | `triage_agent` (`:201`) | `triage_container_vuln` (`tools/triage_agent.py:291`) | ✅ |
| `ai.code_security` | `code_security_agent` (`:265`) | `triage_code_finding` (`tools/code_security_agent.py:344`) | ✅ |

Five for five. That is the correct answer to report: **this is not currently broken.** It is
unenforced, and `.claude/rules/dry-reuse.md:36` already records that it has bitten before
(*"routable without a tool is a silent no-op"*). One `_SOURCE_BOARD` entry added without its
specialist's tool re-breaks it, invisibly. That is a fitness function's job, not a reviewer's.

---

## 4. Where the `wanjala-core:agents` kit skill disagrees with this code

The brief asked for this explicitly, and the divergence is substantial. The kit skill describes the
**nonprofit source platform**, and on the tool layer it is wrong about autosec in five ways:

| Kit skill claim | autosec reality |
|---|---|
| §3: "11 agents registered" — `sponsorship_agent`, `budget_agent`, `content_agent`, `donation_agent`, `financial_agent`, `fundraising_agent`, `grants_agent` | **14 agents, none of those seven exist.** The fleet is security-domain: triage, code_security, posture, log_analytics, log_watch, optimization, ai_governance, report, workflow |
| §2: "10 of the 11 agents still override `_setup_tools()` and construct `langchain.tools.Tool(...)` manually" | **One** override remains (`agents/ai_teammate_agent.py:64`, returns `[]`). Zero manual `Tool(...)` constructions in `agents/*.py`. The decorator migration is **done here** |
| §2/§10: the P0 tool shopping list (`list_recipients`, `list_campaigns`, `list_donors`, …) | Entirely nonprofit domain. Not applicable |
| §17 P1-5: "risk-tiered tool ladder — land BEFORE the money-write tools" (designed, not built) | **Built** — `application/policies/tool_risk.py` + `base.py:467-497`. 46% coverage |
| §17 P0-3 / P0-4: autonomous service principal + kill switch (designed) | **Both built** — `base.py:441-464`, `application/policies/ai_kill_switch.py` |
| §18: `RubricMiddleware` "convergence path (in flight)" | **Landed and wired** (`base.py:1190-1206`, `deep/rubric.py`) — but off in prod (`api/settings/base.py:479`) and scoped to 3 agent types |

The standing memory note is confirmed: treat the kit skill's §17/§18 as *aspirational for the source
repo*, and verify every middleware/orchestration claim against autosec's code. The pattern holds in
both directions — the skill **understates** what autosec has built as often as it overstates it.

---

## 5. What LangChain 1.x already gives us (verified against the pinned stack)

Pinned: `langchain==1.3.14`, `langchain-core==1.4.9`, `langgraph==1.2.9`, `deepagents==0.6.12`
(`requirements/base.txt:91-104`). Verified live in the running image:

```
$ kubectl -n autosec exec deploy/api -- python -c "..."
langchain 1.3.14
wrap_tool_call OK
ToolCallRequest OK          # fields: tool_call, tool, state, runtime
ToolRuntime OK
deepagents 0.6.12
RubricMiddleware OK
```

Three framework-native mechanisms map onto the gaps above, and **all three are already installed**:

1. **`wrap_tool_call` middleware** — the canonical seam for cross-cutting concerns around *every*
   tool call: authorization, error classification, retries, logging, provenance
   ([custom middleware](https://docs.langchain.com/oss/python/langchain/middleware/custom),
   [tool error handling](https://docs.langchain.com/oss/python/langchain/tools#error-handling),
   [v1 migration](https://docs.langchain.com/oss/python/migrate/langchain-v1#handling-tool-errors)).
   `ToolCallRequest` carries `tool_call` (name/args/id), `tool` (the `BaseTool`), `state` and
   `runtime`. This is the correct home for `_risk_gated` + `_serialize_tool_result`, and it catches
   registration paths 2 and 3 (§2) that the promotion-loop wrappers structurally cannot.

2. **`ToolRuntime` context injection** — a tool declares `runtime: ToolRuntime[Ctx]` and reads
   `runtime.context.workspace_id`; the parameter is **not** part of the schema the model sees
   ([runtime](https://docs.langchain.com/oss/python/langchain/runtime#inside-tools),
   [state injection](https://docs.langchain.com/oss/python/langchain/tools#state-injection)). This
   is the direct, by-construction fix for §3.1: a tenant id the model cannot write is a tenant id
   the model cannot cross.

3. **Dynamic tool selection via `wrap_model_call`** — filter `request.tools` by role, entitlement or
   flag before the model ever sees them
   ([context engineering](https://docs.langchain.com/oss/python/langchain/context-engineering#selecting-tools)).
   The framework-native home for `_apply_tool_policy` (`base.py:1323`) and for capability-based
   per-agent access.

**And the seam is already threaded.** `create_agent(..., middleware=self._build_agent_middleware())`
at `base.py:1151-1156` — and `_build_agent_middleware` (`base.py:1168-1207`) returns an **empty
list** unless the rubric flag is on. There is a wired, empty middleware chain sitting in front of
every tool call on every agent. That is the single most important fact in this document.

### On the "too many tools" question

Independent 2025-26 work reports selection accuracy degrading past roughly 10–15 tools, with
retrieval-based tool selection and specialist decomposition as the two standard answers
([tool selection at scale](https://tianpan.co/blog/2026-04-09-tool-selection-problem-agent-tool-routing-at-scale),
[the over-tooled agent problem](https://tianpan.co/blog/2026-04-19-over-tooled-agent-problem),
[ScaleMCP](https://arxiv.org/pdf/2505.06416)). autosec has already taken the decomposition answer:
14 specialists at 4–25 effective tools each rather than one agent with 102. Two agents sit above the
band — `task_agent` at 25 and `project_agent` at 18 (§1) — and both are inherited fork CRUD, not
security surface. **Recommendation: do not build tool-RAG.** Note the ceiling in the ADR, watch the
two outliers, and revisit only if a *security* specialist crosses 15.

---

## 6. Summary judgement

The security-domain half of this layer is well built. `process_pending_finding`, the dispatch
engine, the shared-kernel triage contract, the risk ladder, the autonomous principal and the kill
switch are all genuinely good, and several are better than the kit skill believes.

The gap is not that the design is wrong. It is that **the framework has no way to know what a tool
is** — every cross-cutting property lives in the tool author's memory instead of in a declaration
the registry can check. That produces the same shape at every concern: handled once where someone
built a helper, re-implemented (or forgotten) everywhere else, with 46%, 1%, 5-of-101 and 3-of-14
coverage numbers to show for it.

The fix is small, because the seam already exists and is empty.
</content>
</invoke>
