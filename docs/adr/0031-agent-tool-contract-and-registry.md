# ADR 0031 — The agent tool contract: one declaration, one registration path, cross-cutting concerns in middleware

Status: **Proposed (2026-08-20) — design only.** No tool is migrated by this ADR. Build is deferred
until Henry's explicit go, per decision, and stays behind the standing "harden the core loops for
Tom's real use" priority.

Evidence base: [`docs/architecture/AGENT_TOOL_INVENTORY_2026-08-20.md`](../architecture/AGENT_TOOL_INVENTORY_2026-08-20.md)
— every claim below is cited there with a `file:line`.

Relates to: **ADR 0003** (agent decorator framework — this extends `@tool`, it does not replace it),
**ADR 0004** (Finding SSOT hub-and-spoke — the `handles` declaration in D6 is the tool-layer half of
`ROUTABLE_SOURCE_TYPES`), **ADR 0023** (agent runtime accountability — the customer-facing product
this ADR's declaration would supply data for), **ADR 0029** (two-tier tenancy — the reason D1 is the
first decision and not the fifth).

---

## Context

Henry asked whether agent tools can be standardized so common themes are reused, DRY holds, and
adding a new tool to any agent becomes easy.

The audit says: **yes, and less is needed than the question implies.** There is no missing framework
to build. The pieces are mostly present and several are good — a shared board-write choreography, a
risk/approval ladder, a distinct autonomous principal, a kill switch, a shared-kernel triage
contract. What is absent is one thing, and everything else follows from it:

> **The framework has no way to know what a tool is.** Every cross-cutting property — how it binds
> tenancy, who may call it, whether it writes provenance, what its failure looks like, which finding
> kinds it handles — lives in the tool author's memory rather than in a declaration the registry can
> check.

The consequence is the same shape at every concern: handled once where somebody built a helper,
re-implemented or forgotten everywhere else.

- Tenancy: ~60 inline re-implementations; three safe helpers and one — `_resolve_org_id`,
  used by 10 tools — that **prefers the caller's workspace id** over the agent's.
- Authorization: `@requires_role` exists and is used on **1 of 101** tools.
- Risk tiers: a good ladder, **46 of 101** tools declare one, and **8 of the 10** entries in the
  fallback name-map are dead nonprofit fork-drift.
- Provenance: one excellent shared choreography reaching exactly **5** tools.
- Failure: **50 of 83** tool bodies swallow everything into a flat string; three separate
  failure-signalling mechanisms exist and none is connected to the other two.
- Rubric grading: **3 of 14** agent types, and off in production.
- Observability: per-tool cost is never recorded; per-tool latency is measured and then discarded.

And there are **four** ways a capability reaches an agent, not one — which is precisely why "add a
tool once, use it anywhere" does not hold today.

### The fact that makes this cheap

`base.py:1151-1156` already calls `create_agent(model=…, tools=…, system_prompt=…,
middleware=self._build_agent_middleware())`, and `_build_agent_middleware` (`base.py:1168-1207`)
returns an **empty list** unless the rubric flag is on.

There is a wired, empty middleware chain in front of every tool call on every agent. Verified live
against the pinned image (`langchain==1.3.14`, `deepagents==0.6.12`): `wrap_tool_call`,
`ToolCallRequest` (carrying `tool_call`, `tool`, `state`, `runtime`), `ToolRuntime` and
`RubricMiddleware` all import cleanly today.

So the proposal is **not a new framework**. It is: give a tool a declaration, and move the
cross-cutting concerns from per-tool memory into the middleware slot that is already there.

---

## Decisions

### D1 — A tool declares how it binds tenancy, and the model can never supply it

`@tool(..., scope=Scope.WORKSPACE_BOUND)` is **mandatory**. Three values:

