# Teams / Boards / Columns — Research + QA Pass (2026-08-16)

**Status: decision-ready report. No product code was changed.** Henry decides the model; this
document maps what exists (with file:line evidence), what the live QA pass found, and the
researched options with tradeoffs.

Scope per Henry's 2026-08-09 direction: flag-gate auto-created default teams + onboarding
team-creation prompt; consistent columns everywhere (the AI board's triage/optimize confusion);
multi-board-per-team research; the "missing" column drag-reorder; QA-robustness of the whole area.

QA environment: local k8s cluster (`autosec` namespace, api healthy), HUD dev server on `:3021`
against `http://autosec.local`, real login `test@autosec.local`, workspace
`cc287133-b53c-43c8-9000-2873f8c8a1e3`. Screenshots in
`/Users/henrywanjala/Desktop/claude-smoke/tbqa-0*.png` (never committed to the repo).
All QA artifacts created during the pass (1 task, 1 column, 1 reorder) were cleaned up and the
board restored to its seeded state (verified by reload, `tbqa-06`).

---

## (a) The model as-built

### Entities (backend)

There is **no Board entity**. A "board" is a *derived* concept with two axes:

| Concept | What it actually is | Evidence |
|---|---|---|
| Team board | The set of `Column` rows with `project IS NULL` for a (team, workspace) | `components/workspace/infrastructure/repositories/column_query_repository.py:46-56` |
| Project board | The set of `Column` rows with `project = <p>` | same file `:37-44` |
| Column | `infrastructure/persistence/project/models.py:149-176` — FK `project` (nullable), `team` (required), `workspace`; `order = IntegerField(default=0)`; `Meta.ordering = ["order"]`; partial-unique `(team, workspace, title) WHERE project IS NULL` | `:150-152, :164-176` |
| Task | `infrastructure/persistence/project/models.py:182-243` — FK `team`, `project` (nullable), `column` (nullable, `SET_NULL`); `order = PositiveIntegerField(default=0)`; `source_type` carries AI provenance (`:229`) | |
| Team | `infrastructure/persistence/team/models.py:14-79` — `kind` enum: `department` / `project_team` / `ai_agents` / `blue_team` / `red_team` (`:41-50`); `is_default` (`:66`); per-team `plan` FK (billing) | |

Lane reads are windowed and eager-loaded (`column_query_repository.py:153-194`); board task order
is `("order", "created_at")` (`:193`).

### Auto-created teams (today, every new workspace)

`ensure_workspace_scaffolding` (`components/workspace/infrastructure/adapters/workspace_utils.py:13-69`):

1. **"General"** — `is_default=True`, `kind=BLUE_TEAM` (`:24-43`; ADR 0007 "defensive by default").
   Title is "Family" for personal workspaces (`components/identity/infrastructure/adapters/workspace_bootstrap.py:119`).
2. **"Red Team"** — seeded but opt-in (`workspace_utils.py:72-94`).
3. **Agents team** (`kind=AI_AGENTS`) via `ensure_agents_team`
   (`components/agents/infrastructure/services/agent_permissions_service.py:118-163`), plus the
   **"AI Findings" project** with 4 columns via `ensure_agents_board`
   (`components/agents/infrastructure/services/agents_board_service.py:55-112`).
4. (Bootstrap-command path only: a "Staff Team", `bootstrap_workspace_setup_use_case.py:62-66`.)

Called at registration/first hydration: `_create_bootstrap_workspace`
(`workspace_bootstrap.py:102-145`, scaffolding at `:133`, agents board at `:136`) and at explicit
workspace create (`create_workspace_use_case.py:68-72`).

### Column vocabularies — FOUR of them coexist

| Board | Columns | Seeded by |
|---|---|---|
| Bootstrap team boards (General, Red Team) | Backlog(1) Todo(2) In Progress(3) Testing(4) Complete(5) Canceled(6) | `DEFAULT_BOARD_COLUMNS`, `workspace_utils.py:262-269`; `ensure_team_board_columns` `:272-317` |
| User-created team boards | the 6 above **plus "Done"(7)** | `team_management_repository.py:63-64` + `_ensure_done_column` `:110-117` |
| Agents "AI Findings" project board | Suggested(0) Under Review(1) Accepted(2) Dismissed(3) | `agents_board_service.py:24-34, :92-110` |
| Agents *team* board | "Triage", "Optimize" — created lazily when a specialist first acts | `_finding_processing.py::ensure_board_column` (`components/agents/infrastructure/adapters/langchain/tools/_finding_processing.py:84-102`); titles at `tools/triage_agent.py:29`, `tools/code_security_agent.py:28`, `tools/optimization_agent.py:28` |

### The AI finding's journey crosses two boards

1. `FindingRaised` → `handle_finding_raised_board`
   (`components/agents/application/handlers/finding_raised_board_handler.py:475-589`) builds the
   card per `_SOURCE_BOARD` (`:406-459`) and persists it into the **"AI Findings" project board's
   Suggested column** (`:526-545`).
2. A specialist (triage / optimization / code-security agent) later processes it and **moves it to
   the project-less team-board "Triage"/"Optimize" column** (`_finding_processing.py:349-355`).
3. The move updates **only** `column` (`update_fields` at `:390-393`) — the task keeps
   `project = "AI Findings"` while sitting in a column that belongs to no project. This is exactly
   the FK inconsistency `MoveTaskToBoardView` was built to prevent for human moves
   (its docstring: "Unlike batch-move (which only touches the `column` FK), this keeps
   `team` / `project` consistent" — `components/project/api/controller.py:713-722`).

### Frontend (HUD)

Single board component `src/components/V2/kanban/HudKanbanBoard.jsx` (both the KANBAN drawer and
the panel overlay render it — `CommandCenterV2Page.jsx:3619, :5454-5458`). Key facts, each verified
in code by the frontend sweep:

- **dnd-kit**: `@dnd-kit/core` ^6.1.0 (installed 6.3.1), `@dnd-kit/sortable` ^8.0.0
  (`package.json:6-7`). One `DndContext` (`HudKanbanBoard.jsx:1133-1139`), pointer sensor with a
  5px activation constraint (`:914-919`), collision = `pointerWithin` → `closestCorners` fallback
  (`:930-934`).
- **Columns ARE sortable**: horizontal `SortableContext` over column ids (`:1144-1147`), lanes call
  `useSortable({ data: { type: 'Column' } })` (`:515-526`), header = drag handle (`:578-586`).
  Drop → `arrayMove` → reindex `order = index` → `POST /project/columns/reorder/`
  (`useKanbanDragPresentation.ts:479-520`; persist + optimistic + snapshot rollback in
  `useKanbanColumnsPresentation.ts:334-403`; endpoint `kanbanApi.ts:49-50`).
- **Cards are sortable** per-lane (vertical `SortableContext`, `:614-617`); moves go through a
  debounced patch queue (`kanbanPatchQueue.ts`, 800ms): 1 move → `PATCH /project/task/update/…/`
  (fallback `PATCH /project/tasks/{id}/`), 2+ → `POST /project/tasks/batch-move/`. Every displaced
  card's changed `order` is persisted, not just the dragged one
  (`useKanbanDragPresentation.ts:236-264`).
- **Board switcher**: `Team` select (hidden unless >1 team, `:1088-1101`) + `Board` select
  (= "Team board" or one of the team's projects, `:1102-1121`). So the UI already exposes a
  limited "multiple boards per team" via projects.
- **The "AI board" is not a distinct surface** — it is just the Agents team selected in the same
  component; no TRIAGE/OPTIMIZE strings exist anywhere in the frontend; all real columns are
  fetched (`useKanbanColumnsPresentation.ts:86-127`).

### Diagram (honest as-built)

```
Workspace
 ├── Team "General"  (blue_team, is_default) ──── team board (project=NULL cols):
 │                                                Backlog Todo InProgress Testing Complete Canceled
 ├── Team "Red Team" (red_team) ───────────────── team board: same 6 columns
 ├── Team "<user-created>" ────────────────────── team board: same 6 + "Done"(7)
 └── Team "Agents"   (ai_agents)
      ├── team board (project=NULL cols): "Triage", "Optimize"   ← specialists MOVE cards here
      └── Project "AI Findings"
           └── project board: Suggested / Under Review / Accepted / Dismissed
                               ↑ cards BORN here (finding_raised_board_handler)
      A card's life: Suggested (project board) ──specialist──▶ Triage/Optimize (team board),
      keeping project="AI Findings" → it vanishes from one board and appears on the other.
```

---

## (b) QA findings, ranked

### F1 — HIGH: the AI flow is split across two boards; three "AI Findings" columns are permanently dead

**Observed live** (Agents team): "Team board" shows only **Triage 50/562** and **Optimize 50/96**
(`tbqa-02-agents-team-board-triage-optimize.png`); switching Board → "AI Findings" shows
**Suggested 50/2852, Under Review 0, Accepted 0, Dismissed 0**
(`tbqa-03-ai-findings-project-board.png`). Under Review / Accepted / Dismissed can never be
non-zero from the AI side — no code path moves cards into them; specialists move cards to the
*other* board's Triage/Optimize columns (`_finding_processing.py:349-355`). The operator sees a
card vanish from Suggested and must know to flip the Board select to find it. **This is the
structural root of Henry's "triage/optimize columns are confusing".**

*Repro*: KANBAN → Team=Agents → toggle the Board select between "Team board" and "AI Findings".

*Fix sketch*: pick ONE canonical board for AI findings and make both the intake write and the
specialist move target it (options in §d). Whatever the choice, delete or repurpose the dead
columns and make the specialist move go through a path that keeps `team/project/column` consistent
(reuse the `move_task_to_board` service instead of a raw `column` write).

### F2 — HIGH (belief-correction): column drag-reorder is NOT missing — it exists end-to-end and works

Verified live on the General board: dragged the Todo column past In Progress → UI reordered →
`POST /api/v1/project/columns/reorder/` returned **200** → order survived a full reload
(`tbqa-04-column-reorder-after-drag.png`). Backend endpoint:
`ColumnReorderView` (`components/project/api/urls.py:53`,
`components/project/api/controller.py:1569-1648` — atomic, same-team/workspace validation,
membership-checked). Frontend wiring cited in §a. Both sides have been present since the initial
fork commits (2026-07-18, verified via `git log -S`).

The REAL gaps around reorder (see §f for the full list): **zero backend tests** for
`ColumnReorderView` (grep: only urls.py + controller.py reference it), **zero kanban E2E specs**
(frontend `e2e/` has none; DOM test hooks `data-kanban-*` exist unused), and the latent
order-reset in F3 — the one mechanism that could make a reorder *appear* not to stick.

### F3 — MEDIUM: `ensure_team_board_columns` force-reverts operator column order whenever it re-runs

`workspace_utils.py:305-308`: for each of the six seeded titles, if `column.order != <seed order>`
it writes the seed order back. Any operator reorder of the default columns is silently reverted
the next time the function runs for that team. Callers: workspace scaffolding (`:63`, `:93` — new
workspaces only), team create (`team_management_repository.py:63`), the
`seed_security_teams` command (`components/workspace/cli/management/commands/seed_security_teams.py:54` —
**iterates every workspace**; running it once as an ops backfill reverts every workspace's
customization), `backfill_team_board_columns.py:113`, and the agents kanban sync (F4). Not in the
startup scripts today (`docker/scripts/start-web.sh` seeds only tiers; `entrypoint.sh` only flags)
— so it's a landmine, not a routine bug.

*Fix sketch*: seed order only on create (`get_or_create` defaults), never re-assert it on existing
columns; keep the dedupe/`project=NULL` repairs.

### F4 — MEDIUM: `kanban_sync_service` imports a nonexistent module and swallows the failure

`components/agents/infrastructure/gateways/deep/kanban_sync_service.py:172-177` does
`from infrastructure.persistence.workspaces.utils import ensure_team_board_columns` inside
`try/except Exception: pass`. That module does not exist (verified — the real function lives in
`components/workspace/infrastructure/adapters/workspace_utils.py`), so the ensure-columns step has
silently never run. Fork-drift plus a swallowed ImportError — exactly the error-silencing the
project rules forbid. *Fix sketch*: import the facade
(`components.workspace.application.facades.workspace_facade`) or delete the step; either way drop
the blanket except. (Note: "fixing" the import would re-arm F3 on every deep-agent kanban sync —
fix F3 first or together.)

### F5 — MEDIUM: no team-creation UI; "+ Add team" is permanently disabled

`CommandCenterV2Page.jsx:3583-3590` renders `＋ Add team · soon` (`disabled`, no onClick). The
backend team-create path works (`POST /team/` → `TeamAddView`;
`team_management_repository.py:53-66` seeds membership + columns), and the frontend service
`createTeam` exists with no UI caller (`useSeedCollaborationPresentation.ts:658-687`). The
onboarding modal's "Teams" stage is copy-only — it tells the operator teams are auto-seeded and
creates nothing (`OnboardingPage.jsx:236-254`). Henry's "prompt own-team creation at onboarding"
has no surface today. Also: the SOC TEAM panel tile is dead — listed in `PANELS`
(`CommandCenterV2Page.jsx:187`) with no render branch → falls to "UNDER CONSTRUCTION" (`:5598-5608`).

### F6 — MEDIUM: no column rename or delete UI — a created column is permanent

Verified live: created "QA Temp Column" via the `+ Add Column` composer (works,
`tbqa-05-add-column-works.png`), then found no affordance to rename or remove it; cleanup required
a direct API call (`DELETE /project/columns/864/` → 204). Backend supports both
(`ColumnsView.put` handles rename + `is_deleted` with task archival, `controller.py:1356-1410`;
DELETE exists); frontend `updateColumn` / `softDeleteColumn` are built and context-exposed with
**zero component callers** (`useKanbanBoardItemsPresentation.ts:39-60`,
`useKanbanColumnsPresentation.ts:277-300`). The recycle tray restores tasks only
(`HudKanbanRecycleTray.jsx:21-24`).

### F7 — MEDIUM: four column vocabularies; user-created teams silently differ from seeded teams

See §a table. User-created teams get **"Done"(order 7)** on top of "Complete"
(`team_management_repository.py:110-117`) — two synonymous terminal lanes on the same board.
Directly contradicts "consistent columns everywhere". *Fix sketch*: one canonical seed list (drop
"Done" or replace "Complete"), applied identically at every team-creation path.

### F8 — LOW (latent): `ensure_board_column` can assign duplicate `order` values

`_finding_processing.py:93-94`: new auto-created columns get `order = first_column.order + 1`. On
the Agents board today this yielded Triage=1, Optimize=2 (verified via the live API — no collision
*yet*), but a third acting column would get 2 (collision with Optimize), and on a default team
board (orders 1..6) any auto column gets 2 (collision with Todo). `Column.Meta.ordering` is
`["order"]` with no tiebreaker (`models.py:165`) → unstable board layout. *Fix sketch*:
`Max("order") + 1` over the team's project-less columns, and add a deterministic tiebreaker
(`"order", "id"`) to `Meta.ordering`.

### F9 — LOW: board-as-inbox volume

562 cards in Triage, 96 in Optimize, 2852 in Suggested (demo workspace). Lanes window at 50 with
LOAD MORE, so rendering holds up, but as an operator surface these are unbounded inboxes; only
`code_security` / `vercel_posture` have a severity board-floor (`finding_raised_board_handler.py:429, :436`).
Relevant input for the model decision (§e): a "views over findings" model gets filtering for free.

### F10 — LOW assorted (bug-shaped, noted for the backlog)

- Team-title uniqueness is per-creator across ALL workspaces
  (`team_management_repository.py:51-52`) — creating "Ops" in a second workspace fails with
  "A team with the same name already exists!".
- Team switcher hidden when the workspace has exactly one visible team
  (`HudKanbanBoard.jsx:1088`) — the operator can't tell which board they're on.
- Task create sends no `order` (`useKanbanTaskMutationPresentation.ts:238-246`) — new cards rely
  on `order=0` + `created_at` tiebreak until the first drag.
- Column drag has no `DragOverlay` (source lane just goes `opacity-60`, `:565`) — weaker
  affordance than card drag.
- Column-reorder failure path is toast + snapshot restore with **no server refetch**
  (`useKanbanColumnsPresentation.ts:394-399`) — a partially-applied server state can drift until
  reload (task moves, by contrast, force `refreshBoard`).
- Dead exports: `PUT /project/columns/{id}/ {order}` variant (`kanbanApi.ts:43-44`) superseded by
  batch reorder, still exported.

### Not covered

- **Member (non-owner) view**: the workspace has a single seeded HUD login; provisioning a second
  real account + invite acceptance would have mutated demo-workspace membership, so it was skipped.
  Note the relevant backend rule: workspace admins/owners bypass team membership on board reads
  (`column_query_repository.py:242-255`) — a member-persona pass should assert the deny side.
- Websocket/live-update behavior of the board under concurrent edits.

---

## (c) Flag-gate sketch: default teams + onboarding team prompt

**Flag**: `feature.onboarding_team_choice` (name bikesheddable), added to `DEFAULT_FLAGS` in
`components/shared_platform/cli/management/commands/seed_feature_flags.py:28` — default **OFF**
(today's behavior unchanged), enable per-workspace/per-user for dogfood first. The per-user gate
precedent at this exact seam already exists: `feature.personal_space` in
`_create_bootstrap_workspace` (`workspace_bootstrap.py:116`). The frontend already receives flags
in `/identity/me/summary` (verified live: `user_summary.feature_flags` in localStorage).

**What it gates** (flag ON):

1. **Bootstrap** (`workspace_bootstrap.py:133`, `create_workspace_use_case.py:69`): still create
   ONE home team — but from the operator's chosen name (onboarding input) instead of silently
   "General"; skip the auto **Red Team** (`workspace_utils.py:67`) and surface it as an opt-in
   toggle in Settings / onboarding. The **Agents team + AI Findings board stay unconditional**
   (system-owned; the finding pipeline depends on `ensure_agents_board`,
   `finding_raised_board_handler.py:527`).
2. **Onboarding UI**: the copy-only Teams stage (`OnboardingPage.jsx:236-254`) becomes an input
   stage — name your team (prefill "General"), optional "also set up a Red Team" checkbox; posts
   through the existing create path.

**Why one team must still exist**: the platform assumes a default team — `active_team_id` is wired
into the profile at workspace create (`create_workspace_use_case.py:82`), the board resolves
`teams.find(is_default) || teams[0]` (`HudKanbanBoard.jsx:871-876`), and the dashboard pre-hydrates
from it (`CommandCenterV2Page.jsx:1877-1894`). The gate therefore swaps *silent naming* for
*prompted naming*; it cannot skip team creation entirely without a much larger rework.

**Migration implications**: none for existing workspaces (flag only alters the creation path; the
`is_default` dedupe machinery already guards re-runs, `workspace_utils.py:33-46`, covered by
`components/team/tests/integration/test_merge_default_teams_migration.py`). The flag can graduate
by flipping the seed default to ON — no data migration.

---

## (d) Column-consistency options for the AI board (F1)

Three shapes, in increasing ambition. No recommendation — Henry picks.

**D1 — One AI board: fold the acting columns into the AI Findings board.**
Specialists move cards to columns *of the same project board* — either literally "Triage"/
"Optimize" columns created under the project, or reuse the existing "Under Review" (+ keep
Accepted/Dismissed as the human outcome lanes, which finally gives them a purpose).
Changes: `ensure_board_column` gains a `project` parameter (or `process_pending_finding` targets
`board.column(UNDER_REVIEW)` via `ensure_agents_board`); the team-board Triage/Optimize columns are
migrated (cards re-pointed, columns soft-deleted). Cost: small backend change + a data migration
per workspace; the HUD needs nothing (columns are fetched). Risk: workflow bindings/consumers that
assume the current column names (`ensure_ai_findings_workflow_binding`, board cutover tests
`test_logwatch_board_cutover.py`) need a sweep.

**D2 — Consistent columns everywhere: AI cards live on the standard vocabulary.**
The AI surface adopts the same workflow columns as every other board (e.g. Backlog/Todo/In
Progress/…), and AI state (suggested / triaged / fix-ready / needs-human) becomes card chips
driven by `task.metadata.triage` — which the card callout already renders. Columns then mean the
same thing on every board in the product. Cost: moderate — remap intake + specialist moves to the
standard lanes, decide what "Suggested" maps to, migrate existing cards; messaging in the HUD
already leans on metadata chips (FIX READY etc.). Risk: loses the "AI funnel" as a spatial
metaphor; the finding lifecycle reads from chips, not lanes.

**D3 — Keep two boards, but make them honest views.**
Rename "Team board" → "Acting" and "AI Findings" → "Intake" for the Agents team, always show the
Board select, and fix the FK inconsistency by routing the specialist move through
`move_task_to_board` semantics. Cheapest; removes the *mystery* but keeps two column vocabularies
on one team — it does not satisfy "consistent columns everywhere".

In all three: kill or repurpose the permanently-dead columns, and fix F8's ordering scheme.

---

## (e) Multi-board-per-team — researched models

Grounding: Linear docs (board layout, teams, custom views), Atlassian Jira Cloud docs (columns ↔
statuses, boards from saved filters), GitHub Projects docs (views, board layout backed by a
single-select field), Height release notes. Full pattern write-up preserved below; three candidate
models for autosec:

**Model A — "Board = saved view over a per-team status vocabulary" (Linear / GitHub Projects / Height).**
One canonical status field (per team) is the single source of truth; a board is a saved
filter + grouping rendered as lanes; N views per team are cheap.
- Pros: zero column drift (one vocabulary per team), rollups/reporting trivially consistent,
  adding a "view" needs no migration, kills the F1 class of bug permanently — the AI intake and
  acting surfaces become two *filters* over the same cards.
- Cons: largest adoption cost for autosec: introduces a Status concept (today status is the
  column FK plus a vestigial `Task.status` todo/done/archived field, `models.py:186-190` — note
  that field already exists and is mostly unused: a head start), migrates Column → status values +
  view definitions, reworks the HUD switcher into a views bar.
- Cost: the big one — new model + data migration + frontend views UI. Weeks, not days.

**Model B — "Board = first-class entity owning its columns" (Jira).**
Formalize what autosec half-has: a `Board` entity per team (the current "team board" and each
project board become Board rows), columns FK to a board, many boards per team.
- Pros: matches the existing two-axis reality (cheap conceptual migration: team-board → Board #1,
  each project's columns → its Board), full flexibility (an "engineering" and a "customer" board
  over different cards), the Board select generalizes naturally.
- Cons: this is the pattern with the documented confusion cost (Jira's "which board is the
  truth" / unmapped-status support burden); it *legitimizes* diverging column vocabularies —
  the opposite of "consistent columns everywhere" unless paired with column templates per board
  kind.
- Cost: moderate — new table + FK backfill migration (mechanical), modest API/HUD changes.

**Model C — Harden the status quo (team board + per-project boards), no new entity.**
Keep board == team (+ optional project sub-boards), and spend the effort on consistency: one seed
vocabulary everywhere (F7), one AI board (§d), Board/Team selects always visible, cross-board
moves always through `move_task_to_board`.
- Pros: days of work, no migration risk, directly addresses every confusion Henry named.
- Cons: "multiple boards per team" stays limited to projects; saved filtered views (the thing
  operators eventually ask for — William's "single actionable digest" feedback points this way)
  remain unbuilt; revisiting Model A later re-opens the migration.

Reference patterns (from the research pass): Linear renders any view as board/list over per-team
workflow states; Jira boards are saved filters with per-board column↔status mapping (many-to-one);
GitHub Projects backs board columns with a single-select field and allows N views per project;
Height mirrors the Linear shape (lists + saved views). The industry mass is on "columns are values
of one shared field; boards are views" — Jira is the notable holdout, and its per-board mapping is
the documented source of its confusion tax.

---

## (f) Drag-reorder: actual state + concrete gap list

**It exists and works** (F2): backend `POST /project/columns/reorder/`
(`urls.py:53`, `controller.py:1569-1648`), frontend dnd-kit column sortable + persist
(`useKanbanDragPresentation.ts:479-520`, `useKanbanColumnsPresentation.ts:334-403`,
`kanbanApi.ts:49-50`). Verified live with persistence across reload. Both since the 2026-07-18 fork
commits.

Gaps, concretely:

1. **No backend tests** for `ColumnReorderView` — happy path, cross-team batch rejection (400),
   non-member 403, atomicity. (Grep shows zero test references.)
2. **No kanban E2E at all** (`auto-sec-frontend/e2e/` has no kanban spec; DOM hooks
   `data-kanban-lane`, `data-kanban-lane-header`, `data-kanban-add-task`, `data-kanban-load-more`
   exist unused — `HudKanbanBoard.jsx:581, 610, 643, 685`). A Playwright spec must use stepped
   pointer movement (the 5px activation constraint means a naive `dragTo` no-ops — reproduced
   during this pass).
3. **The F3 order-reset landmine** — the only code that can undo a persisted reorder; fix before
   anything re-runs scaffolding routinely.
4. **F8 duplicate-order assignment** by `ensure_board_column` + no ordering tiebreaker.
5. **Failure path**: column reorder rollback is local-snapshot-only (no refetch) — align with the
   task-move path's `refreshBoard` on error.
6. **Polish**: no column `DragOverlay`; dead `PUT /project/columns/{id}/ {order}` export.
7. **Persistence scheme**: integer reindex of all columns per drop is fine at ≤10 columns
   (research consensus); fractional/lexicographic indexing is only worth it if columns or
   concurrent reordering grow — noted, not needed now.

---

## (g) Decision list for Henry

1. **AI board shape** — D1 (one AI board), D2 (standard columns + AI chips), or D3 (two honest
   views)? This decides F1 and most of "consistent columns".
2. **Team↔board model** — Model A (views over statuses), B (Board entity), or C (harden status
   quo)? A and C are compatible sequentially (C now, A later) but the A migration doesn't shrink.
3. **Flag-gate scope** — gate only the *naming prompt* + Red-Team opt-in (sketch in §c), or do you
   want new workspaces to be creatable with literally zero non-system teams (bigger rework —
   `active_team_id` and board default-selection assumptions)?
4. **Canonical column seed** — drop user-created teams' "Done" or drop "Complete"? Six lanes or
   fewer (Linear defaults to ~5)?
5. **Board floor for AI cards** — extend `min_severity` beyond code_security/vercel to cap the
   562-card Triage inbox, or is that the sample-data skew talking?
6. **Column rename/delete UI** — ship it (backend is ready), or deliberately keep columns
   append-only for operators?
7. **Priority of the QA-robustness debt** — greenlight the test pack (backend reorder tests +
   first kanban E2E) as its own PR ahead of any model rework?

---

*QA evidence: screenshots `tbqa-01`…`tbqa-06` under `/Users/henrywanjala/Desktop/claude-smoke/`
(01 General board; 02 Agents team board Triage/Optimize; 03 AI Findings board with dead columns;
04 column order persisted after drag; 05 Add Column works; 06 board restored post-cleanup).*
