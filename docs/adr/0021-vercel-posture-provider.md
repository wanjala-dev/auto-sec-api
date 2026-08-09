# ADR 0021 — Vercel posture scanning via Prowler's `vercel` provider: `PostureProvider` as a first-class value object, so the second posture provider lands without corrupting the asset-graph spine

Status: Proposed (2026-08-08) — **design only; build deferred** until Henry's go per phase, and
sequenced behind the standing "harden the core loops for Tom's real use" priority.

Relates to: **ADR 0004** (Finding SSOT + hub-and-spoke — the `aws:`-URN hazard this ADR exists to
prevent lives on that spine), **ADR 0006** (scanner-execution substrate — the ephemeral hardened
K8s Job the Vercel scan runs in, unchanged), **ADR 0010** (multi-provider `VcsPort` — the
token-shaped-connection + registry template `VercelConnection` copies, and the commit-SHA join P2
exploits), **ADR 0013** (contextual risk — the down-rank lane for CVE-2025-29927), **ADR 0016**
(delivery — `ScanCompleted` stays the one digest signal per scan), **ADR 0019** (SAST pillar — the
scan-gate/cooldown contract this ADR reuses for teams, and the deployment-webhook trigger P2
reuses), and the **feasibility pass** this ADR hardens:
`_session-artifacts-2026-08-08/vercel-integration-feasibility.md` (2026-08-08 — posture yes, logs
no; the "one-word change" story is false). Pricing interaction: 
`docs/product/PRICING_PACKAGING_RECOMMENDATION_2026-08-08.md` (meter on connected estate).

## Context

### Henry's ask

The feasibility pass concluded: build Vercel **posture + estate enumeration**, do **not** build
Vercel log ingestion (no `logs` integration scope exists; Drains are Pro/Enterprise-gated at
$0.50/GB on the customer's bill; and drain payloads are attacker-authored strings feeding the AI
pipeline — a hard prompt-injection gate). Henry's reaction: *"I didn't know about this, I think
this is great — can you write an ADR for this? Let's dig into this a bit more before action."*

So this ADR is the deeper grounding pass: it re-verifies the feasibility doc's load-bearing claims
(one of them turns out **wrong in our favor** — R2), decides the architecture as D-numbered
decisions, and stops. Nothing is built.

### This is customer-driven work, anchored to a named buyer

**Isaac — the first real buyer signal in the outreach tracker (~60 AI agents in production, Stripe
card data in play, no security team) — is confirmed on Vercel** (outreach tracker; Henry's
confirmation 2026-08-09). Henry's bar, verbatim: *"at minimum, making sure that the Vercel Prowler
scanner is working should just be good enough."*

That answers the queue question this ADR would otherwise have left open: Vercel posture is not a
speculative pillar-dimension bet — it is the shortest path to scanning a named prospect's real
production estate. The phasing (below) is shaped so the **earliest shippable phase IS Henry's
minimum bar**: a working Prowler `vercel` posture scan producing findings in the SSOT. Everything
richer (estate graph, joins, OAuth) queues behind it.

### Why this matters more than "a 17th integration"

