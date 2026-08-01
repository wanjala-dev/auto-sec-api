# ADR 0010 — Multi-Provider VCS Integration behind a `VcsPort` (GitHub / GitLab / Bitbucket)

Status: Proposed (2026-07-31)
Relates to: ADR 0008 (`LogSourcePort` — the driven-adapter-behind-a-port + per-workspace-config model +
registry template this mirrors **exactly**), ADR 0006 (`ScannerPort`), and the existing design plan
`docs/plans/AGENT_DRAFT_PR_DESIGN_2026-07-19.md` (the GitHub draft-PR work this generalizes and productizes).

## Context

Auto-Sec's triage agent can already **open a draft pull request** to remediate a finding — it commits one
file and opens a *draft* PR the human reviews and merges. This is real, shipped code:

- `GitHubPrPort` (`application/ports/github_pr_port.py`) — `get_default_branch` / `get_file` /
  `create_branch` / `commit_file` / `open_draft_pr`.
- `GitHubPrAdapter` (`requests` → api.github.com, fine-grained PAT), `github_pr_provider`,
  `OpenDraftPrUseCase` (all preconditions in one choke point), and a real triage-agent tool
  (`triage_agent.py::open_draft_pr`).
- `GitHubConnection` model — workspace-scoped, **`repo_allowlist`** (the consent boundary), encrypted PAT
  via the `secret_envelope`.

But it is a **Phase-A dogfood**, and two things force this ADR:

1. **It's un-productized.** There is **no CRUD API and no Settings UI** to create/manage a connection — the
   `GitHubConnection` is created by hand (Django admin / DB). That is *why GitHub does not appear under
   Settings ▸ Integrations*, and why the tool can't fire on the demo: with no connection linked, the use
   case correctly raises `DraftPrPreconditionError(no_github_connection)`. Log sources got the full CRUD +
   panel treatment (ADR 0008 phases 3 & 6); VCS never did. This is the un-finished half.
2. **GitHub is one provider among several.** Organizations use **GitLab** and **Bitbucket** too, and a
   single org may link **more than one at once**. The current `GitHubConnection` + `GitHubPrPort` hard-code
   one provider — the same trap `trail_s3_bucket` was for logs. We want the `WorkspaceLogSource` shape: a
   per-workspace, many-rows, provider-tagged connection behind a port + registry.

