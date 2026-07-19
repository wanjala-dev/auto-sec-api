---
name: workflow
description: |
  Use when working on the Workflow / Automation surface — the nonprofit-automation product (triggers → conditions/branches → actions like Send Email, Add Tag, Add To-Do, Wait/Delay, Run AI agent) that is our answer to Keela Automation / Mailchimp Customer Journeys. Covers the `components/workflow/` bounded context end to end: the outbox→Celery execution engine, the graph/node/edge model, autonomous condition + wait-until branching, trigger bindings + the trigger catalog, enrollment→run wiring, the action executors, the published-version model, the feature-flag gating, AND the frontend builder (canvas, list, enrollment monitor) in literacyseed. Loads the current state, the known gaps, the constitutional rules that keep the engine correct, and the GTM roadmap so contributors don't reinvent dispatcher patterns, ship a UI on a non-autonomous engine, or backslide into silent action failures. Invoke BEFORE authoring a node type, trigger, or builder screen; also invoke `/architecture` before layer-crossing changes, `/celery-tasks` before touching the run tasks, `/frontend-reuse` before any builder UI, and `/writing` before touching the email/message node.
---

# Workflow / Automation

**Mental model.** A workflow is a **directed graph** (`nodes` + `edges`, stored as JSON) that a **contact or group walks top→bottom**. A **trigger** (the single `start` node, bound to a domain event via `WorkflowBinding`) is the only way in. The engine advances one node at a time as a **Celery chain**, persisting per-node state with row locks for idempotency. Actions (send email, tag, to-do, AI) are the leaves; conditions/waits branch the path. This is the nonprofit-automation product — **automation + transparency are the platform's bread and butter**, so this feature must be autonomous, robust, and sellable.

> **Read `docs/plans/WORKFLOW_GTM_OVERHAUL_2026-06-24.md` first** — it is the live GTM roadmap, Keela-parity gap matrix, and phase status. This skill is the durable engineering playbook; that doc is the where-are-we tracker. Keep both current.

The reference bar is **Keela Automation** (see the overhaul doc §1 for the full webinar teardown): single starting point + audience filters → auto-resolving checkpoints (wait-until-open, wait-until-transaction, split-by-filter) → actions (email/tag/to-do/field) → exit; plus enrollment management, a live "who's where" monitor, and per-email analytics.

---

## 1. Where everything lives

- **Bounded context:** `components/workflow/` (canonical Explicit-Architecture layout).
- **ORM models:** `infrastructure/persistence/workspaces/workflows/models.py` (Django app `workspaces.workflows`):
  `WorkflowTemplate`, `Workflow`, `WorkflowVersion`, `WorkflowBinding`, `WorkflowEnrollment`, `WorkflowRun`, `WorkflowRunIdempotency`, `WorkflowStepState`, `WorkflowStepEvent`, `WorkflowEvent` (the outbox).
- **Engine:** `components/workflow/infrastructure/tasks/workflow_tasks.py` (the Celery chain) + `infrastructure/adapters/dispatcher.py` (outbox→bindings→runs) + `infrastructure/adapters/node_actions.py` (action executors).
- **Catalog/validation:** `domain/constants.py` (`NODE_TYPES`, `TRIGGER_CATALOG`, statuses) + `domain/validators.py` (`validate_graph`).
- **API:** `api/controller.py` + `api/urls.py` (all gated by `feature.workflows_ui`). **MCP names:** `workspaces_workflows_workflows_*`, `..._workflow_templates_*`, `..._workflow_bindings_*`, `..._workflow_runs_*`, `..._workflow_triggers_*`, `..._enroll/enrollments/unenroll`, `..._runs_steps_complete/input`.
- **Seeds:** `cli/management/commands/seed_workflow_templates.py` (11 system templates).
- **Frontend (literacyseed):** builder canvas `src/components/Workflow/WorkflowCanvas.js`; the screen `src/features/team/presentation/components/DirectoriesLanding.tsx` (`workflowView`); ops layer `src/features/workflow/presentation/useWorkflowOperationsPresentation.ts` (all 25 API ops wired); API client `src/infrastructure/workflow/workflowApi.ts`; routes `/settings/automations` + `/teams/directories/workflows`; action catalog `src/features/team/presentation/models/directoriesWorkflowModel.tsx`.
- **Design docs:** `docs/plans/WORKFLOW_GTM_OVERHAUL_2026-06-24.md` (roadmap), `docs/plans/WORKFLOWS_IMPLEMENTATION.md` (original spec), `docs/plans/GTM_SCOPE_FREEZE_CHECKLIST.md`.