1. **Our ICP ships on Vercel — and the first buyer-signal prospect does, confirmed.** The
   AI-era-builder ICP (Tom's framing: "the security team you don't hire") deploys Next.js on
   Vercel far more often than it runs EKS. For Isaac, a Vercel team **is** the production estate —
   and today we can say nothing about it.
2. **The April 2026 Vercel incident made this a live wound.** Vercel's own bulletin told customers
   to rotate env vars after an attacker could "enumerate and decrypt non-sensitive environment
   variables" (R6). Prowler shipped a `vercel` provider and wrote the playbook against that exact
   breach class (R1). The demand window is open and named.
3. **Wiz validated the graph framing** with its own Vercel integration (2026-04-09, R7) — Vercel
   projects/domains/teams as graph nodes correlated with cloud + code. That is our exposure-anchored
   moat replayed on a new surface; the difference is we *generate* the posture scan first-party.
4. **It is a provider dimension, not a new pillar.** Prowler already runs behind `ScannerPort` as a
   pinned official image (ADR 0006). Vercel posture is the *second value* of an axis
   (`cloud_posture` × provider) that today is hardcoded to its first value. That is exactly the
   "adding the Nth of something — re-examine the 1st" trigger (`improve-dont-replicate.md`).

### The trap this ADR exists to name: the "one word" shortcut corrupts the spine

The tempting story is that `prowler aws …` → `prowler vercel …` is a one-word change. **It is
false, and the failure mode is not a broken scan — it is a silently poisoned asset graph.** The
feasibility pass verified five hardcoded AWS assumptions (all re-verified for this ADR,
2026-08-08):

| # | Blocker | Evidence |
|---|---|---|
| 1 | Target validation is AWS-only | `components/cloud_posture/domain/aws_scan_target.py:15` — `_ACCOUNT_RE = ^\d{12}$` rejects a Vercel team id before any scan runs |
| 2 | **The asset-URN scheme is hardcoded** | `components/cloud_posture/infrastructure/services/prowler_ingest_service.py:214` — `asset_urn=AssetUrn.canonical("aws", resource_ref).value` |
| 3 | Source string hardcoded twice | `prowler_ingest_service.py:212` (`NormalizedFinding.source`) and `:176` (`ScanCompleted.source`), plus `ScanJobSpec(source="cloud_posture.prowler")` at `prowler_scanner.py:87` |
| 4 | Identity keys are AWS-shaped | fingerprint `f"{check_id}\|{account_id}\|{resource_uid}"` (`:213`); attributes carry `account_id`/`region` (`:222-223`) |
| 5 | Credential vending is AWS-only | `prowler_scanner.py:138-148` emits only `AWS_*` env vars |

Blocker 2 is the dangerous one. `AssetUrn` is the cross-pillar correlation key (ADR 0004 D4) — a
Vercel finding entering the SSOT wearing an `aws:`-namespaced URN would corrupt dedupe, graph
joins, and attack-path correlation on the exact spine the product wedge rests on. The shortcut
would not fail loudly; it would succeed and lie. Hence D1: the provider becomes a **value object in
the scan/ingest contract**, and the shortcut becomes structurally unwritable.

### Build sequencing (standing constraint)

Design only. Each phase awaits Henry's explicit go. The queue-position question is **answered**
(Isaac confirmed on Vercel, 2026-08-09 — this is customer-driven work with a named buyer); what
remains open is only the per-phase go and the small set of Isaac-facing questions in OQ1.

## Research grounding (claim → source, fetched 2026-08-08 unless noted)

| # | Claim | Source |
|---|---|---|
| R1 | **Prowler ships a first-class `vercel` provider: 26 checks across 6 services** — Authentication (2: stale ≥90-day tokens, expired/expiring tokens), Deployment (1: production deploys from feature branches), Domain (3: DNS misconfig, invalid/missing SSL, unverified domains), Project (10: plaintext secrets, prod env vars leaking to preview, deployment protection off, directory listing, fork protection off, skew protection off, auto-exposed system vars, over-broad env-var targeting), Security/firewall (5: WAF off, managed rulesets off, no rate limiting, no IP blocking, no custom rules), Team (5: SAML SSO absent/unenforced, owner over-privilege, stale invitations, no directory sync). | Prowler blog (2026-04-26)[^prowler-blog]; Prowler docs, "Getting started — Vercel"[^prowler-gs]; provider source[^prowler-src] |
| R2 | **Our pinned image ALREADY contains the provider.** `toniblyx/prowler:5.36.0@sha256:d37ab7…` (`prowler_scanner.py:46-50`); the `prowler/providers/vercel/` tree (exceptions/, lib/, services/, `vercel_provider.py`, `models.py`) **exists at the `5.36.0` tag** — verified against the tag tree, not `master`. Timeline: provider public by 2026-04-26 (blog); Vercel joined cross-provider CIS Controls 8.1 in **5.34.0 (2026-07-15)**; our pin is 5.36.0 (2026-07-24). **The feasibility doc's G0 fear ("our pin predates that claim") is resolved: no version bump, no digest re-pin, no supply-chain change needed for P0.** | GitHub tag tree `5.36.0/prowler/providers/vercel`[^prowler-tag]; releases page[^prowler-rel] |
| R3 | **Prowler's Vercel auth is a bearer API token**: `VERCEL_TOKEN` env var (or `api_token` arg) + optional `VERCEL_TEAM` (team id or slug); credentials validated against `GET /v2/user` (401 invalid / 403 insufficient / 429 rate-limited); **no team specified ⇒ auto-discovers every team the user belongs to and scans each**. Docs: the token creator needs "at least a Viewer role on the team to be scanned", and expiration is configurable ("or select 'No expiration' for continuous scanning"). | `vercel_provider.py` (master)[^prowler-src]; Prowler docs, Vercel authentication[^prowler-auth] |
| R4 | **Prowler degrades gracefully by plan and permission**: "11 checks have explicit billing-plan handling" (password protection, production deployment protection, SAML SSO etc. don't exist on Hobby), and the **5 firewall checks "return `MANUAL` when the firewall configuration endpoint is not accessible"** — i.e. reduced-privilege tokens produce honest partial coverage, not crashes. | Prowler docs, "Getting started — Vercel"[^prowler-gs] |
| R5 | **Vercel's integration-scope model** (per the feasibility doc's fetches of Vercel docs, upd. 2026-07-29): twelve scopes (`deployment`, `project`, `project-env-vars`, `global-project-env-vars`, `team`, `user`, `domain`, `log-drain`, `billing`, …), each None/Read/Read-Write; **no `logs` scope and no `security`/`firewall` scope**; connectable-account OAuth exchange at `POST /v2/oauth/access_token` yields a long-lived token; adding a scope later forces re-consent by every installer. Marketplace listing needs ≥500 active installs; a "Community"-badged unlisted integration works from day one. If the installing developer leaves the team, every call returns `403 integration_configuration_disabled` and the install is deleted after 30 days. | Vercel docs via feasibility doc §2.1/§10 (fetched 2026-08-08)[^feas] |
| R6 | **The April 2026 Vercel incident** (Context.ai OAuth supply chain): attacker could "enumerate and decrypt non-sensitive environment variables"; Vercel told customers to rotate. This is the breach class Project checks 1–2 (plaintext secrets, prod-vars-in-preview) detect. | Vercel bulletin (2026-04-19/23) + Trend Micro/Varonis corroboration, via feasibility §10[^feas] |
| R7 | **CVE-2025-29927** (Next.js middleware auth bypass, CVSS 9.1, 2025-03) was **automatically mitigated for Vercel-hosted deployments** — so a "Vercel-hosted" fact in the asset graph must *down-rank* that CVE class or we ship a confident false positive. **Wiz** shipped a Vercel integration (2026-04-09) pulling projects/domains/teams/members into its Security Graph — market validation of the estate-node framing. | JFrog/ProjectDiscovery on the CVE; Wiz blog — via feasibility §5/§10[^feas] |
| R8 | **There is nothing to container-scan on the default Vercel path**: git-connected deployments expose no build output, no image, no filesystem; Vercel Container Registry (OCI) exists but only holds images on the non-default Functions-container/Sandbox path and has **no integration scope** (PAT-only). | Vercel docs (Container Registry upd. 2026-08-03) via feasibility §3/§10[^feas] |

## Decisions

### D1 — `PostureProvider` becomes a first-class value object in the `cloud_posture` domain: provider is part of the scanner/ingest/URN contract, never an implicit `"aws"`. AWS behaviour is preserved byte-for-byte, locked by tests. **[proposed]**

**What it is.** A frozen dataclass in `components/cloud_posture/domain/posture_provider.py`, one
instance per provider, registered in a small provider registry (the ADR 0008/0010 registry
template, third use):

```python
@dataclass(frozen=True)
class PostureProvider:
    token: str                      # "aws" | "vercel" — the engine argv word AND the URN namespace
    source: str                     # NormalizedFinding/ScanCompleted source string
    validate_target: Callable       # provider-shaped target/params validation (injection gate)
    credential_env: Callable        # credential envelope → engine env vars (AWS_* / VERCEL_*)
    identity_keys: Callable         # OCSF record → the fingerprint's account-shaped middle key
```

Threaded through the three seams the shortcut would have silently skipped:

- **`ProwlerScanner.scan`** takes the provider (via `ScanTarget.params["provider"]` resolved at the
  registry, defaulting to `aws`): argv becomes `prowler {provider.token} …`, `secret_env` comes
  from `provider.credential_env`, and target validation dispatches to `provider.validate_target`.
  `aws_scan_target.py` becomes the AWS entry in a provider-keyed validator registry (file renamed
  in P0a; the AWS regexes move verbatim).
- **`prowler_ingest_service._to_normalized`** builds `asset_urn=AssetUrn.canonical(provider.token,
  resource_ref)` and `fingerprint=f"{check_id}|{provider_identity}|{resource_uid}"` from
  `provider.identity_keys` — for AWS that stays exactly `account_id`; for Vercel it is the team id.
- **`ScanCompleted.source` / `NormalizedFinding.source`** come from `provider.source`.

**Where it does NOT live: the shared kernel.** The kernel carries only cross-context contracts
(`AssetUrn`, `NormalizedFinding`, `ScannerPort` — ADR 0004 C6), and it already needs no change:
`AssetUrn.canonical(source_system, ref)` takes the provider as a free string and namespaces
`urn:vercel:<ref>` today (`components/shared_kernel/domain/security.py:210-226`), and
`CloudAssetEntity.provider` is already a plain `str`
(`components/cloud_graph/domain/entities/cloud_asset_entity.py:16`). `PostureProvider` is pillar
mechanics — which argv word, which validator, which env vars — and no other context needs it.
Promoting it to the kernel would leak one pillar's engine wiring into the shared vocabulary.

**Source-string asymmetry, decided deliberately.** AWS **keeps** `source="cloud_posture.prowler"`
unchanged; Vercel gets `source="cloud_posture.prowler.vercel"`. Renaming the AWS source to
`…prowler.aws` would look tidier but the SSOT's finding identity is
`(workspace, source, fingerprint)` — a rename would orphan every existing AWS finding and re-mint
them as new (broken lifecycle, duplicate cards). Byte-for-byte preservation beats symmetry; the
asymmetry is documented at the registry definition so nobody "fixes" it later.

**How AWS is locked byte-for-byte** (the regression here corrupts the CNAPP spine, so the lock is
named, not implied):

1. A **golden-master test** in `components/cloud_posture/tests/unit/`: feed a fixture OCSF record
   through `records_to_scan_result` before and after P0a and assert the exact `source`,
   `fingerprint`, `asset_urn`, and `attributes` strings for the AWS provider (assert literal
   values, e.g. `asset_urn == "arn:aws:s3:::…"` for an ARN-bearing record and
   `"urn:aws:account/…"` for the account fallback).
2. The existing integration suites stay green unmodified:
   `components/cloud_posture/tests/integration/test_cloud_posture_scan.py` and
   `test_cloud_posture_orchestration.py`.
3. An architecture fitness test asserting the ingest service constructs URNs **only** via the
   provider registry (no string-literal `"aws"`/`"vercel"` in `_to_normalized`) — the structural
   version of "the shortcut is unwritable".

**Why this is worth doing even if Vercel is cancelled** (feasibility OQ4, adopted here as a
position): `cloud_posture` will eventually hold Azure/GCP; every future provider hits the same five
blockers. P0a removes a real inherited coupling on its own merits and ships as its own PR
(`improve-dont-replicate.md`: improve the 1st instance when adding the 2nd).

### D2 — Connection + auth: a token-shaped `VercelConnection` in `components/integrations` first (the GitHub-PAT precedent), with the connectable-account OAuth integration as a later **additive** credential kind — not a prerequisite. Least-privilege is achieved by the token-creation recipe, and the ADR corrects the feasibility doc's PAT rejection. **[proposed]**

**The feasibility doc chose OAuth-first and rejected the customer token as "a full-privilege,
no-read-only-variant ask that a security vendor cannot credibly make." Deeper grounding weakens
that rejection on three facts:**

1. **A Vercel token inherits its creator's role.** Prowler's own docs instruct: the token creator
   needs *"at least a Viewer role on the team to be scanned"* (R3). A token minted from a
   Viewer-role seat is **not** a full-privilege credential — it is read-scoped by construction.
   "No read-only token variant" is true of the token *form*, but the role system supplies the
   privilege boundary.
2. **Prowler's documented auth path IS the API token** (`VERCEL_TOKEN`, R3). An OAuth integration
   token is also a bearer token and should work for most endpoints, but the check surface under
   integration scopes is **empirically unverified** — and the scopes that don't exist
   (`security`/firewall, R5) guarantee at least the 5 firewall checks degrade to `MANUAL` (R4).
   Building the OAuth flow first means shipping our first Vercel scan on the *less*-tested
   credential shape.
3. **OAuth-first drags non-engineering calendar**: partner registration wants a logo, EULA URL,
   privacy-policy URL, 3–5 gallery images, and a public support email (R5) — go-to-market
   artifacts, some of which don't exist yet. A design-partner motion with Tom/Isaac shouldn't
   block on marketing collateral.

**Decision:** `VercelConnection` mirrors `VcsConnection` (ADR 0010) exactly:

- **Model** in `infrastructure/persistence/integrations/models.py`: workspace FK, `team_id`,
  `team_slug`, `token_ciphertext` via the ONE integrations Fernet envelope
  (`components/integrations/infrastructure/adapters/secret_envelope.py` — `@sensitive_variables`,
  decrypt failure raises loudly, same as `VcsConnection.token_ciphertext` /
  `DeliveryConnection.secret_ciphertext`). AWS stays the outlier (role-assumption, no stored
  secret); Vercel is token-shaped like GitHub/Slack.
- **`credential_kind` discriminator from day one** (`token` | `oauth_integration`), so the OAuth
  connectable integration lands later as an additive kind on the same row — the log-source
  `Kind` precedent. The OAuth build (install redirect → 30-min single-use code →
  `POST /v2/oauth/access_token` → long-lived token into the same ciphertext column) is **P4**, not
  P0, and is gated on the G0 empirical matrix showing which checks an integration-scoped token can
  actually run.
- **Connect UX / least-privilege recipe** (shown in the panel, enforced socially since the API
  can't introspect the creator's role): create the token **from a Viewer-role seat**, scoped to
  the one team, **with an expiration** (we surface expiry and nag before it lapses — Prowler's
  Authentication checks will meanwhile flag *other* stale tokens in the account, a nice mirror).
- **`verify()`**: `GET /v2/user` + team resolution (the exact calls Prowler validates with, R3);
  results recorded on the connection health fields. Two failure modes surface **loudly** (the ADR
  0008 silent-blank lesson): 401 (revoked/expired token) and — once OAuth exists —
  `403 integration_configuration_disabled` (installer left the team; the install self-deletes
  after 30 days, R5). Both are connection-health errors with notifications, never a quietly empty
  next scan.
- **Settings ▸ Integrations panel** follows the uniform provider-panel contract (a
  `PROVIDER_LABEL` map entry + an `ADDABLE_*` entry + the standard connect/verify/disconnect
  card) — the same shape the VCS and delivery panels use. No new UI primitives.
- **Audit** every connect / verify / disconnect (existing audit funnel), and never log the token,
  team member emails, or env-var *values* anywhere (`logging.md` §4).

**Env-var scope discipline** (carried from feasibility §6, still binding): whichever credential
kind is in play, we never call `GET /v10/projects/{id}/env` with `decrypt=true`, and if/when the
OAuth kind lands we do **not** request `global-project-env-vars`. Prowler's env-var checks read
key/type/target metadata — plaintext values are never needed for posture.

### D3 — Execution: the same ephemeral hardened K8s Job behind `ScannerPort`, pinned digest **unchanged** (R2), with a Vercel-shaped target validator, `VERCEL_*` secret env, an api.vercel.com egress policy, and the existing scan-gate cooldown contract applied per team. **[proposed]**

- **No new substrate.** `ProwlerScanner` composes the same `ScanJobSpec` (ADR 0006: gVisor where
  available, read-only rootfs, non-root, resource limits, `activeDeadlineSeconds`); the script
  becomes `prowler {provider.token} --output-formats json-ocsf --output-directory /tmp …; cat` —
  the OCSF-file-to-stdout dance is provider-agnostic.
- **Pin:** stays `toniblyx/prowler:5.36.0@sha256:d37ab7…` — verified to contain the provider (R2).
  No bump, no re-pin, no AWS regression run forced by this ADR. (When the pin next bumps for other
  reasons, the golden-master test from D1 is the AWS regression gate.)
- **Target validation (the injection gate, Vercel edition):** the provider registry's
  `validate_target` for Vercel admits only well-formed team ids (`^team_[A-Za-z0-9]{1,64}$`) and
  conservative slugs (`^[a-z0-9][a-z0-9-]{0,62}$`), and project filters if we pass `--project`.
  Same rule as `aws_scan_target.py`: only strictly-validated tokens ever reach the interpolated
  command. The team id is also the label on ingested findings (the AWS `account_id` analog).
- **Secrets:** `secret_env={"VERCEL_TOKEN": …, "VERCEL_TEAM": …}` (R3) — decrypted from the
  connection at dispatch, env-only (never argv), never logged. We **always** set `VERCEL_TEAM` to
  the connection's team: Prowler's no-team auto-discovery (scan *every* team the user belongs to,
  R3) is a consent violation in our model — the connection names one team; we scan exactly it.
- **Network:** the scan-Job NetworkPolicy for Vercel allows egress **only** to `api.vercel.com` +
  DNS (the Trivy egress-allowlist shape). The AWS scan Job's egress needs differ — the policy is
  per-provider, resolved from the same registry.
- **Memory:** do **not** inherit the AWS 4Gi bump. `_PROWLER_MEM` exists because a full AWS
  account's findings accumulate in-memory across regions; a Vercel team is orders of magnitude
  smaller (26 checks × projects). The backend's 2Gi default suffices; the provider registry
  carries the override only for AWS. (Cheap, but it halves the per-scan footprint and keeps the
  Job schedulable on a busy node.)
- **Cadence + cooldown (the #261/#263 analog, decided):** Vercel scans go through the existing
  scanning gate — `check_and_lock_dispatch(workspace_id, source="cloud_posture.prowler.vercel",
  target_ref=<team_id>, cooldown_seconds=…)`
  (`components/scanning/application/providers/scan_gate_provider.py`) — one in-flight scan per
  team, one completed scan per cooldown window, failed scans don't start a cooldown, manual
  re-scan surfaces `retry_after`. Triggers mirror AWS CSPM: **on-connect** initial scan (the
  onboarding "it found things in *my* account" moment) + the **beat cycle**
  (`schedule_prowler_runs`-style fan-out, weekly on Free / continuous-tier cadence per the pricing
  doc). The `deployment.succeeded` webhook trigger is P2 (it belongs to the join story, and drags
  webhook signature verification with it).
- **Failure posture:** identical to AWS — a Job that dies leaves no complete OCSF file, `cat`
  fails, `result.ok` is False, the scanner **raises** (`prowler_scanner.py:105-117`); a crashed
  scan is a failed scan, never a clean-looking empty one.

### D4 — Findings + graph: same OCSF→SSOT path with `urn:vercel:` URNs and team-keyed fingerprints; estate nodes (team/project/domain) enter `cloud_graph` in **P1, not P0** — posture ships first, honestly, without graph nodes; contextual risk gains the CVE-2025-29927 down-rank as its own cheap phase. **[proposed]**

- **Normalization:** Vercel OCSF records flow through the existing `parse_prowler_ocsf` →
  `_to_normalized` path with the D1 provider threaded: `source="cloud_posture.prowler.vercel"`,
  `fingerprint=f"{check_id}|{team_id}|{resource_uid}"`,
  `asset_urn=AssetUrn.canonical("vercel", resource_ref)` → `urn:vercel:<project-or-resource-id>`
  (Vercel ids are already team-unique; the URN namespace makes them globally so). `attributes`
  carry `team_id`, `project_id`/`project_name`, and `check_id` — the AWS `region` key is simply
  absent, not faked. **G0 captures a real Vercel OCSF sample** to confirm field placement
  (`cloud.account.uid` = team id, resource shapes) before the parser mapping is finalized — the
  parser is defensive, but the fingerprint's identity keys must be *verified*, not assumed
  (`verify-dont-guess.md`).
- **Board + triage:** the proven ~1-day seam, fifth use — a `_SOURCE_BOARD` entry for
  `cloud_posture.prowler.vercel` (card copy leads with check + project), `ROUTABLE_SOURCE_TYPES`
  routing + a triage tool in the same phase ("routable without a tool is a silent no-op"), and
  the severity floor per ADR 0019 D4's noise posture.
- **Which findings feed contextual risk (ADR 0013):** the exposure-anchored ones — plaintext
  secrets (`project_environment_no_secrets_in_plain_type`), prod-vars-reachable-from-preview
  (+ fork protection off — the R6 breach class), deployment protection off on production, and the
  Team SSO checks. Domain/DNS checks are hygiene-tier (board floor applies).
- **Graph nodes ship in P1, deliberately not P0.** Honest sequencing: P0's findings already carry
  correct `urn:vercel:` URNs, so when the nodes land the correlation joins **by value** with zero
  backfill (ADR 0004 D4 — identity by URN, never FK). P1 then enumerates teams / projects /
  domains / deployments as `CloudAssetEntity` rows: `provider="vercel"`, `arn`=the same
  `urn:vercel:` value (the field name is fork-drift; it holds the globally-unique id),
  `asset_urn`=ditto, `resource_type` ∈ `vercel_team|vercel_project|vercel_domain|vercel_deployment`,
  and **exposure semantics decided as**: a project with a live production domain and deployment
  protection disabled is `PUBLIC`; with deployment protection enabled, `INTERNAL`; no production
  deployment, `PRIVATE` (`Exposure.from_value` default). Env-var enumeration stores **keys + types
  only, never values**. Edges (project→domain, project→deployment, member→team) reuse existing
  relation semantics where they fit; no new edge types are minted in P1 without a named query that
  needs them.
- **The three flagship findings** (refined from feasibility §5, honest framing kept): (1) HIGH —
  production secret reachable from fork previews (plaintext type + preview scope + fork protection
  off; **genuinely Vercel-only**; fix is a Response Action, not a PR); (2) CRITICAL —
  `NEXT_PUBLIC_*`-inlined server secret live in the public bundle (**SAST detects, Vercel
  confirms it is live on the real domain** — exposure-anchored, never claimed as Vercel-found);
  (3) HIGH — committed `VERCEL_AUTOMATION_BYPASS_SECRET` defeating deployment protection (GitHub
  secret-scanning detects; Vercel contributes the "this is the only thing between previews and
  the internet" sentence). #2/#3 are **P2** (they need the commit-SHA join to the `VcsPort`
  estate); #1 falls out of P0's checks directly.
- **CVE-2025-29927 down-rank (P1.5):** once the graph knows an app is Vercel-hosted, the
  contextual-risk layer down-ranks that CVE class (auto-mitigated on Vercel hosting, R7).
  Removing a confident false critical is worth more to a solo founder than 26 new checks — the
  cheapest high-value item in the plan.

### D5 — Explicitly OUT of scope, with named re-entry conditions. **[proposed]**

| Out | Why | Revisit when — ALL conditions, not any |
|---|---|---|
| **Log ingestion (drains)** | No `logs` integration scope exists (runtime-logs 403s even with every scope granted); drains are Pro/Enterprise-only at $0.50/GB **on the customer's bill**; drain payloads (`proxy.path`, `userAgent`, `message`) are **attacker-authored strings entering the AI triage pipeline** — the first ingest source where an unauthenticated internet client writes the LLM's input (R5, feasibility §6) | (a) a **paying** customer on Pro+ asks for it, **and** (b) the injection-fence test exists and passes — a payload fed receiver→finding→triage proving the grounding fences hold, **and** (c) the `process_records()` extraction + workspace-keyed ingest + nullable-connection rollup FKs have landed as their own PRs (feasibility §4.4's four blockers), **and** (d) per-source byte/rate caps + `clientIp`/JA3 retention-purge are designed (denial-of-wallet + PII) |
| **Container scanning of Vercel workloads** | There is no artifact: git-connected deployments expose no image/filesystem; VCR is non-default-path and PAT-only (R8). **Say this plainly in marketing** — claiming coverage here is the kind of thing an operator catches in five minutes | Vercel ships an integration scope for VCR, or a customer on the Functions-container path materializes |
| **Marketplace listing** | Needs ≥500 active installs + review (R5); the token path (and later the unlisted Community-badge OAuth integration) works from day one | A distribution push makes 500 installs plausible — a later GTM question, not an engineering one |
| **WAF posture beyond Prowler's `MANUAL`** | No `security`/firewall integration scope exists (R5); under a reduced-privilege token the 5 firewall checks return `MANUAL` (R4) — honest partial coverage, surfaced as such | Vercel ships a firewall read scope |
| **Hobby-tier posture promises** | 11 of 26 checks have explicit billing-plan handling (R4) — password protection, SAML SSO etc. don't exist on Hobby; findings there would be "upgrade your Vercel plan" nags | Never "fixed" — handled by honest per-plan reporting from day one |

### D6 — The pillar ships **dark** behind `feature.vercel_posture`, un-darkened per workspace — the `code_security` pattern, applied from day one. **[proposed]**

Standing rule from Henry (2026-08-09): in-progress capability ships behind a flag and is enabled
per workspace, never globally-on at birth.

- **Flag key:** `feature.vercel_posture` — a sibling of `feature.cloud_posture`, not a re-use of
  it: the AWS pillar's flag must not implicitly grant a second provider (a workspace opted into
  AWS CSPM has not consented to a Vercel scan surface), and gating them separately keeps the
  pricing mapping (§OQ2) free to place them independently.
- **Seeded dark:** registered in `seed_feature_flags` and included in `PROD_DISABLED_FLAGS`, same
  as the scanner flags before it — globally disabled in prod, enabled by an operator per workspace
  (Isaac's, ours for dogfood). Fail closed: every gate checks the flag and treats "missing" as
  off, mirroring `_is_cloudwatch_enabled`'s posture.
- **Where the gate sits:** (a) the Settings ▸ Integrations panel entry renders only when the flag
  is on (no connect surface, no dark-launch confusion); (b) `enqueue`/beat fan-out skips
  non-flagged workspaces (no scan Jobs run dark); (c) the on-demand scan endpoint 403s without the
  flag. Findings ingest needs no separate gate — no scan, no findings.
- **Tier mapping later:** the flag joins `tier_features.py` only when OQ2 is decided; until then it
  is an operator switch, not an entitlement (the ADR 0020 distinction).

## Consequences

**Positive:** a second posture provider at provider-dimension cost — engine, substrate, SSOT,
board, triage, delivery, and graph are all reuse; the net-new surface is a value object, a
connection model, a validator, and a normalizer mapping. P0a removes a real inherited AWS coupling
that Azure/GCP would have hit anyway. The pin already contains the provider (R2), deleting the
supply-chain work item the feasibility pass budgeted. The demand story is dated and named (R6),
and the market framing is validated by Wiz (R7).

**Negative / costs:** a second credential *shape* in the AWS-role-dominated integrations story
(token expiry becomes an operational surface — mitigated by verify() + expiry nagging); Prowler's
Vercel checks are young (introduced ~2026-04) and their OCSF field placement is verified only by
G0's empirical capture, not by years of production use; check coverage varies by the customer's
Vercel plan (R4) — reporting must carry the "MANUAL/not-on-your-plan" nuance honestly or the
product looks broken on Hobby accounts; and the source-string asymmetry (D1) is a permanent small
wart, chosen deliberately over an SSOT identity migration.

## Non-goals

- **Not a new bounded context and not a new pillar** — `cloud_posture` gains a provider dimension;
  `ScannerPort`, the Job substrate, and the SSOT pipeline are untouched as contracts.
- **No Vercel log ingestion, no drain receiver, no push seam** in any phase of this ADR (D5).
- **No `decrypt=true` env-var reads, ever** — posture needs key/type/target metadata only (D2).
- **No auto-discovery scans across every team the token can see** — the connection names one team;
  consent is per-team (D3).
- **No Response Actions against Vercel config in this ADR** — re-scope env var / regenerate bypass
  secret land with the response-action framework's Vercel adapter later (feasibility P4), after
  posture is proven.

## Phased build plan (each phase awaits Henry's go — standing rule)

**The earliest shippable phase IS Henry's minimum bar** — *"making sure that the Vercel Prowler
scanner is working should just be good enough"* — i.e. **P0 = connection + token + scan Job +
findings in the SSOT**, flag-gated (D6). Nothing richer sits ahead of it: P0a (the
`PostureProvider` refactor) is not front-loading — it is the load-bearing prerequisite *inside*
P0, because without it the scan physically cannot produce correctly-URN'd findings (the `aws:`
corruption trap, D1). Estate graph, down-rank, joins, and OAuth all queue behind the working scan.

**G0 — half a day, zero code, before P0 is scheduled:**
(a) ~~verify the pin contains the provider~~ — **done in this ADR (R2), no bump needed**;
(b) ~~is Isaac on Vercel?~~ — **confirmed (2026-08-09)**;
(c) the **empirical check matrix**: run `prowler vercel` (the pinned image, `VERCEL_TOKEN` from a
Viewer-role token) against our own Vercel team; capture the OCSF file; record which of the 26
checks PASS/FAIL/MANUAL/ERROR under (i) a Viewer token and — if cheap to mint — (ii) an
integration-scoped token; confirm OCSF field placement for the D4 identity keys;
(d) the three remaining **Isaac questions** (OQ1).

| Phase | Scope | Effort |
|---|---|---|
| **P0 — the minimum bar: a working Vercel Prowler scan → findings in the SSOT** (two internal steps, one deliverable) | **P0a** — D1 in full: `PostureProvider` value object + registry, validator registry (AWS regexes move verbatim), threaded scanner/ingest, golden-master + fitness tests; AWS byte-identical. **P0b** — D2 token-shaped `VercelConnection` + verify() + Settings panel entry (flag-gated, D6); D3 validator/env/egress/gate wiring; D4 normalization + board/triage seam entry; `feature.vercel_posture` seeded dark. Exit criterion: a real scan of a real team produces correctly-URN'd findings on the board (flagship finding #1 class included). **Validation moment: Isaac's team, with his consent (OQ1c).** | ~4–5 days + ~3 days |
| **P1 — estate enumeration** | Teams/projects/domains/deployments as graph nodes with the D4 exposure semantics; env-var keys+types; HUD estate surfacing. | ~3 days |
| **P1.5 — CVE-2025-29927 down-rank** | Vercel-hosted ⇒ down-rank the auto-mitigated class in contextual risk. | ~1 day |
| **P2 — the join findings** | Commit-SHA correlation of Vercel deployments ↔ `VcsConnection` repos; `deployment.succeeded` webhook (signature-verified) firing the SAST pillar; flagship findings #2/#3. | ~3 days |
| **P4 — OAuth connectable integration** *(deliberately after P2)* | The `oauth_integration` credential kind: install redirect + code exchange + partner assets (logo/EULA/privacy/gallery — GTM work, parallel-trackable); gated on G0's integration-token matrix. | ~3 days eng + GTM assets |

**Recommended cut: G0 → P0 → P1 → P1.5 → P2 ≈ 2.5–3 weeks of eng — but P0 alone (~1.5 weeks)
satisfies the named buyer's bar** and is a clean stopping point if Isaac's engagement dictates
pace. The total *confirms* the feasibility doc's ~3-week estimate but re-derives it: G0 shrank
(the pin is fine R2; the "is he on Vercel" question is answered) and P0b shrank (token-first, no
OAuth flow), which absorbs the slack the feasibility pass had under-budgeted for the join work and
the per-plan reporting nuance. P4 is additive and optional until a design partner objects to
pasting a token.

## Open questions (for Henry)

1. **The three remaining Isaac questions** (the "is he on Vercel" question is answered —
   confirmed 2026-08-09):
   (a) **Plan tier** (Hobby/Pro/Enterprise) — matters *only* for the out-of-scope drains
   discussion (D5's re-entry conditions) and for how many of the 11 plan-gated checks will read
   as "not on your plan"; it does not gate P0.
   (b) **Team vs personal account** — a personal (Hobby) install has `team_id: null` semantics;
   the connection model and the `VERCEL_TEAM` pinning (D3) assume a team, so a personal account
   needs the personal-scope branch exercised in G0's matrix.
   (c) **Consent to run a read-only posture scan against his real team as the validation
   moment** — P0's exit criterion is his estate, with his explicit yes (Viewer-role token, the
   D2 recipe).
2. **Pricing placement.** The merged pricing doc meters on **connected estate** — cloud accounts,
   repos, images. Is a Vercel team a "cloud account" unit (Free: 1 account total across
   providers, weekly; Pro: 3 accounts, +$79/extra) — or a separate cheaper unit (a Vercel team
   costs us a 2Gi/~minutes Job, far less than an AWS sweep)? Proposal: count it as a cloud
   account for simplicity at launch, with `feature.vercel_posture` (D6) joining `tier_features.py`
   when this is decided; revisit if it suppresses connects.
3. **Token-first vs OAuth-first (D2).** This ADR reverses the feasibility doc's OAuth-first on
   the Viewer-role-inheritance fact + Prowler's documented auth path + partner-asset drag. Are
   you comfortable asking a design partner for a Viewer-scoped, expiring token in the interim, or
   is the OAuth optics bar absolute (in which case P4 moves before P0b and the estimate grows)?
4. **`VERCEL_TEAM` consent stance.** D3 always pins the scan to the connection's team and rejects
   the auto-discover-all-teams default. Any case for an "org mode" that enumerates all teams
   (AWS-organization-style) with explicit multi-team consent later?
5. **P0a even on a Vercel no-go?** Position taken in D1: yes, it ships on its own merits as the
   Azure/GCP pre-work. Confirm so it can be scheduled independently.
6. **Per-plan honesty surface.** Where does "11 checks don't apply on your Vercel plan / 5 are
   MANUAL under this token" render — the scan snapshot detail only, or a per-connection coverage
   badge in Settings? (Cheap either way; it's a product-voice call.)

[^prowler-blog]: Prowler blog, "Secure your Vercel apps with Prowler: lessons from the April 2026 breach" (2026-04-26 — the 26-check/6-service enumeration): https://prowler.com/blog/secure-vercel-apps-prowler-april-2026-breach
[^prowler-gs]: Prowler docs, "Getting started — Vercel" (fetched 2026-08-08 — `prowler vercel`, `VERCEL_TOKEN`/`VERCEL_TEAM`, auto-discovery, 26 checks, 11 with billing-plan handling, 5 firewall checks → `MANUAL` without firewall API access): https://docs.prowler.com/user-guide/providers/vercel/getting-started-vercel
[^prowler-auth]: Prowler docs, Vercel authentication (fetched 2026-08-08 — API-token auth; creator needs ≥ Viewer role on the target team; expiration configurable): https://docs.prowler.com/user-guide/providers/vercel/authentication
[^prowler-src]: Prowler source, `prowler/providers/vercel/vercel_provider.py` (master, read 2026-08-08 — `VERCEL_TOKEN`/`VERCEL_TEAM` env vars, `/v2/user` validation w/ 401/403/429 handling, `/v2/teams` auto-discovery): https://github.com/prowler-cloud/prowler/tree/master/prowler/providers/vercel
[^prowler-tag]: Prowler repo at tag **5.36.0**, `prowler/providers/vercel/` (verified present 2026-08-08 — exceptions/, lib/, services/, `models.py`, `vercel_provider.py`): https://github.com/prowler-cloud/prowler/tree/5.36.0/prowler/providers/vercel
[^prowler-rel]: Prowler releases (fetched 2026-08-08 — 5.34.0 2026-07-15 adds Vercel to cross-provider CIS Controls 8.1; 5.36.0 2026-07-24 = our pin; latest 5.38.0 2026-08-06): https://github.com/prowler-cloud/prowler/releases
[^feas]: Vercel integration feasibility + design pass (2026-08-08 — session artifact; its §10 carries the dated Vercel-docs fetches for scopes/drains/limits/VCR, the April-2026 incident sources, CVE-2025-29927 sources, and the Wiz integration): `_session-artifacts-2026-08-08/vercel-integration-feasibility.md`
