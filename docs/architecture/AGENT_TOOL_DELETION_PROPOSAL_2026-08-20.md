# PROPOSAL — the ADR 0031 Phase 4 trim. DECLINED. Nothing here is done, and nothing here should be done.

Status: **DECLINED by Henry, 2026-08-20.** Verdict: *"convert, don't delete — these will be needed."*

> **Do not execute this document.** It is kept as the record of an analysis, not as a backlog item.
> The measurement it rests on is sound and worth reading; the conclusion it invites was considered
> and rejected. The 53 CRUD tools stay, now carrying declarations (#446).
>
> The reasoning behind the decision, which the evidence itself supports: a zero call-count over this
> cluster's 24-day history measures **which surfaces were exercised, not which tools have value**.
> The same rule that would retire these tools would also retire `open_draft_pr` — 29 of the 79
> never-recorded tools live on the *security* agents. And `tools/task_agent.py`, whose deletion this
> document contemplated, carries **874 recorded calls** because TriageAgent re-exports five tools
> from it.
>
> **Two items here are bugs, not dead code, and remain open on their own merits:**
> `detectors/tasks.py` and `detectors/projects.py` are never imported, so **7 detector classes never
> register**. That is a wiring defect to fix, not surface to delete. `agent_bridge.py` having zero
> production callers still contradicts ADR 0031 D4's decision to keep it — worth reconciling in the
> ADR rather than resolving with `rm`.

Original status when opened: proposal, 2026-08-20, awaiting Henry. No code was deleted by this
document or its PR.

Evidence: [`AGENT_TOOL_USAGE_EVIDENCE_2026-08-20.md`](AGENT_TOOL_USAGE_EVIDENCE_2026-08-20.md) —
every claim below is measured there. Read that first; this document only says *what to remove and
what it costs*.

Companion to the conversion, which is a separate PR and does not depend on this one. The conversion
stands whether or not any of this is approved; approving any of this makes a small part of the
conversion redundant, which is the correct order (declare first, delete later, never the reverse).

---

## The shape of the ask

The OQ4 evidence found **zero dead tools by reachability** in the CRUD fleet and **9 dead functions
plus 3 dead modules behind it**. So this is not "delete the fleet". It is four separate, differently
sized decisions:

| # | What | Size | Needs Henry? |
|---|---|---|---|
| **A** | 5 unregistered functions in the tool modules | ~200 lines, zero callers | Rubber stamp |
| **B** | 3 unreferenced modules | ~350 lines | Rubber stamp, with one ADR correction |
| **C** | 4 registered tools that arguably should not exist | 4 tools, ~180 lines | **Real decision** |
| **D** | `task_agent` at 25 tools, above D9's band | Design change | **Real decision, and not a deletion** |

A and B are dead code by any definition and are proposed for execution once seen. C is a product and
security judgement. D is named so it is not lost, and explicitly **not** proposed as a deletion.

---

## A — five unregistered functions (zero risk)

Each lives in a tool module, is registered by **no** `@tool`, and is called by **nothing**. They are
not "unused tools"; they are functions no agent can reach.

| function | file | note |
|---|---|---|
| `update_project_status` | `tools/project_agent.py` | superseded by `update_project`; never registered |
| `update_task_status` | `tools/project_agent.py` | a **duplicate** of the task-module tool of the same name, in the wrong module |
| `get_project_risks` | `tools/project_agent.py` | reads a `Risk` model. In a SOC product "risk" means something else entirely, and this is not it. |
| `add_project_risk` | `tools/project_agent.py` | writes the same model |
| `generate_organization_report` | `tools/workspace_agent.py` | **archived planner prompt versions route report verbs to it by name** — see the trap below |

### The trap, and why it argues *for* deleting

`generate_organization_report` is the one that matters. **Seven consecutive planner prompt versions
— v2 through v8 — routed report verbs to `workspace_agent.generate_organization_report` by name, and
the tool was never registered on the agent.** For those seven versions the planner was directing
"write me an impact report" to a capability the target agent did not have.

v9 dropped the clause and v12 (active) routes report verbs to `get_organization_analytics` instead,
so this is **not a live misroute** — it is a fixed one whose corpse is still in the tree. But it is
a clean worked example of the failure `.claude/rules/dry-reuse.md` already records — *"routable
without a tool is a silent no-op"* — and it is the same shape ADR 0031 D6/F2 exists to make
impossible. Deleting the function completes a removal that stopped halfway.

**Cost of A:** four of the five are in F4's ratchet list
(`_PROJECT/add_project_risk`, `_PROJECT/get_project_risks`, `_PROJECT/update_task_status`, and
`_PROJECT/_calculate_duration` is adjacent), so `KNOWN_BLANKET_STRING_HANDLERS` must shrink in the
same commit — which `test_the_known_list_has_no_stale_entries` already enforces. Nothing else moves.

---

## B — three unreferenced modules (zero risk, one ADR correction)

### B1 — `tools/agent_bridge.py`

`create_agent_tool` builds a `call_<agent_type>` delegation tool. It has **zero production call
sites**. The only references in the tree are a comment in `test_tool_risk_map_is_live.py:116`, two
doc mentions, and a `README.md` snippet importing `apps.ai.agents.tools.agent_bridge` — a path that
has not existed since the fork.

**This contradicts ADR 0031 D4**, which says:

> **Path 3 (`agent_bridge.create_agent_tool`)** → keep, but it is a **delegation** primitive, not a
> tool. Give it its own declaration (`scope`, `risk`) and route it through the same middleware.

D4 was written from a code read of the four registration paths and did not check whether Path 3 had
callers. It does not. So the choice is: delete it, or build the D4 declaration onto a primitive
nothing uses. **Proposed: delete, and amend D4 to say so** — orchestrator→sub-agent delegation
happens through the planner's per-task `agent_type`, which the runner resolves in
`deep/adapters.py::build_worker_from_agent`, and that path is real and busy.

One consequence to handle deliberately: `test_tool_risk_map_is_live.py` derives `call_<agent_name>`
names *because of* this module. With the module gone, that derivation should go too, or it silently
starts admitting names nothing can produce.

### B2/B3 — `adapters/actions/detectors/tasks.py` and `.../projects.py`

Seven detector classes calling `context.invoke_agent('task_agent', …)` / `'project_agent'`.
Detectors register at **import time**, and `detector_cycle.py:61-76` imports six detector
modules — neither of these is among them. A repo-wide grep for `detectors.tasks` /
`detectors import tasks|projects` returns nothing. **They never enter `_DETECTOR_REGISTRY`, so
those seven detectors have never run.**

This is worth a second look before deleting, because "seven detectors that never registered" could
be an unfinished feature rather than dead weight. The evidence says otherwise — nothing schedules
them, nothing tests them, and the detector cycle's import list is explicit rather than
auto-discovered — but it is the one item in A/B where "delete" and "wire up" are both defensible,
and that is Henry's call, not a rubber stamp.

---

## C — four registered tools that arguably should not exist

**This is the real decision.** All four are reachable, all four are declared by the conversion PR,
and none is dead. The argument for removing them is that they are wrong for the product, not that
they are unused.

### C1 — `create_organization` — strongest case

Creates a **new tenant** from chat: a `Workspace` row with `privacy` defaulting to `"public"`, owned
by whichever user the agent is running as.

- It resolved to **`read`** until the conversion PR raised it to `irreversible`.
- It is **not** in the active v12 planner routing table — no rule routes to it, and no example uses
  it. It is reachable only if the model picks it unprompted.
- It is the only tool in the system that cannot honestly claim `Scope.WORKSPACE_BOUND`, because
  tenant *creation* is not a tenant-scoped operation. ADR 0031 D1 on `CROSS_WORKSPACE`: *"Reserved
  for staff/support surfaces; no tool holds it today and adding one is a security review."*
- Tenant creation already has a real, audited home: the workspace API, with membership, billing and
  entitlement wiring that this tool does none of. A `Workspace` created here is a tenant with no
  subscription tier and no membership row.

**Proposed: delete.** An LLM should not be able to mint a tenant. The conversion PR's
`irreversible` tier is the interim, not the answer — a gate on a capability that should not exist is
still a capability that exists.

### C2 — `manage_organization_team` — description does not match behaviour

Described to the model as *"Add or remove organization team members"*. It mutates
`Workspace.followers` — the nonprofit **social graph**, not membership. It takes an arbitrary
`user_id` from the model and performs no membership check on the subject.

The active v12 prompt routes *"inviting or removing workspace members"* to `workspace_agent`, so the
prompt promises membership management this tool does not deliver. Whichever way this is resolved,
the mismatch must be: real membership management belongs in `membership`, which has the invite
flow, the role policy and the audit trail.

**Proposed: delete, and let the prompt's membership clause resolve to the real surface.**
Alternative if Henry wants the capability from chat: keep it, rename it to what it does
(`manage_organization_followers`), and fix the routing bullet. Deleting is cleaner; renaming is a
`tool_whitelist` data migration under ADR 0031 D8.

### C3 — `get_organization_followers` — the same graph, and it has already leaked

Reads `Workspace.followers`. Until #439 it resolved a workspace **by name across every row**, so it
returned another tenant's follower **email addresses**. That specific bug is fixed; the surface it
lived on is a nonprofit social graph that a SOC product has no read for.

**Proposed: delete.** If followers stay in the data model, they do not need a chat-reachable read.

### C4 — `manage_project_budget` — the last money surface in the tool layer

Writes `Project.budget` / `Project.spent_amount` and renders `$` amounts to the model. The
`budgeting` bounded context was **stripped** when this fork was created; this is a survivor pointed
at the two money columns that stayed behind on `Project`.

`.claude/rules/no-shortcuts.md` and CLAUDE.md both treat the payment path as load-bearing and
handled with care. A chat tool that edits money fields, currently gated as a `read` (the conversion
raises it to `reversible_write`), is not that care.

**Proposed: delete.** Weakest of the four — it is at least internally consistent, and `Project` does
still carry the columns. If Henry wants project budgets in the product, this deserves to be rebuilt
against a real money surface rather than kept as fork residue.

### If all four go

| agent | tools now | after C |
|---|--:|--:|
| `workspace_agent` | 12 | **9** |
| `project_agent` | 15 | **14** |
| `task_agent` | 22 | 22 |
| `user_agent` | 4 | 4 |

`workspace_agent` drops under D9's ~10-15 band. `project_agent` reaches its top edge. `task_agent`
does not move, which is D.

---

## D — `task_agent` at 25 tools. Named, not proposed.

ADR 0031 D9 records tool-selection accuracy degrading past ~10-15 tools and notes `task_agent` (25)
and `project_agent` (18) sit above the band. Nothing in C fixes `task_agent`.

**Deleting tools is the wrong instrument here**, for a reason the evidence makes concrete: five of
`task_agent`'s tools are the *only* CRUD code with production traffic (874 recorded calls), and they
get it through `TriageAgent`, which re-exports them under its own names. The task layer is not
unwanted — it is wanted by a different agent, under different names, with different risk tiers
(`TriageAgent.assign_task` declares `reversible_write`; `TaskAgent.assign_task` declared nothing).

So the honest fix is **decomposition plus de-duplication**, which is a design change and belongs in
its own ADR revision, not a deletion PR:

1. The five shared functions get **one** definition with **one** name and **one** tier, consumed by
   both agents. Today `list_workspace_tasks` / `list_open_findings` and `create_task` /
   `record_finding` are the same function twice, which is exactly what
   `.claude/rules/dry-reuse.md` §4 forbids.
2. What remains of `task_agent` splits by verb — reads vs. writes vs. the three timer tools — or
   the timer tools move to whichever surface owns the Kanban play button, which is where their use
   cases already live.

**Proposed: no action in this PR. Record D, decide it with the D9 revisit.**

---

## What deleting anything costs — the checklist

Every item in A, B and C must be landed with these, or it breaks the build or the product. This is
the §5 hidden-dependency list from the evidence, reduced to a to-do.

| # | Applies to | What must change in the same commit |
|---|---|---|
| 1 | **C, any workspace_agent tool** | Nothing — but if `workspace_agent` itself were ever removed, `controller.py:2584`, `agent_chat_request.py:24`, `agent_chat_command.py:32` and `agent_chat_use_case.py:447` all default to it. **The agent stays. Only tools are proposed for removal.** |
| 2 | **C1, C2, C3** | The v12 planner routing bullet at `planner.system.yaml:2593` names `workspace_agent`'s surface including "inviting or removing workspace members" and "followers". A new prompt version, not an edit in place — versions are immutable and `test_prompt_hygiene.py` reads the live one. |
| 3 | **A (`generate_organization_report`)** | Nothing in the active prompt. Archived versions mention it and must stay untouched — they are the eval baseline. |
| 4 | **A, C** | `KNOWN_BLANKET_STRING_HANDLERS` in `tests/architecture/test_tool_blanket_exception.py` — `test_the_known_list_has_no_stale_entries` fails if an entry stops matching. The list may only shrink. |
| 5 | **C** | `CANONICAL_TOOLS` in `components/agents/tests/_helpers/agent_capability_inventory.py` — an exact-match set, also parametrized by `test_tool_smoke_runtime.py`. |
| 6 | **C** | `ROUTING_EXPECTATIONS` in the same helper, if a removed tool is the reason a phrase routes where it does. |
| 7 | **C** | `test_tool_tenancy_binding.py` pins cross-tenant refusal per workspace tool; removing a tool removes its case. |
| 8 | **C** | `components/agents/tests/prompt_eval/datasets/planner_soc_v1.json` names `get_organization_info` / `get_organization_analytics` (not the four proposed) — check before assuming clear. It is **orphaned** (no runner loads it), which is its own small cleanup. |
| 9 | **B1** | `test_tool_risk_map_is_live.py:116-118` derives `call_<agent_name>` names from the module being deleted. |
| 10 | **C, and any tool rename** | `Agent.config.custom_profile.tool_whitelist` holds tool names as **DB-resident strings**. Null in all 10 rows on the local cluster; unknowable for a deployed customer. ADR 0031 D8: names are permanent, a rename is a data migration. A **deletion** is safe (an unmatched whitelist entry filters nothing); a **rename** is not. |
| 11 | **Any agent deletion (not proposed)** | `ai_agenttype.class_path` holds importable dotted paths in the database and `sync_agent_types_from_registry` upserts without pruning. A deleted class leaves a row whose `class_path` no longer imports. Also `test_agent_defaults_contract.py:103-115` asserts every `DEFAULT_AGENT_TYPES` `class_path` imports. |
| 12 | **Everything** | `discover_agents` **swallows `ImportError` and `SyntaxError`**. A broken agent module does not fail boot — it silently vanishes from `AgentRegistry`, and the planner's catalog is built from that registry, so the agent silently stops being routable. This bit the conversion PR during development: two agents disappeared and every test still passed except the one that counted them. Any deletion touching these modules must verify the registry count afterwards, not just that the suite is green. |

Item 12 is the one to internalise. It is not specific to this proposal — it is a property of the
agent layer that makes *every* change to it quieter than it should be, and it deserves its own fix
(fail loudly on a discovery error) regardless of what happens to the CRUD fleet.

---

## Recommendation

1. **Do A now** — 5 unregistered functions, zero callers, rubber stamp.
2. **Do B1 now** and amend ADR 0031 D4. **Look at B2/B3 once** before deleting: seven never-registered
   detectors is either dead weight or an unfinished feature, and the two readings deserve one
   deliberate glance.
3. **Decide C.** The recommendation is delete all four, with C1 (`create_organization`) as the one
   that should go regardless of the others. If only one thing on this page is approved, make it C1.
4. **Defer D** to the D9 revisit, as decomposition rather than deletion.
5. **Fix item 12** on its own merits, whatever is decided above.

Nothing proceeds without Henry's word.