| value | meaning |
|---|---|
| `WORKSPACE_BOUND` | every query filters `workspace_id = <the run's bound workspace>`. The default and the overwhelming majority. |
| `WORKSPACE_FREE` | genuinely tenant-independent (IOC enrichment against external threat intel, a pure text grader). Must justify itself in the docstring. |
| `CROSS_WORKSPACE` | reads beyond one tenant. **Reserved for staff/support surfaces; no tool holds it today and adding one is a security review.** |

Enforcement is two-sided:

1. **The workspace id reaches the tool through `ToolRuntime`, not through its args schema.** LangChain
   1.x excludes a `runtime: ToolRuntime[AgentToolContext]` parameter from the schema the model sees.
   A tenant id the model cannot write is a tenant id the model cannot cross. This is the
   by-construction half.
2. **A fitness function forbids a tool body from reading a workspace/organization key out of its
   payload** (F3, §Enforcement).

*Rationale.* `_resolve_org_id` is not a careless line — it is a considered helper with a thoughtful
docstring citing a real 2026-05-08 incident, written by someone solving a genuine problem (the LLM
omitting the id). It is *still* a cross-tenant escape hatch advertised to the model in nine tool
descriptions. That is the argument for construction over discipline: the discipline was present and
the outcome was wrong anyway. Under D1 the problem `_resolve_org_id` solves does not exist, because
the model was never asked for the id.

*Alternative rejected — "validate that the supplied id equals `agent.workspace_id`."* Cheaper, and it
would close today's hole. Rejected because it leaves the parameter in the schema, which means it
stays in the tool description, which means the next tool copies the pattern and the next reviewer has
to notice the missing check. It converts a boundary into a lint.

### D2 — A tool declares its failure semantics, and the framework classifies the outcome

`ToolResult` becomes the **required** return type for every tool, and it grows a reason:

```python
ToolResult(ok=False, error="...", failure=Failure.UPSTREAM_UNAVAILABLE, retriable=True)
```

`Failure` values: `NOT_FOUND`, `INVALID_INPUT`, `DENIED`, `UPSTREAM_UNAVAILABLE`, `CONFLICT`,
`INTERNAL`. A blanket `except Exception` in a tool body becomes a lint failure; genuinely unexpected
exceptions propagate and are classified once, in middleware.

The middleware then does what the three disconnected mechanisms cannot do separately:

- stamps `DeepRunLog.status` on the `tool_observation` row — the field already exists
  (`gateways/deep/logging.py:15`) and is simply never passed (`base.py:2253-2262`);
- marks the run's outcome, so `execute()` stops setting `success=True` unconditionally
  (`base.py:1872`);
- renders the model-facing string *from* the structured result, so the LLM still sees prose while
  the system keeps the bit.

*Rationale.* This is the dominant defect class and it is structural, not a set of bugs. Today
`ToolResult.ok` is flattened to a string by `_serialize_tool_result` (`base.py:513`) before anything
can read it; the DeepRunLog `status` column is never written; and the honesty guard inspects the
LLM's own narration rather than tool output. The worked example in the inventory §3.4 — an
LLM-provider outage producing "Handled CVE-xxxx: reviewed; no confident fix" across every finding,
every card stamped triaged, no PRs opened, and `status="completed"` at all four layers — is not
hypothetical; the six advisor services that produce it are cited.

*Note the discipline this must respect.* LangChain's own guidance on `wrap_tool_call` error handling
is explicit that not everything should be caught: handle runtime input errors, let implementation
bugs bubble. `Failure.INTERNAL` must stay loud, and D2 is a licence to *classify* failures, never to
swallow more of them.

### D3 — Cross-cutting concerns move from promotion-time wrappers into `wrap_tool_call` middleware

One `ToolGovernanceMiddleware` returned from `_build_agent_middleware`, composing, in order:

