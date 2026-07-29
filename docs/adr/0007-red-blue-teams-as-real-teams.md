# ADR 0007 — Red / Blue Teams as Real Teams (a discipline lens over shared data, not a data silo)

Status: Accepted (2026-07-29)
Relates to: ADR 0002 (persona ≠ role — RBAC lives on role, not persona),
ADR 0004 (CNAPP unified Finding + Asset spine — findings are a workspace-scoped SSOT),
the frontend HUD "mode dial" (the ring is the mode selector; the Blue⇄Red flip rides it).

## Context

The HUD grew a **Blue ⇄ Red team flip**: spin the center ring (or click a toggle) and the
whole command center morphs from the defensive SOC view (Blue) to an offensive Cyber-Kill-Chain
view (Red) — colour, modes, and hex nodes all change. As first shipped it was a **pure
frontend costume**: a `redTeam` boolean + a `.team-red` CSS class, with **no connection to any
`Team` record, no membership, no access control**. Refresh and you're Blue again.

That raised the real question this ADR answers: **should Red and Blue be actual teams in the
database, and if so, what exactly does "belonging to the Red team" scope?** The tempting-but-wrong
answer is "give each team its own findings/assets" — a per-team data silo. Three facts make that
the wrong call, and point at the right model:

1. **Findings/assets are a workspace-scoped SSOT (ADR 0004).** There is deliberately **no `team`
   FK on `Finding`** — dedup + lifecycle happen once, per org. Siloing findings per team would
   fight the unified spine, break dedup, and destroy cross-discipline collaboration.
2. **The security industry doesn't silo the data either.** Red emulates adversary TTPs; Blue
   detects them; **both look at the same telemetry**. MITRE ATT&CK is a *shared* taxonomy (Red
   plans emulations with it, Blue maps detections + coverage gaps with it). The collaboration
   where Red attacks and Blue detects *against the same data* has a name — **Purple Team** — and
   it only works if the data is shared. (Sources: Orca/Sysdig on Blue = CNAPP/CSPM/SIEM/SOC;
   MITRE ATT&CK "adversary emulation and red teaming"; SANS purple-team framework.)
3. **The backend is already shaped for the right model.** `Team.kind` is a purpose
   discriminator (`DEPARTMENT | PROJECT_TEAM | AI_AGENTS`); `Team.is_default` marks the home
   team; `Task.team` + per-team Kanban boards already scope *work* to a team; `TeamMembership`
   (LEAD/EDITOR/VIEWER) + `IsTeamLead`/`IsTeamEditor` + capability-backed `has_workspace_permission`
   already gate *actions*. What's team-scoped today is **people + boards + tasks + actions** —
   exactly the things Red/Blue *should* scope.

So the taxonomy lands cleanly: **CNAPP / CSPM / attack-graphs / triage / SOC / SIEM = Blue**
(defensive), **adversary emulation / running the kill chain = Red** (offensive), **ATT&CK =
the shared/Purple bridge**. A given TTP is *detected* by Blue and *emulated* by Red — same fact,
two sides. None of that requires the *data* to be partitioned.

## Decision

**1. Red and Blue are real teams, expressed as `Team.kind` values.** Add `BLUE_TEAM` and
`RED_TEAM` to the existing `Team.Kind` discriminator. They are seeded as default teams at
workspace bootstrap:

- **Blue Team is the default/home team** (`is_default=True`, `kind=BLUE_TEAM`) — every workspace
  is **defensive-by-default**. The existing single default team *becomes* the Blue team; no new
  "home team" concept is introduced.
- **Red Team is seeded alongside it** (`kind=RED_TEAM`, `is_default=False`) — a necessary system
  team, present from bootstrap, but **opt-in**: offensive work is deliberate, not the default.
- The workspace owner is enrolled in **both** (as `TeamMembership.Role.LEAD`).

**2. Red/Blue scopes people + boards + tasks + actions — NEVER findings/assets.** Findings,
assets, attack-paths and scans stay **workspace-scoped** (ADR 0004 unchanged — no `team` FK is
added to `Finding`). What differs per team is:

- the **board** (Blue's carries triage/detection work; Red's carries kill-chain/emulation work),
- the **tasks** on it (already `Task.team`-scoped),
- the **actions** a member may take (offensive/irreversible actions gate behind a Red-team
  capability — see decision 3),
- the **HUD lens** (the modes/colour/nodes the flip already swaps).

This is what keeps **Purple** possible: both teams read the same findings; only their *work* and
*capabilities* differ.

**3. Red/Blue membership is RBAC (role/capability), NOT persona.** Per ADR 0002, `persona` is
UX-routing only and MUST NOT drive permissions. "You can't cross into a team you're not in unless
you're a workspace admin" is enforced through **`TeamMembership` + the existing team permission
classes** (and, for offensive actions, capability keys), never through `persona`. Concretely:

- The frontend flip switches your **active team**, and is **gated by `TeamMembership`**: you may
  flip among teams you belong to; a **workspace admin/owner** may view any team; a non-member
  cannot cross over.
- Irreversible/offensive actions (the response-action framework) require a **Red-team
  capability**, checked via `has_workspace_permission`, independent of the visual flip.

## Consequences

- **The flip becomes honest.** After Slice 1 the ring flip reflects real team membership and is
  access-gated — no longer a costume — while still "not doing much" (no offensive tooling yet),
  which matches the intended rollout.
- **No migration of the SSOT.** `Finding`/`ScanRun`/asset-graph are untouched; dedup and
  cross-pillar correlation keep working exactly as ADR 0004 specifies.
- **Purple is a first-class outcome, not an afterthought** — shared findings + per-team work is
  precisely the purple-team pattern.
- **`Team.kind` gains two values.** A Django migration records the choices change; the seeding is
  additive and idempotent (bootstrap already prefers an existing default team, so re-runs never
  duplicate). Existing workspaces get their Red team + their default team's `kind` set to
  `BLUE_TEAM` via a data backfill.

## Alternatives considered

- **A — Keep it a pure UX lens (persona/boolean).** Simplest, but it can never enforce
  "can't cross over" (persona is UX-only per ADR 0002) and it doesn't make Red/Blue *mean*
  anything in the system. Rejected: the user explicitly wants real, necessary teams.
- **B — Silo findings per team (add `Finding.team`).** Superficially matches "each team its own
  data," but fights the ADR-0004 unified SSOT, breaks dedup, and kills Purple (Red and Blue could
  no longer reason over the same telemetry). Rejected as an architecture regression.
- **C (chosen) — Real `Team.kind` teams scoping people/boards/actions; findings stay the shared
  SSOT; RBAC (not persona) gates crossover.** Fits the existing model with minimal new surface,
  keeps ADR 0004 intact, and is the industry-correct (purple-enabling) shape.

## Rollout (slices)

1. **Make the flip real (this ADR's first slice):** add `BLUE_TEAM`/`RED_TEAM` to `Team.kind`;
   seed both at bootstrap (Blue = default) + backfill existing workspaces; rewire the frontend
   flip to switch the *active team*, gated by `TeamMembership` (admins see all).
2. **Scope boards/actions:** Red board carries offensive/kill-chain tasks; gate the
   response-action framework's irreversible actions behind a Red-team capability.
3. **Later:** actual offensive tooling / adversary-emulation runs. Not now.
