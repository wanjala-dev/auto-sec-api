# Triage Agent → Draft PRs: GitHub Integration + Agent Capability Settings

**Status:** researched design, not built. Prompted by Henry (2026-07-19): the triage agent
finds issues and recommends fixes from logs — give it the power to push a **draft PR**, gated
by **settings on agents**.

## 1. How the field does it (research, 2026)

- **[Sentry Seer / Autofix](https://docs.sentry.io/product/ai-in-sentry/seer/autofix/)** is the
  canonical shape and validates the whole idea: production telemetry → root-cause analysis →
  generated code fix → **PR created via an installed GitHub App** (installing the Seer
  GitHub/GitLab app is a hard requirement). At the fix step, Seer can alternatively **hand off
  to an external coding agent** — Claude Code, Cursor Cloud Agents, or GitHub Copilot — instead
  of writing the patch itself.
- **[GitHub Copilot agentic autofix](https://byteiota.com/github-copilot-agentic-autofix-verified-fixes-auto-pr/)**
  (public preview 2026-07-14): assign `copilot-swe-agent[bot]` to a code-scanning alert via API
  and it produces a verified fix PR — i.e. GitHub itself now exposes "file an alert → get a fix
  PR" as a platform primitive we can trigger.
- **Integration mechanics** ([GitHub docs](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens)):
  the standard is a **GitHub App** with fine-grained permissions — `contents: write` +
  `pull_requests: write` + `metadata: read`, nothing else. Installation access tokens are
  **short-lived and minted per operation**, and can be **scoped to specific repos at mint
  time**. The customer installing the app on chosen repos IS the consent boundary. PRs are
  authored by the app bot (`auto-sec[bot]`) — clean attribution, no human's token at risk.
  (v1 shortcut: a fine-grained PAT with the same two scopes, stored encrypted.)

**Answer to "would this require GitHub integrations?" — yes**, and the industry-standard form
is a GitHub App the workspace installs, not tokens pasted into a form (that's the v1 stopgap).

## 2. Where it lands in OUR architecture (almost every seam already exists)

| Piece | Lands on | Status |
|---|---|---|
| GitHub connection | `GitHubConnection` model in `infrastructure/persistence/integrations/` — mirrors `AwsOrganizationConnection` (workspace-scoped, status, **repo allowlist**, install/app ids; PAT v1 stored via the `SinkConnector` encryption envelope) | new model, established pattern |
| Agent settings | `Agent.config["capabilities"]["open_draft_pr"]` — per-workspace agent row; settings UI toggle on the agent | `Agent.config` exists; toggle UI is new |
| The tool | `open_draft_pr` on `triage_agent`, wrapped by the **risk gate** (`_risk_gated`, SEE-203) | tool new; gate exists — `triage_finding`'s docstring predicted exactly this |
| Autonomy gating | risk tier + capability check + **grounded-verifier precondition** (a `needs_human` finding NEVER auto-PRs) | verifier shipped |
| Verification | RubricMiddleware / critic grades the patch (rubric gains: "patch touches only files implicated by the evidence; references the failing symbol") | loop shipped |
| Audit | provenance event (`agent:triage_agent → opened draft PR <url>`) + PR link on the finding card | provenance shipped |
| Identity | the GitHub App installation IS the on-behalf-of service principal (§17 P0-3) | closes an open governance gap |

## 3. The risk-tier decision (the interesting design call)

A **draft PR on a bot branch** never touches `main`, can't merge itself, and is fully closable —
arguably `REVERSIBLE_WRITE`. But we ship the **stricter posture first and let the agent EARN
promotion** (the risk-ladder's earned-promotion rung, and the right optics for a SOC product):

- **Rung 1 (ship first):** `open_draft_pr` = `IRREVERSIBLE` → autonomous runs can *prepare* the
  patch (attached to the finding as an artifact) but the PR push pauses for **HITL approval**
  (existing pause/approve flow). Operator clicks approve → PR opens.
- **Rung 2 (earned):** after N clean approved PRs for a workspace, the operator may flip the
  capability to autonomous (`REVERSIBLE_WRITE`) in agent settings — drafts open unprompted;
  **merge remains human forever**, at every rung, non-negotiable.

Plus hard preconditions at every rung: capability enabled per agent · grounded verifier passed ·
target repo in the connection's allowlist · finding not `needs_human`.

## 4. Where the FIX comes from (two generations)

- **v1 — API-only patch, no sandbox:** for the small fixes the triage agent already nails
  (missing export, config value, requirements pin), create branch + commit + draft PR purely via
  the GitHub contents API — no clone, no code execution, respects the §17 sandbox boundary (an
  agent writing arbitrary code in-process is a hard no).
- **v2 — coding-agent handoff (Sentry's model):** for real multi-file fixes, hand the finding's
  evidence + suggested fix to a coding agent — trigger **GitHub Copilot agentic autofix** via
  the alert API, or a Claude Code session — and let IT produce the PR. The triage agent stays a
  *dispatcher with evidence*, which is what it's good at; the sandbox problem is outsourced to
  platforms built for it.

## 5. Pipeline fit (end-to-end)

```
detector → router → triage worker (deep pipeline)
   → advisor (fix suggestion) → grounded verifier (evidence check)
   → [capability on? repo allowed? not needs_human?]
   → open_draft_pr (risk-gated: HITL at rung 1)
   → PR URL → finding payload + provenance + card comment (HUD chip: "DRAFT PR ↗")
   → L4 signal: merged = positive, closed-unmerged = negative → hill-climbing input
```

That last line matters: PR outcomes are the first **ground-truth reward signal** the
self-improvement loop gets for free.

## 6. Build sequence

- **Phase A (dogfood):** `GitHubConnection` (PAT v1, encrypted) + agent-capability setting +
  settings UI toggle + `open_draft_pr` (rung 1, API-only patch) pointed at OUR repos —
  auto-sec's own log findings become draft PRs on `auto-sec-api`.
- **Phase B (product):** proper GitHub App (`auto-sec[bot]`), customer installs on chosen
  repos — mirrors the AWS role-assumption onboarding; repo allowlist + short-lived tokens.
- **Phase C:** coding-agent handoff for multi-file fixes; earned-promotion rung 2.