The three concerns to untangle (mirrors ADR 0008's table):

| Concern | Question | Owner |
|---|---|---|
| **A. Provider integration** | *how* to read a repo + open a draft change-request on GitHub vs GitLab vs Bitbucket (auth, branch, commit, PR/MR) | **`VcsPort` adapter** — one per provider |
| **B. Per-workspace config** | *which* repos a workspace links, on which provider, with what secret + lifecycle | **`VcsConnection`** model (many rows per workspace) |
| **C. Remediation flow** | finding → grounded patch → branch + commit + draft PR → record + notify | **provider-agnostic `OpenDraftPrUseCase`** (today's, generalized) |

### Grounding (research + review)

- **In-repo precedent — `LogSourcePort` (ADR 0008).** Identical shape: a driven adapter per source behind
  one port, a per-workspace config model with many rows, a `kind → adapter` registry, flag-gated nascent
  adapters, secrets via the envelope, and a CRUD API + Settings panel. **VCS is `LogSourcePort` for code
  hosts.** S3 was "the first adapter that ships while the seam generalizes"; **GitHub is the S3 of VCS.**
- **In-repo precedent — the existing GitHub port is already provider-neutral in shape.** Reviewing
  `github_pr_adapter.py`: every operation (`get_default_branch`, `get_file`, `create_branch`,
  `commit_file`, `open_draft_pr`) maps cleanly onto GitLab and Bitbucket REST — only the *names* and the
  HTTP details are GitHub-specific. Generalizing is a **rename + registry**, not a rewrite (improve, don't
  replicate).
- **Industry — "VCS provider" is the standard abstraction.** Terraform Cloud, Backstage, Sentry Seer, and
  GitHub/GitLab/Bitbucket themselves treat "connect a VCS" as a pluggable provider with an app/token +
  a repo scope. Sentry Seer's shape (telemetry → root cause → fix PR via an installed GitHub App, or hand
  off to an external coding agent) is the exact target; the app-install *is* the consent boundary.

## Decision

Introduce **`VcsPort`** (a driven-adapter seam), a **`VcsConnection`** per-workspace config model, and a
**`VcsProvider`** registry — **generalizing the existing GitHub-specific code** rather than adding a second
silo. All in **`components/integrations`** (which already owns it). GitHub is the **proven first adapter**;
GitLab/Bitbucket are **flag-gated follow-ons, designed-for but not built now**. Per Henry: build it for now
(GitHub, to par), design the seam so a second provider is *just an adapter*, don't over-invest in the future.

```
 VcsConnection rows                    VcsProvider (registry: provider → adapter)
 (per workspace, MANY / mixed)   ┌──────────────┬──────────────┬───────────────┐
  provider / repo_allowlist /    ▼              ▼              ▼
  secret / status           GitHubVcsAdapter  GitLabAdapter  BitbucketAdapter   ← driven adapters
        │                        └────────── all implement VcsPort ────────────┘  (gitlab/bitbucket flagged)
        │  verify(config) → health
        ▼  get_default_branch · get_file · create_branch · commit_file · open_draft_pr
  OpenDraftPrUseCase (provider-agnostic: preconditions, grounded patch, record + notify)
        ▼
  triage-agent tool · HITL endpoint · (later) response-action framework
```

### D1 — `VcsPort` (generalize `GitHubPrPort`) + add `verify()`

Rename/generalize `GitHubPrPort` → `VcsPort` (application/ports/), keeping its provider-neutral DTOs
(`DefaultBranch`, `RepoFile`, `CommittedFile`, `DraftPullRequest`) and operations. **Add the one operation
it lacks vs. the log-source bar: `verify(config) → VcsHealth`** (a cheap reachability + repo-access probe),
so the CRUD verify endpoint and the panel can confirm a connection before the agent relies on it.
`GitHubApiError` → a provider-neutral `VcsApiError` (adapters raise it). (`DraftPullRequest` stays the port
term; a GitLab *merge request* / Bitbucket *pull request* is the adapter's mapping — GitLab drafts via a
`Draft:` title prefix, Bitbucket has no native draft state, both handled in-adapter.)

### D2 — `VcsConnection` model (generalize `GitHubConnection`, many rows, provider-tagged)

`infrastructure/persistence/integrations/`:

```
VcsConnection
  workspace (FK)
  provider        github | gitlab | bitbucket        # NEW — the discriminator
  name            "prod org (GitHub)"
  repo_allowlist  JSONField   # "owner/repo" (or project path) the agent may open PRs against — CONSENT boundary
  secret_ref / token_ciphertext   → secret_envelope (encrypted; never plaintext)  # reuse existing envelope
  base_url        CharField (blank)   # self-hosted GitLab / Bitbucket Server; defaults to the SaaS host
  status          connected | disabled | error
  last_used_at / last_error / last_verified_at
```

Many rows per workspace = an org can link **GitHub *and* GitLab** (Henry's "some orgs add both") — falls out
free, not future-built. Direct analog of `WorkspaceLogSource` / `WorkspacePaymentMethod`. **Data migration:**
copy existing `GitHubConnection` rows → `VcsConnection(provider="github")` (idempotent); deprecate
`GitHubConnection` with a transitional read (same strangler move as `trail_s3_bucket` → `WorkspaceLogSource`).

### D3 — `VcsProvider` registry (generalize `github_pr_provider`)

`provider → VcsPort` factory, exactly like `LogSourceProvider`'s `kind → adapter`. The composition root that
knows the concrete adapters exist and resolves `secret_ref` before handing `config` to the adapter.
GitLab/Bitbucket adapters are registered **behind `feature.vcs_gitlab` / `feature.vcs_bitbucket`** (default
off, fail-closed — the `feature.log_source_cloudwatch` pattern). `OpenDraftPrUseCase` picks the adapter by
`connection.provider` via the registry (it currently hard-calls `get_github_pr_adapter`).

### D4 — GitHub is adapter #1; GitLab/Bitbucket are flagged follow-ons

The existing `GitHubPrAdapter` becomes `GitHubVcsAdapter`, re-registered under `provider="github"` —
behavior-identical, the triage tool keeps working throughout. `GitLabAdapter` (Projects/Repository/Merge
Requests API; draft via title) and `BitbucketAdapter` (Pull Requests API) are **designed-for but NOT built
in this ADR's scope** — each is later "just an adapter + a registry line + a flag," proving the seam like
CloudWatch proved `LogSourcePort`.

### D5 — Productize: CRUD API + Settings panel (the missing half)

- **CRUD API** — `VcsConnectionService` (list / create / update / delete / verify) mirroring
  `LogSourceService`; thin controller endpoints under `/integrations/workspaces/<ws>/vcs-connections/`;
  request/resource DTOs mirroring `log_source_request` / `log_source_resource`. `verify` calls
  `VcsPort.verify` and flips `connected`/`error` (mirrors log-source verify).
- **Frontend panel** — a **"Code Repositories"** panel in `IntegrationsSection` (mirror `LogSourcesPanel`):
  a **PROVIDER picker** (GitHub now; GitLab/Bitbucket shown "coming soon"), the **repo allowlist** editor,
  the **PAT** field (Phase A), and verify / enable-disable / delete. This is the piece whose absence is why
  "GitHub" isn't in the UI today.
- **Agent-capability toggle** — surface `Agent.config.capabilities.open_draft_pr` in settings so an operator
  explicitly grants the triage agent its PR power (the use case already enforces this precondition).

### D6 — Secrets & identity

Reuse the integrations `secret_envelope` (already used — `token_ciphertext` via `decrypt_secret`), resolved
only inside the provider, never in `config`/logs/`VcsHealth.detail`. **Phase B (later):** replace the PAT
with a **GitHub App installation** (short-lived, per-operation, repo-scoped tokens; PRs authored by
`auto-sec[bot]`) — already the recommended path in the design plan; GitLab/Bitbucket have equivalent app
models. The app install becomes the on-behalf-of service principal (closes a governance gap).

### D7 — Decouple the remediation flow from log-watch (later)

`OpenDraftPrUseCase` is currently bound to `ai.log_watch` findings + `LogPatchAdvisor`. Henry's framing —
"a draft PR to the correct repo; not everything is IaC" — means *any* grounded finding should be able to
produce a PR. Generalizing the finding-source coupling (any finding with a grounded patch advisor) and
wiring it into the **response-action framework** (propose → approve → execute) is real follow-on work, noted
here but **out of this ADR's productize-now scope**.

## Consequences

- Adding the Nth code host = a `VcsPort` adapter + a registry line + a flag. Auth/branch/commit/PR mechanics
  are the adapter's problem; preconditions, grounded-patch, recording, notification, and the agent tool are
  inherited from `OpenDraftPrUseCase` — solved once (mirrors "adding the Nth scanner / log source").
- A workspace links any mix of providers simultaneously (GitHub + GitLab), each with its own allowlist.
- The triage agent's draft-PR power becomes **self-serve and demoable** — the reason it's invisible today is
  removed.
- Cost: a rename/generalize refactor of shipped GitHub code + a new model/migration + CRUD API + a Settings
  panel. Mitigated by the strangler phases (GitHub stays working throughout; the existing tests cover it).

## Non-goals

- **Not** building the GitLab/Bitbucket adapters now (flag-gated, designed-for — later).
- **Not** the GitHub App yet (PAT v1 stays; App is Phase B).
- **Not** a general git client — only the draft-PR operations the core needs.
- **Not** auto-merging — it opens a *draft*; review + merge stay human.
- **Not** over-modelling the future (no repo-discovery/webhook sync until a real need).

## Implementation plan (strangler — each phase ships on its own; this ADR is the spec)

1. **Generalize the seam.** `GitHubPrPort` → `VcsPort` (+ `verify()`), `github_pr_provider` →
   `VcsProvider` registry, `GitHubPrAdapter` → `GitHubVcsAdapter` registered under `provider="github"`;
   `OpenDraftPrUseCase` resolves the adapter via the registry. Behavior-identical; existing tests green.
2. **`VcsConnection` model** (D2) + data migration from `GitHubConnection` (provider=github); deprecate the
   old model with a transitional read. Unit/integration tests (idempotent migration, allowlist gate).
3. **CRUD + verify API** (D5) — `VcsConnectionService` + thin controller + DTOs, mirroring log sources.
4. **Frontend "Code Repositories" panel** (D5) in Settings ▸ Integrations (provider picker + allowlist + PAT
   + verify), mirroring `LogSourcesPanel`; + the agent-capability toggle. **This makes GitHub appear in the
   UI.**
5. **Exercise on the demo** — link a demo repo via the new UI, enable the capability, and drive one triaged
   finding → real draft PR end-to-end (closes the "it doesn't actually apply" gap).
6. **(Flagged, later)** `GitLabAdapter` + `BitbucketAdapter`, each behind its flag — the seam proof.
7. **(Later)** GitHub App (Phase B) short-lived tokens; decouple the use case from `ai.log_watch` (D7) and
   wire into the response-action framework.

Phases 1–4 bring GitHub **up to the log-source bar** (generalized seam + CRUD + UI); 5 proves it live; 6–7
generalize. Build only 1–5 now.
