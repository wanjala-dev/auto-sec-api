# ADR 0030 — Boards are views over per-team statuses; AI state is chips, not lanes

- **Status:** PROPOSED — the build does not start until Henry approves this document.
  (The direction itself is decided: Henry picked Model A + D2 from
  `docs/reviews/TEAMS_BOARDS_QA_2026-08-16.md` §g on 2026-08-17. What this ADR fixes is the
  *shape* of the build, so the weeks-scale migration is reviewed before it burns time.)
- **Drivers:** the 2026-08-16 teams/boards QA pass (findings F1, F7, and the two-board AI flow);
  Henry's 2026-08-09 direction ("consistent columns everywhere"); Tom's persisted-saved-views
  double-down (task #74).

## Context

The QA report established the as-built model precisely (§a; file:line citations there):

- **There is no Board entity.** A "board" is a derived concept: the set of `Column` rows with
  `project IS NULL` for a team ("team board") or `project = <p>` ("project board"). `Column.order`
  is an integer; `Task.column` is a nullable `SET_NULL` FK.
- **Four column vocabularies coexist** (F7): bootstrap teams (6 lanes), user-created teams
  (the same 6 plus a redundant "Done"), the AI Findings project board (Suggested / Under Review /
  Accepted / Dismissed), and the Agents team board (lazily-created Triage / Optimize).
- **The AI finding's life crosses two boards** (F1): cards are born on the AI Findings project
  board's Suggested lane, then a specialist moves them to the Agents *team* board's
  Triage/Optimize — updating only the `column` FK, so the card keeps `project = "AI Findings"`
  while sitting in a column that belongs to no project. Three AI Findings columns are permanently
  dead, and cards visibly vanish from one board and appear on another.
- The column-as-status design means every consistency property (same lanes everywhere, honest
  rollups, "where is this card") must be re-enforced per seeder, per handler, per board — and the
  QA pass showed it is not (F3 order-reverting seeder, F8 duplicate orders, the FK inconsistency
  above).

The research pass (§e) grounded the industry shape: Linear, GitHub Projects and Height all model
**columns as values of one shared status field and boards as saved views over it**; Jira is the
holdout with first-class boards owning column↔status mappings, and that per-board mapping is the
documented source of Jira's "which board is the truth" confusion tax. Model B (a Board entity) was
rejected for exactly that reason: it *legitimizes* diverging vocabularies — the opposite of what
Henry asked for.

A head start already exists in the schema: `Task.status` (todo / done / archived) is a vestigial,
mostly-unused field — evidence the model always wanted a status axis and never got one.

## Decision

### 1. One status vocabulary per team; statuses are rows, not columns

New model `WorkflowStatus` (in `infrastructure/persistence/project/`, beside `Column`):

```
WorkflowStatus: id · workspace FK · team FK · name · order · category
```

- `category ∈ {backlog, unstarted, started, completed, canceled}` — the Linear-style coarse axis
  that survives renames. Rollups, the BRIEF card, and reporting read *category*; lanes read
  *status*. This is what makes "consistent columns everywhere" durable instead of re-seeded.
- The canonical seed is the 6-lane set the quick-wins PR is already converging on
  (Backlog / Todo / In Progress / Testing / Complete / Canceled), mapped onto categories
  1:1 except Testing → `started`.
- `Task` gains `workflow_status` FK (nullable during migration, non-null at cutover). The
  vestigial `Task.status` field is absorbed: `done` ↔ category `completed`, `archived` stays an
  orthogonal lifecycle flag exactly as today.
- Per-team custom statuses are allowed later (rename, insert) but NOT part of this build — the
  seed is uniform; the model merely stops making uniformity a per-seeder promise.

### 2. A board is a saved view

New model `BoardView`:

```
BoardView: id · workspace FK · team FK · name · slug · filter (JSON) · group_by · order · is_system
```

- `filter` is a small, closed vocabulary (project id, source_type, severity floor, assignee,
  tag) — **not** a query language. Every existing "board" becomes a system view at migration:
  the team board = the unfiltered view; each project board = a `project = <p>` view.
- The HUD's Team/Board selects become a views bar rendering `BoardView` rows; lanes are the
  team's `WorkflowStatus` rows filtered by the view. The board component itself
  (`HudKanbanBoard.jsx`) keeps its dnd-kit machinery — what changes is where lanes and
  membership come from.
- This is deliberately the substrate for **#74 (Tom's persisted saved views)**: a user-saved view
  is a non-system `BoardView` row plus a `created_by` — the entity, API and views bar built here
  are that feature's foundation, not a parallel mechanism.

### 3. AI state is chips on standard lanes (D2)

The AI surface stops having its own column vocabulary:

- Findings are born in **Todo** (category `unstarted`) with chip `suggested`.
- A specialist acting moves the card to **In Progress** with chips `triaged` / `optimizing` /
  `fix-ready` / `needs-human` — driven by `task.metadata.triage`, which the card callout already
  renders today.
- Human outcomes land in **Complete** (accepted) or **Canceled** (dismissed, with the dismissal
  reason chip). The permanently-dead Under Review / Accepted / Dismissed lanes and the lazy
  Triage / Optimize lanes are retired.
- The Agents team gets two **system views**: "Intake" (`status category = unstarted`,
  source_type-filtered) and "Acting" (`started`) — the two honest surfaces of what is today two
  boards, over ONE set of cards. Nothing vanishes; a view change is a filter change.
- `_finding_processing`'s move writes `workflow_status` through the same path human moves use, so
  the F1 FK inconsistency class is gone by construction, not by discipline.

### 4. Phased migration with dual-write; each phase shippable and reversible

| Phase | Ships | Reversible by |
|---|---|---|
| **P1** | `WorkflowStatus` + `BoardView` models; backfill statuses from each team's existing columns (per-team mapping table, exceptions logged); dual-write: every column write also sets `workflow_status`; reads unchanged | dropping the new tables — columns never stopped being authoritative |
| **P2** | Views API + HUD views bar behind flag `feature.boards_as_views`; flag ON reads lanes/membership from statuses+views, OFF keeps today's board | flag off |
| **P3** | AI cutover (D2): intake + specialist moves target statuses; data migration re-points existing AI cards (Suggested→Todo, Triage/Optimize→In Progress with chips, Accepted→Complete, Dismissed→Canceled); board-cutover tests (`test_logwatch_board_cutover.py` et al.) swept | flag off + the migration is re-runnable in reverse (mapping is bijective and recorded per card) |
| **P4** | Cutover: flag default ON, `Task.column` dual-write removed, `Column` demoted to a render-cache or dropped, dead AI columns deleted | none — this is the point of no return, taken only after P2/P3 have soaked on the dogfood workspace |

Every data migration follows the repo's established pattern (pinned `schema_editor.connection.alias`,
`.objects.using(db_alias)`) and lands with tests. Every queryset added is workspace-scoped —
tenancy invariant 8 (every new read seam ships an isolation test) applies to the views API in P2.