---

## 2. The execution model (how a run actually runs)

1. A feature context calls **`emit_workflow_event(...)`** (`dispatcher.py`) → writes a `WorkflowEvent` outbox row → `transaction.on_commit` enqueues `workflow_event_process`.
2. **`workflow_event_process`** → `dispatch_event` finds matching **active `WorkflowBinding`s** for `(source_type, trigger_type, source_id)`, creates one `WorkflowRun` per binding (idempotent via `WorkflowRunIdempotency`), enqueues `workflow_run_start`.
3. **`workflow_run_start`** finds the single `start` node, sets the run RUNNING, enqueues `workflow_run_step` for the start node.
4. **`workflow_run_step`** (the core executor) gets/creates a `WorkflowStepState` under `select_for_update` on the **tenant-routed DB** (`router.db_for_write` — a bare `atomic()` only covers `default` and `select_for_update` would fail), runs the node by type, then **self-chains** to the next node.
5. **`workflow_run_complete`** finalises.

**Node types** (`NODE_TYPES`): `start, end, message, data_request, decision, task, ai, assign, wait, webhook, publish_event`.
**Run statuses:** `queued, running, paused, completed, failed, canceled`. **Step states:** `pending, running, waiting, waiting_input, completed, failed`.

**What works well (don't break):** the outbox pattern, dispatch-after-commit, per-node idempotency with row locks (`workflow_tasks.py:133`), real `wait` delay via `apply_async(countdown=...)`, published-version snapshots, idempotent run creation.

---

## 3. Constitutional rules (the engine correctness invariants)

1. **The engine must be AUTONOMOUS.** A `condition`/`wait_until` node selects its branch **server-side** with no human in the loop. The legacy `decision` node *pauses the run for a manual API call* — that is the single biggest gap and must not be the branching mechanism for shipped automations. Only `data_request` (genuine human input) may pause. **Never wire a builder UI to a manually-advanced engine** — that produces automations that silently stall (a bandaid we'd rip out).
2. **Fail loudly.** Action executors must **raise** on real failure so `workflow_run_step` fails the run and logs with `run_id`/`node_id`. A returned `{"status":"failed"}` dict that the engine logs as `completed` is a silent-failure bug — never reintroduce it (the engine also treats a returned failed-dict as a failure, as a backstop). Per `.claude/rules/logging.md` + CLAUDE.md "fail loudly".
3. **Enrollment must connect to runs.** Creating a `WorkflowEnrollment` without starting/anchoring a `WorkflowRun` is dead state. Manual enrollment = skip the trigger, start at the `start` node.
4. **Triggers are a contract.** A trigger is only usable if (a) its id is in `TRIGGER_CATALOG` *and* (b) some context actually calls `emit_workflow_event(trigger_type=...)`. The binding serializer validates against the catalog. Keep both halves in sync: every catalogued trigger must have an emitter (else a binding can be created that never fires), and every emitter's trigger must be catalogued (else the binding is rejected and the event fires into the void). When a trigger has no real contact target, or its only emit point would loop (e.g. `contact_tagged` — its sole writer is the `add_tag` executor, so emitting it would re-trigger itself), **remove it from the catalog rather than emit a wrong or looping event.** (As of the trigger-completeness slice: `form_completed`, `email_sent`, `contact_updated`, `task_assigned`, `document_uploaded`, `document_applied` are all wired; `contact_tagged` was removed for the loop reason above — re-add it the day a manual tagging surface exists.)
5. **Idempotency is sacred.** Keep the `select_for_update` get-or-create on `WorkflowStepState` and the `completed`-skip. Pass IDs not objects into tasks. Dispatch after commit. (See `/celery-tasks`.)
6. **Tenant routing.** Always `router.db_for_write(Model)` for the atomic alias when locking workflow rows; never assume `default`.
7. **Explicit Architecture.** Condition evaluation + run advancement belong in an `application` use case (`AdvanceRunUseCase`) + a `domain` predicate evaluator (`WorkflowGraph`/`NodeSpec`), so they're unit-testable without Celery/DB. The Celery task is a thin adapter. Side-effects (tag/field/email/notify) go through ports or existing cross-context facades/shared-kernel events — **no cross-context infra imports**.
8. **Validate what you run.** `validate_graph` must accept exactly what the engine executes and what the seeded templates ship (Phase 1 unified this — it accepts `label` or `title` and validates `condition`/`wait_until`/branch nodes). It runs **at publish, not on draft save**: `WorkflowSerializer` only structurally checks drafts, and `WorkflowService.publish_workflow` runs full `validate_graph` — so a workflow can only go live once complete.
9. **Guard the webhook node.** SSRF allow-list / internal-IP block before any customer can point a node at an arbitrary URL.
10. **Test the engine.** Any engine change ships with an integration test that builds a graph and asserts it advances, waits, branches **both ways autonomously**, executes the action, and fails loudly. The run engine currently has **zero** direct tests — every PR should shrink that hole.

---

## 4. Action executors — status (the leaves of the graph)

| Node | State | Note |
|---|---|---|
| `task` | ✅ real | `ProjectService().create_task(...)` |
| `ai` | ✅ real | `AgentService().execute_agent(...)` — **our differentiator** |
| `message` | ⚠️ partial | email via `NotificationService`; **ignores `template_id`, no email builder, no SMS** → integrate `content` rendering (`/writing`) |
| `webhook` | ⚠️ real but unguarded | sync `requests` to user URL — **SSRF risk** |
| `assign` | ❌ stub | fetches membership, persists nothing |
| `publish_event` | ⚠️ single-purpose | only `task_accepted_from_board` |
| `add_tag` / `remove_tag` | ❌ missing | **Keela table-stakes — build it** |
| `update_field` | ❌ missing | build it |
| `condition` / `wait_until` | ❌ missing | **the autonomous-branching keystone — build it** |

---

## 5. Frontend builder — status

A genuinely good **hand-rolled node canvas** (pan/zoom/minimap, topological layout, bezier branch edges, leaf "+" insert) and a **100%-complete API client + ops layer**. But the UI only calls 3 GETs + 1 POST. **The blockers to a sellable product are wiring + missing screens, not greenfield:**
- "Start workflow" mutates **local React state only** — wire to `createWorkflow` + `publishWorkflow` + `enroll`/`createWorkflowRuns`.
- Action catalog is **Stripe-demo placeholders** ("Retrieve a balance") — replace with the nonprofit set.
- **No workflow list table, no enrollment/run monitor, no analytics** — build them (backend already supports them).
- `condition` branches have **no predicate editor** — build the field/op/value (All/Any) UI (reuse the filter components).
- `wait`/`task`/`assign`/`webhook` nodes have **no config forms**.
- Use the shared component library (`/frontend-reuse`) — DRY is a hard rule.

---

## 6. Feature gating + GTM

- `feature.workflows_ui` gates **all** API routes + the sidebar "Automations" item + the TeamDashboard tab. **The engine/dispatcher are NOT gated** — internal automations (e.g. the Agents-as-Teammates `task_moved_column` → `TaskAcceptedFromBoard` flow) run regardless.
- Currently **OFF in prod** (`seed_feature_flags.py` `PROD_DISABLED_FLAGS`) and listed as a frozen non-ICP surface in `.claude/rules/gtm-scope-freeze.md`.
- **Strategic reclassification (Henry, 2026-06-24): workflows become a headline ICP selling feature.** Roadmap: keep the flag as the rollout lever, enable per paying workspace (like `bank_feed_plaid`), move it from "frozen" to "core ICP, GA-bound" in the freeze rule + checklist at GA. See the overhaul doc §6.

---

## 7. Per-PR checklist
1. Engine change? → integration test that advances a graph + branches autonomously both ways.
2. New node type? → add to `NODE_TYPES`, executor (raises on failure), `validate_graph` support, a config form in the builder, and the nonprofit action catalog.
3. New trigger? → add to `TRIGGER_CATALOG` **and** wire the `emit_workflow_event` call; test the binding can be created and fires a run.
4. Touched run tasks? → `/celery-tasks` (IDs not objects, after-commit, idempotent), tenant-routed atomic.
5. List/repository? → `select_related` what the serializer reads, paginate.
6. Email/message node? → `/writing` (reuse content rendering, don't reinvent templates).
7. UI? → `/frontend-reuse`; wire real API ops, not local state.
8. Run the workflow tests + `tests/architecture` + `makemigrations --check`; respect the EC2 gate before deploy.