1. **capability + risk gate** — today's `_risk_gated` (`base.py:467-497`), unchanged in policy
2. **authorization** — today's `requires_role`, read off the declaration rather than a decorator
3. **tenant assertion** — reject a call whose args carry a workspace key (belt to D1's braces)
4. **provenance** (D5) and **failure classification** (D2)
5. **observability** — per-tool latency, outcome, and cost delta on the `tool_observation` row

*Rationale.* The current wrappers are applied inside a `for` loop over `_decorated_tools`
(`base.py:844`), so they only reach tools that entered that loop. The proof is already in the tree:
`retrieve_workspace_context` — the one tool **every** agent has — is constructed directly at
`base.py:1022` and receives neither `_risk_gated` nor `_serialize_tool_result`. It is read-only, so
there is no live exposure; the *structure* is the defect, and it would silently repeat for the next
tool built that way. Middleware wraps the `ToolNode`, so it catches every tool regardless of how it
was registered.

*Alternative rejected — keep the wrappers and also wrap the RAG tool.* That is the bandaid: it fixes
the one instance and leaves the seam that produced it.

### D4 — One registration path; the other three are named and bounded

**Path 1, `@tool` + the promotion loop, is the only way a tool reaches an agent.** For the others:

- **Path 2 (universal RAG tool)** → convert to a `@tool` method on a `_RetrievalMixin`. Removes the
  bypass entirely. This is the reference conversion (§Migration).
- **Path 3 (`agent_bridge.create_agent_tool`, `tools/agent_bridge.py:92`)** → keep, but it is a
  **delegation** primitive, not a tool. Give it its own declaration (`scope`, `risk`) and route it
  through the same middleware, so an orchestrator handing work to a sub-agent is governed like any
  other call.
- **Path 4 (the MCP JSON-RPC server, `infrastructure/api/mcp/views.py`)** → **explicitly not an agent
  tool surface.** It exposes DRF operations derived from the OpenAPI schema and executes by proxying
  HTTP back into the app. It should never grow agent-tool semantics, and the agent layer should never
  try to unify with it.

  Two facts belong in a ticket, not in this ADR's scope but named here so they are not lost:
  its `_is_authorized` checks only that an `Authorization` header is **non-empty**
  (`views.py:91-95`), and the route is mounted unconditionally (`api/urls.py:40`). Because
  `POST /ai/chat/agent-chat/` is itself a DRF operation, the deep-agent pipeline is reachable through
  it. Separately, its money denylist (`views.py:534-556`) is a **second, non-communicating copy** of
  the `ToolRisk` policy, keyed on URL substrings instead of tool names, and the two demonstrably
  disagree.

*Open question for Henry — OQ1.* Whether the MCP surface should be gated behind a setting and put
behind real authentication is a product/security decision above this ADR. Flagged, not decided.

### D5 — Provenance is declared, and the shared choreography stays the implementation

`@tool(..., provenance=Provenance.BOARD_CARD | NONE | AUDIT_ONLY)`. `BOARD_CARD` tools are asserted
by fitness function to route through `_finding_processing.process_pending_finding` — the pattern is
already correct and already DRY across all five board-acting tools; this makes it checkable rather
than remembered.

*Rationale.* The standing rule is "every AI action posts to the board as provenance". Five tools do.
Ninety-six do not, and several of those mutate state (`create_task`, `update_organization`,
`open_draft_pr`, `generate_pentest_report`, `draft_workflow`).

*Open question — OQ3.* Does the provenance rule bind **every** state-changing tool, or only
board-acting specialists? This is a product decision about how noisy the board should be, and it is
Henry's. D5 supplies the declaration either way; the fitness function's strictness follows his answer.

### D6 — A specialist declares which finding kinds it handles, and startup asserts the routing closes

`@tool(..., handles=("ai.code_security",))`. A fitness function then asserts:

> every entry in `ROUTABLE_SOURCE_TYPES` is declared by at least one tool on the agent that
> `_SOURCE_BOARD` stamps for that source.

**This is currently green — five for five** (inventory §3.10). Report that plainly: routing is *not*
broken today. It is held by hand, `.claude/rules/dry-reuse.md:36` already records that it has bitten
before ("routable without a tool is a silent no-op"), and one `_SOURCE_BOARD` entry added without its
tool re-breaks it invisibly — because the dispatch goal is generic ("use your tools to list them and
process each one", `finding_dispatch_service.py:89-96`) and a specialist with no matching tool
produces nothing while the run still reports completed.

This is the same argument `tests/architecture/test_sole_session_minter.py` makes in its own docstring
— three call sites found by hand, one incident at a time, before someone wrote the rule. D6 is that
rule for tool routing.

### D7 — Per-agent access is a policy over declarations, not hand-wiring

Today a tool is available to an agent iff the method is defined on that class. The only declarative
controls are *subtractive* name filters (`base.py:1323-1409`) which cannot grant anything.

Under D7, `wrap_model_call` middleware filters `request.tools` before the model sees them, using the
declared `capability` + the caller's resolved role + entitlement. This is the framework-native
dynamic-tool-selection pattern. It replaces the ad-hoc `_apply_tool_policy` and gives a real answer to
"which agents get which tools" without editing 14 classes.

*Explicitly not decided here.* Which capabilities exist, which agents hold them, and which are paid
tier are **product decisions — OQ2**. D7 supplies the mechanism only. Note today's shape is one
capability, `{"open_draft_pr"}` (`agent_capabilities.py:24`), enforced downstream in a use case rather
than at the tool, and always read off the workspace's `triage_agent` row even when
`code_security_agent` is the caller.

### D8 — Evolution: names stay byte-stable, schemas grow additively, tiers may only rise

- **Tool names are permanent.** `Agent.config.custom_profile.tool_whitelist` references them as
  strings. A rename is a data migration. Unchanged from ADR 0003 §5.2 — restated because D7 makes
  names load-bearing in a second place.
- **Schema changes are additive.** New args are optional with a default. A required-arg change is a
  new tool plus `superseded_by=` on the old one, which keeps working until removed. A run already in
  flight never sees a shape it cannot satisfy.
- **A risk tier may be raised at any time; lowering one is a security review.**
- **The declaration carries `since=` and optional `superseded_by=`**, so the governance read
  (`ai_governance_agent`) can report tool inventory drift over time — the same reason specialists
  version their system prompts via `<agent_slug>.system` in the `PromptRegistry`.

*Deliberately excluded:* semantic versioning of tool schemas. The additive rule plus
`superseded_by` covers the real cases without a version negotiation the agents would have to
understand.

### D9 — Do not build tool-RAG

Independent 2025-26 work reports tool-selection accuracy degrading past ~10–15 tools, with two
standard answers: retrieval over a tool registry, or decomposition into specialists. **autosec has
already taken the decomposition answer** — 14 specialists at 4–25 effective tools each, rather than
one agent with 102.

Two agents sit above the band: `task_agent` (25) and `project_agent` (18). Both are inherited fork
CRUD, not security surface. Record the ceiling, watch those two, and revisit only if a *security*
specialist crosses 15. Adding a retrieval layer now would be building for a problem the architecture
already solved.

---

## Enforcement — fitness functions

Each lands beside the code it guards, in `tests/architecture/`, following the shape of
`test_sole_session_minter.py` and `test_feature_flag_not_sole_permission.py` (explicit allowlist,
each entry carrying a written justification; never baseline a real violation).

| id | assertion |
|---|---|
| **F1** | Every `@tool` declares `scope`, `risk`, `provenance`, `failure_mode`. Missing → fail. *This is the one that makes the bug class disappear rather than get re-found.* |
| **F2** | Every routable `source_type` has a specialist declaring `handles=` for it (D6). |
| **F3** | No tool body reads `workspace_id` / `organization_id` from its payload (D1). |
| **F4** | No blanket `except Exception` in a tool body returning a bare string (D2). |
| **F5** | Every promoted tool passes through `ToolGovernanceMiddleware` — i.e. no `StructuredTool.from_function` outside the promotion loop (D3/D4). |
| **F6** | `_TOOL_RISK` contains no key that no agent declares — kills the 8 dead nonprofit entries and stops the map rotting again. |

F6 is deliberately trivial and lands first: it is a five-line test that deletes a class of confusion
for free.

---

## Before / after — adding a new tool

**Today.** Add a tool that lists open Vercel posture findings for the posture agent:

| # | file | thing to remember |
|---|---|---|
| 1 | `tools/posture_agent.py` | write the body; remember `workspace_id=agent.workspace_id` on every queryset |
| 2 | `agents/posture_agent.py` | `@tool(name=…, description=…)` — and remember `risk=`, which 54% of tools do not |
| 3 | `application/policies/tool_risk.py` | or add it to `_TOOL_RISK` instead — two places, no rule saying which |
| 4 | — | remember `@requires_role` if sensitive (1 tool in 101 does) |
| 5 | `tools/_finding_processing.py` | route through it if board-acting — or don't, nothing checks |
| 6 | — | decide the error shape; the house style is `except Exception → f"Error …: {exc}"`, which is the defect class |
| 7 | `shared_kernel/domain/triage.py` | if it handles a new finding kind, add to `ROUTABLE_SOURCE_TYPES` — and remember the tool, or it is a silent no-op |
| 8 | `finding_raised_board_handler.py` | `_SOURCE_BOARD` entry with the right `agent_type` |
| 9 | tests | a tool test; no rule about what it must assert |

**~4 files, 9 remembered concerns, 0 enforced.** Nothing fails if you forget any of items 1, 3, 4, 5,
6 or 7 — the tool ships and the gap surfaces later as a QA finding or an incident.

**Under the proposal.**

```python
@tool(
    name="list_open_vercel_findings",
    description="...",
    scope=Scope.WORKSPACE_BOUND,
    risk=ToolRisk.READ,
    provenance=Provenance.NONE,
    handles=("ai.vercel_posture",),
)
def list_open_vercel_findings(self, runtime: ToolRuntime[AgentToolContext], limit: int = 20) -> ToolResult:
    return posture_tools.list_open_vercel_findings(runtime.context.workspace_id, limit)
```

**1 file, 1 declaration, 0 remembered concerns.** Scoping is bound by the runtime and unwritable by
the model; the risk gate, authorization, provenance, failure classification and per-tool telemetry
are applied by middleware; F1 refuses the tool at test time if the declaration is incomplete; F2
refuses the routing change if `handles=` and `ROUTABLE_SOURCE_TYPES` disagree.

That comparison is the test of whether this design delivers what was asked. It does — but note
honestly what it costs: **every future tool must write a declaration it does not write today.** The
trade is four lines of declaration against nine things to remember.

---

## Migration — incremental, reversible, one tool first

No big-bang. The two shapes coexist for as long as it takes.

**Phase 0 (hours).** F6 — delete the 8 dead `_TOOL_RISK` keys and add the test that stops the map
rotting. Independently valuable, zero risk, no dependency on anything below.

**Phase 1 (~1 day). — LANDED 2026-08-20.** Add `ToolSpec` as **optional** metadata on `@tool`
(defaults preserve today's behaviour exactly) and add `ToolGovernanceMiddleware` to
`_build_agent_middleware` in **observe-only** mode: it classifies and records, and enforces nothing.
This alone fixes the observability gaps in §3.9 — per-tool latency, outcome, and
`DeepRunLog.status` — and it produces the data to size the rest. Reversible: remove one line from a
list.

*As shipped.* `components/agents/application/policies/tool_spec.py` holds the declaration
(`Scope`/`Provenance`/`Failure`/`ToolSpec`, every field optional, `UNDECLARED` the shared default);
`.../langchain/middleware/tool_governance.py` holds the middleware. Observations join onto the
**existing** `tool_observation` row rather than emitting a second row — `_reconstruct_intermediate_steps`
now carries `tool_call_id`, which is the join key — so `DeepRunLog.status` is finally written and
`payload["governance"]` carries `outcome`, `latency_ms`, `declared`, and the declaration. The
run-success contradiction is logged as `agent_run_reported_success_with_tool_failures`; the reported
status is deliberately **unchanged** (that is D2, Phase 3).

One thing the ADR did not anticipate: the flattened `ToolResult.ok` bit has to be recovered from the
`"Error: "` prefix `serialize()` renders, because `_serialize_tool_result` destroys it before any
middleware can see it. That is ugly on purpose — it is the measurement that sizes D2, not a fix for it.

**Phase 2 — the reference tool. — LANDED 2026-08-20.** Convert **`retrieve_workspace_context`**
first. It is the right first conversion for four independent reasons: it is the single tool every
agent has, so one conversion proves the seam across the whole fleet; it is the concrete instance of
the D4 bypass, so converting it removes a real structural hole; it is read-only, so a mistake cannot
corrupt anything; and it is *already* the only tool that emits `DeepRunContext` events, so it
exercises the observability path end to end. Ship it with its declaration, prove middleware fires for
it, and stop.

*As shipped.* The body moved onto `WorkspaceRetrievalMixin`, which `BaseAgent` inherits, as a `@tool`
carrying a complete declaration. It now enters the promotion loop like every other tool and picks up
`_risk_gated` + `_serialize_tool_result`, which it never had. Two details worth recording:
`__init_subclass__` skips `BaseAgent` when walking the MRO, so the method has to live on a mixin
rather than on `BaseAgent` itself; and the promotion loop always passes an explicit `args_schema`, so
the schema `from_function` used to *infer* had to be restated exactly — including its title — or the
tool definition the model reads would have changed. Both are pinned by tests.
`_build_workspace_retrieval_tool` survives as the builder for the one path that skips promotion (a
subclass that pre-populated `self.tools`).

**Phase 3 — enforce per concern, not per tool.** Turn on F3 (tenancy) first, because that is where
the live exposure is, with `_resolve_org_id`'s ten call sites as the explicit remediation list.

*F3 landed in WARN mode alongside Phase 2* (`tests/architecture/test_tool_payload_tenancy.py`),
per the mitigation this ADR names against itself below. It printed and warned the **14** outstanding
entries on every run — `_resolve_org_id` + `_extract_identifier`, their eleven call sites, and
`project_agent.check_project_permissions`, which did
`Workspace.objects.get(id=data["workspace_id"])` with no fallback and no comparison to
`agent.workspace_id` at all. It was a **ratchet**, not a mute: a *new* violation failed the build.

**F3 is now in FAIL mode — LANDED 2026-08-20.** All 14 entries are fixed and the allowlist is
deleted. What shipped:

- `_resolve_org_id` → `_bound_workspace_id(agent)`, which takes no payload at all. All ten call
  sites read the run's workspace. `_extract_identifier` is deleted with its one caller rewritten.
- `get_organization_info` no longer resolves a workspace **by name across every row**
  (`workspace_name__iexact` then `__icontains`) — a bug sharper than the preference this phase set
  out to fix, and one the ADR did not name: it rendered another tenant's story, owner username and
  follower list, and answered "does a workspace called X exist" for any X.
  `get_organization_followers` leaked that tenant's follower **email addresses** the same way.
- `get_organization_analytics` started from `Workspace.objects.all()` and narrowed *only if* an id
  resolved, so a run with no bound workspace reported counts aggregated across every tenant. The
  queryset now starts scoped.
- `project_agent.check_project_permissions` binds to the run.
- **Eleven tool descriptions** advertised the parameter — ten `organization_id`, one
  `workspace_id`. The ADR said nine; the real count is eleven, and a twelfth
  (`get_organization_info`) advertised "organization name or ID". All rewritten, and a second
  fitness function keeps them that way: removing the trust without removing the advertisement
  leaves the model still supplying the value.

D1's by-construction half needed one adaptation. "Leave the field out of the args schema" assumes a
typed schema; nearly every tool here is a legacy `input_str` tool promoted with
`LegacyStringToolInput`, whose `extra="allow"` exists precisely so the model can pass arbitrary
kwargs. There is no field to remove. The equivalent construction is to remove the **value**:
`application/policies/tool_tenancy.py` defines the tenancy keys once, and two seams strip them —
`_tenancy_scoped` in the promotion loop (covers direct invocation, which is where tests live) and
`ToolGovernanceMiddleware._strip_tenancy_args` (covers every tool however registered, which is D3
item 3). Stripping rather than refusing, because a refusal is a tool error the model retries with
the same call.

Then
F4 (failure), then F1 (full declaration) once enough tools carry one that the allowlist is short.
Each is one test flipped from warn to fail, and each is independently revertible.

*D2 + F4 landed 2026-08-20 — the failure-semantics half of Phase 3.*

**The outcome now survives serialization, out-of-band.** `_serialize_tool_result` was where
`ToolResult.ok` died; it now returns `(content, artifact)` under LangChain's
`response_format="content_and_artifact"`. `content` is byte-for-byte the string it always was —
`ToolResult.serialize()` is untouched — and the structured outcome rides `ToolMessage.artifact`,
which LangChain documents as *"additional data not sent to the model"* and
`langchain_mcp_adapters` uses for the same purpose. So this is the framework's own out-of-band
slot, not a parallel channel invented here. `convert_to_openai_messages` and
`convert_to_openai_tool` are asserted identical with and without it
(`test_tool_failure_semantics.py::TestTheModelVisibleBytesDidNotMove`).

A contextvar was considered and rejected on evidence: LangGraph's `ToolNode` runs sync tools in a
thread pool under `copy_context().run(...)`, so a value set inside the tool would never reach the
middleware.

**Classification is honest.** `ToolResult` grew `failure` + `retriable`; the reason resolves
call → declaration (`@tool(failure_mode=...)`) → `INTERNAL`, and every observation carries
`expected` — True when the tool *reported* the outcome, False when the framework *inferred* it from
an escaped exception or a rendered prefix. `INTERNAL` stays the loud tier; it is just no longer the
answer for everything. `_risk_gated` refusals now classify as `DENIED` via a `str` subclass
(`_ToolRefusal`), so a blocked call stops counting as a success without moving a single byte the
model reads.

**`execute()` stopped claiming success it cannot know.** `resolve_run_outcome` (application layer,
framework-free) gives three states: no tool failed → `completed`; some failed → `partial`
(`success=True` — the answer is usable and discarding it would be its own dishonesty); tool calls
were made and **all** failed → `failed` (`success=False`, narration preserved as `result`). A turn
with no tool calls is `completed`. All four layers agree: the `tool_observation` row's status +
reason, `AgentExecution.status` (new `partial` choice), the `run_telemetry` row, and the
`worker_completed` row — which read `completed` unconditionally and now carries the worker's own
verdict.

**Two things worth recording that the ADR did not anticipate.**

- Phase 1's `"Error: "` prefix heuristic reads as though it covered the ~49 hand-rolled error
  strings. It never did — every one of them is `f"Error <verb>ing X: {exc}"`, with no colon after
  "Error", so the heuristic only ever matched `ToolResult.serialize()` output. Those failures were
  invisible before D2 and are invisible after it. Converting the bodies is the only fix, which
  raises F4 from hygiene to the actual remediation. Pinned by
  `test_the_prefix_fallback_does_not_reach_the_hand_rolled_house_style`.
- "No outcome" is carried as **no artifact**, never as an asserted success. Attaching a success
  envelope to every bare-string return would have shadowed the fallback and turned "we don't know"
  into "it worked" — the defect class in miniature.

**F4 is on, in ratchet mode** (`tests/architecture/test_tool_blanket_exception.py`): 63 known
blanket-`except`-returning-a-string bodies are named and printed every run; a 64th fails the build.
The distribution is the finding — **50 are the inherited CRUD fleet** (`task_agent` 21,
`project_agent` 19, `workspace_agent` 6, `user_agent` 4), i.e. Phase 4 / OQ4, and **13 are security
surface** (`ai_governance_agent` 6, `posture_agent` 5, `report_agent` 2), which is where conversion
should start.

*Not in scope, and named rather than silently left.* The six advisor services whose
`logger.exception(...); return None` produces the inventory's worked example still return `None`;
D2 supplies the mechanism to report it, and converting them is its own change.

**Phase 4 — the CRUD backlog.** `task_agent` / `project_agent` / `workspace_agent` / `user_agent` are
46 of the 101 tools, carry 0 risk declarations, and are inherited nonprofit-shaped CRUD. Convert them
last, or reconsider whether a SOC product needs 25 task-management tools reachable from chat at all.
**Not decided here — OQ4.**

At every phase both shapes work, nothing is deleted before its replacement is proven, and any phase
can be reverted by flipping one flag or removing one middleware entry.

---

## Consequences

**Good.** One place to look for what a tool is. Six bug classes become test failures instead of QA
findings. Tenancy stops depending on ~60 correct memories. The `wrap_tool_call` seam is
framework-native, so future LangChain middleware (rubric grading on tool calls, retries, emulation
for tests) plugs into a slot that is already there. New pillars get D6's routing assertion for free.

**Costs.** Every future tool writes four lines it does not write today. `ToolSpec` is a new concept
contributors must learn — mitigated because F1 tells them exactly what is missing. The middleware
adds a small per-tool-call overhead. And the migration is genuinely long-tailed: Phase 4 is 46 tools.

**Risk.** The main one is that Phase 1's observe-only mode becomes permanent — the middleware lands,
nothing is ever enforced, and we have added a layer without removing a bug class. The mitigation is
that Phase 3 is one test flip per concern, and F3 should be scheduled with Phase 2 rather than
deferred.

---

## Open questions for Henry

1. **OQ1 — the MCP surface.** Should `/mcp/` be flag-gated and put behind real authentication? It is
   mounted unconditionally, authenticates on header-presence, and reaches
   `POST /ai/chat/agent-chat/`. Security decision, above this ADR.
2. **OQ2 — capabilities.** Which capabilities exist, which agents hold them, which are paid tier.
   Pure product. D7 supplies the mechanism only.
3. **OQ3 — provenance scope.** Does "every AI action posts to the board" bind every state-changing
   tool, or only board-acting specialists? Determines how strict F-provenance is, and how noisy the
   board gets.
4. **OQ4 — the CRUD fleet.** `task_agent` (25 tools) and `project_agent` (18) are inherited
   nonprofit-shaped CRUD, both above the tool-count band in D9. Convert them, trim them, or leave
   them?
5. **OQ5 — sequencing.** This is craft work, not customer work. Phase 0 and Phase 1 are cheap and
   pay for themselves in observability; Phases 3–4 are real effort. Does any of it clear the "does
   this move Tom/Isaac/Sephora forward?" bar right now, or does it wait?

## What could not be verified

- The MCP `sid` claim consequence (§D4) is read from code, not runtime-reproduced. Labelled a
  hypothesis in the inventory.
- The live MCP tool count. `infrastructure/api/schema.py:41` claims ~985, which predates the fork's
  context deletions; the schema could not be generated from the worktree (no venv), and generating it
  on the shared cluster was out of scope for a read-only pass.
- Whether `feature.code_security` / `feature.container_security` are genuinely bypassed via the agent
  tool path. The absence of any flag check in the tool layer is verified; the *consequence* is
  inferred and labelled a hypothesis.
</content>