## What we are explicitly not doing

- **No Board entity owning columns** (Model B / Jira) — rejected above.
- **No per-board column↔status mapping.** One vocabulary per team, views filter it.
- **No query language in `filter`.** Closed keys only; extending it is a deliberate change.
- **No second drag library, no board component rewrite.** dnd-kit and `HudKanbanBoard` stay.
- **No change to the finding pipeline's spine** (ADR 0004): `FindingRaised` →
  `finding_raised_board_handler` still owns card creation; only its *target* changes in P3.

## Consequences

**Positive.** F1 and F7 become structurally impossible rather than continuously patched; rollups
and the severity floor read one axis; #74 gets its substrate for free; the two-board vanishing act
ends; the four vocabularies collapse to one; operator column reorder (fixed in the quick-wins PR)
stops being a per-seeder truce.

**Negative / costs.** Weeks, not days: two new models, a backfill, dual-write discipline across
P1–P3, a views API with isolation tests, and a frontend views bar. Dual-write is a known bug
surface — it is why every phase keeps a one-step rollback. The spatial "AI funnel" metaphor is
traded for chips; if operators miss it, the Intake/Acting system views are the mitigation.

**Sequencing.** The quick-wins PRs (F3/F4/F8, reorder tests, canonical seed, severity floor,
onboarding flag-gate) land FIRST — they are compatible with and shrink this migration (one seed
vocabulary in means a simpler backfill). P1 starts only after this ADR is approved and those PRs
are merged.

## References

- `docs/reviews/TEAMS_BOARDS_QA_2026-08-16.md` — findings, research, and the option analysis this
  decision selected from (§d D2, §e Model A).
- ADR 0004 — the finding/asset spine this build must not disturb.
- ADR 0007 — defensive-by-default teams (the flag-gated naming prompt refines, not replaces it).
- Linear docs (workflow states, custom views); GitHub Projects docs (single-select-backed boards,
  N views); Atlassian docs (board↔filter model) — surveyed in the report's §e.
- Task #74 — persisted saved views (Tom), built on `BoardView`.
