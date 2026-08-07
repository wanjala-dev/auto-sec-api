# ADR 0019 — Code scanning (SAST) as a scanner pillar: connected-repo bug/vulnerability findings feeding the existing triage → draft-PR remediation loop, with snippet preview

Status: Proposed (2026-08-07) — **design only; build deferred** until Henry's go per phase.

Relates to: **ADR 0004** (Finding SSOT + hub-and-spoke — this pillar is a spoke-in behind the ONE
`ScannerPort`), **ADR 0006** (scanner-execution substrate — the ephemeral hardened K8s Job every
engine runs in; Trivy is the worked example this pillar copies), **ADR 0010** (`VcsPort` /
`VcsConnection` / `repo_allowlist` — the connected-repo consent boundary and the credential this
pillar reads code through), **ADR 0017** (universal code remediation — the fix engine this pillar's
findings feed; its `CodeLocationResolverPort` is where a SAST finding becomes the *easiest*
remediation class), **ADR 0012** (Remediation Memory — every merged SAST fix compounds per-tenant),
**ADR 0013** (contextual risk — the re-rank that keeps this pillar from becoming a wall of
findings), **ADR 0008 / 0016** (the port + per-workspace-config + registry template), and the
operator feedback that shapes the noise posture (William: *"single actionable digest, not a wall of
findings"*; Tom: harden the connect→scan→draft-PR loops for real use).

## Context

### Henry's ask

Verbatim-ish: *"scan the codebase, find bugs/vulnerabilities, push a draft PR, and preview the
snippet code."* I.e. the front of the funnel is a real code scanner over the customer's connected
repos; the back of the funnel is the draft-PR remediation loop we already run; and the operator
sees the offending code (and the proposed fix) as a rendered snippet, in the HUD.

### Why now: the whole back half already exists and is proven live

This is the rare feature where the *hard* 80% is already built, shipped, and dogfood-proven:

- **VCS connect + consent** — `VcsConnection` + `repo_allowlist` + verify, with CRUD and a
  Settings panel (ADR 0010). A repo not allowlisted is rejected before any API call.
- **The draft-PR engine** — `OpenDraftPrUseCase` (ordered gates → `create_branch` /
  `commit_file` / `open_draft_pr` through `VcsPort`), proven end-to-end on a real grounded dogfood
  draft PR (2026-08-04). ADR 0017 D0 locks it as the ONE engine.
- **Advisor + guardrails** — the grounded advisor with deterministic patch validation
  (`validate_patch`: parse / no-symbol-drop / not-too-destructive, fail closed), being generalized
  into `CodeLocationResolverPort` + `PatchValidatorPort` registries by ADR 0017.
- **Preview + snippet UI** — `preview(...)` returns `path` + unified `diff` + `change_summary` +
  `grounding[]` with zero writes; the frontend renders it in `HudDraftPrPreviewModal` via the
  sanitized `HudCodeBlock` primitive (`auto-sec-frontend/src/components/V2/HudCodeBlock.jsx`).
- **Remediation Memory** (ADR 0012) — merged fixes are captured per-tenant and ground the next fix.
- **The SSOT + board + triage seam** — `NormalizedFinding` → `FindingObserved` → `findings`
  context (dedup fingerprint, lifecycle, auto-reopen) → board card → triage routing. The
  finding-source→board→triage recipe has been run three times (logwatch, cloud_exposure, Trivy);
  it is a ~1-day seam per source.
- **The scanner substrate** — `ScannerPort` (`components/shared_kernel/application/ports/scanner_port.py`)
  with two adapters already behind it: Prowler (`cloud_posture`) and Trivy (`container_security`),
  both running as ephemeral hardened K8s Jobs via `ScanExecutionBackend` (ADR 0006: gVisor
  runtimeClass, read-only rootfs, default-deny NetworkPolicy, resource limits).

**The ONLY net-new front-of-funnel piece is the SAST engine itself** — an adapter, a normalizer,
triggers, and the noise discipline around it. Everything downstream is reuse.

### What a SAST finding uniquely brings

Unlike a cloud-posture finding (ARN + check id — location must be *resolved*, the crux of ADR
0017 D2), a SAST finding **arrives with its code location**: repo, file, line span, rule id, and
the matched snippet. For ADR 0017's engine this is the easiest remediation class that exists — the
location resolver is a pass-through. That is why this pillar's findings are the highest-leverage
input the draft-PR loop can get.

## Research grounding (claim → source, fetched 2026-08-07)

| # | Claim | Source |
|---|---|---|
| R1 | **Semgrep's 2024 clampdown:** on 2024-12-13 Semgrep rebranded OSS → "Community Edition", moved cross-function taint, result **fingerprinting**, and tracking-ignores behind the commercial platform, and put registry rules under the **Semgrep Rules License v1.0**, which forbids use in "competing" products and SaaS offerings (grace period to 2025-01-31 for vendors to phase out). The *engine* stays LGPL-2.1; the *rules* are the trap for a commercial embedder like Auto-Sec. | Semgrep announcement (2024-12)[^semgrep-change]; licensing docs[^semgrep-license]; third-party analyses[^opengrep-press] |
| R2 | **Opengrep:** community fork of Semgrep CE launched 2025-01 by a consortium of 10+ security vendors (Aikido, Endor Labs, Jit, Orca, Kodem, Arnica, Mobb, Legit…), with a dedicated full-time OCaml team. Engine LGPL-2.1, no commercial tier. Restores **cross-function (intrafile) taint across 12 languages, result fingerprinting for dedup, and tracking ignores**. Fully rule-format-compatible with Semgrep YAML + JSON/SARIF output as of early 2026 (divergence has begun; long-term compat not guaranteed). 30+ languages; native Windows restored Fall 2025. | Opengrep launch posts (2025-01)[^opengrep-press][^aikido-fork]; fork-vs-upstream comparison (2026)[^opengrep-vs] |
| R3 | **Opengrep is actively maintained:** monthly release cadence through 2026 — v1.23.0 (2026-06-18), v1.24.0 (2026-06-30), v1.25.0 (2026-07-01), **v1.26.0 (2026-07-24)**, with continuing taint-analysis and parser work. The org maintains an official `Dockerfile` and publishes packages on GHCR. | Opengrep releases page (fetched 2026-08-07)[^opengrep-releases]; org repos[^opengrep-org] |
| R4 | **Rules corpus:** `opengrep/opengrep-rules` is a fork of `semgrep-rules` **pinned at the 2024-12-13 pre-relicense commit** (i.e. the last permissively-usable snapshot) and is a *public archive* — the community rule freeze is real; ongoing rule freshness comes from consortium packs + first-party rules, not from that repo. | Opengrep org repo listing (fetched 2026-08-07)[^opengrep-org] |
| R5 | **CodeQL is licensed out:** the GitHub CodeQL Terms permit use only on OSI-licensed open-source codebases, academic research, or CI on open-source hosted on GitHub.com — *"The Software may not be used in connection with any codebase that is not an Open Source Codebase (e.g., code in a private repo in GitHub)"*; commercial use on private/closed-source code requires a separate commercial (GHAS) license. Scanning customers' private repos inside Auto-Sec is squarely prohibited. | CodeQL CLI LICENSE.md[^codeql-license] |
| R6 | **Semgrep CE vs Pro capability line:** CE taint is intraprocedural only; `--pro-intrafile` (cross-function, one file) and `--pro` (cross-file, 8 languages) are paid. Opengrep restores the cross-function tier but **cross-FILE taint remains a Semgrep-Pro exclusive** — an honest ceiling on any Opengrep-based pillar's recall for multi-file flows. | Semgrep pro-engine docs + comparison[^semgrep-pro][^opengrep-vs] |
| R7 | **Fingerprint-based dedupe is the industry standard:** SARIF `partialFingerprints` (`primaryLocationLineHash`) is how GitHub code scanning matches logically-identical results across runs so alerts survive re-scans and line drift; results uploaded without fingerprints produce duplicate alerts. Opengrep restored result fingerprinting for exactly this. | GitHub SARIF support docs[^sarif-fp]; R2 |
| R8 | **Scan→autofix→PR, as shipped by the market:** GitHub **Copilot Autofix** (GA 2024-08) generates fixes for code-scanning alerts, resolving ~2/3 of addressed alerts with little/no editing; agentic autofix (public preview 2026-07) covers ~90% of alert types in JS/TS/Java/Python, and "security campaigns" batch remediation with human review. **Semgrep Assistant**: ~40% of AI fixes outright accepted, ~40% a good starting point, gated on triage-agreement confidence. **Snyk** rebuilt remediation as ONE agentic engine (Agent Fix), SCA first, SAST in active development. **Aikido AutoFix**: one-click AI autofix opening PRs across SAST/IaC/SCA on a dual engine (proprietary + **Opengrep**) — proof that a commercial SaaS ships Opengrep inside. All are *proposal*-shaped: fixes land as PRs/suggestions a human merges, never auto-merge. | Copilot Autofix GA + agentic preview[^autofix-ga][^autofix-agentic]; Semgrep Assistant[^semgrep-assistant]; Snyk Agent Fix[^snyk-agentfix]; Aikido AutoFix[^aikido-autofix] |
| R9 | **PR-volume discipline:** ~85% of automated security PRs go unmerged industry-wide; Dependabot-fatigue studies document rubber-stamping/queue abandonment. Merge rate, not PR count, is the metric. (Carried from ADR 0017 Amendment B — restated here because SAST is the highest-volume finding source we will ever attach to the PR engine.) | Pixee merge-rate; Dependabot studies[^pixee][^dependabot] |
| R10 | **Trivy's overlap is misconfig + secrets, not app-code SAST:** `trivy fs --scanners vuln,misconfig,secret` covers IaC misconfigurations (Terraform/CFN/K8s/Helm/Dockerfile — tfsec absorbed) and secret detection, but Trivy does no taint/dataflow analysis of application code. The pillars are complementary, with two deliberate overlap seams to police (secrets, IaC checks — see D2 scope table). | Trivy misconfiguration docs[^trivy-misconf] |
| R11 | **Bandit is Python-only** (PyCQA's AST-based security linter for Python) — a fine single-language tool, not a multi-language pillar engine for an ICP shipping Python **and** TS/JS **and** Go. | Bandit repo/docs[^bandit] |

## Decisions

### D1 — Engine: **Opengrep**, pinned, official artifact, native output. Semgrep CE and CodeQL are licensing-rejected; Bandit is coverage-rejected. **[proposed]**

**Choice: Opengrep** (R2/R3), for four reasons in order:

1. **License fits a commercial security SaaS.** Engine LGPL-2.1 with no competing-use clause; the
   consortium's explicit purpose is keeping SAST embeddable by security vendors — and Aikido
   already ships Opengrep inside a commercial product in our exact price class (R8). By contrast,
   Semgrep CE's *engine* is usable but its **rules license v1.0 forbids exactly our use** (a
   competing security SaaS, R1), and CE is deliberately defanged (no fingerprinting — which D4
   needs — and intraprocedural-only taint, R6). CodeQL is flatly prohibited for scanning
   customers' private repos outside GitHub's own products (R5).
2. **Alive and institutionally backed.** 10+ vendor consortium, dedicated full-time OCaml team,
   monthly releases through 2026 (v1.26.0, 2026-07-24) — not a zombie fork (R2/R3).
3. **Capability floor is right:** 30+ languages, cross-function taint in 12, restored result
   fingerprinting (feeds D4 dedupe directly), Semgrep-rule-format compatible so the enormous
   existing rule ecosystem and our own first-party rules share one YAML dialect (R2).
4. **No build step, no execution.** Opengrep parses source (tree-sitter/OCaml); it never compiles
   or executes the scanned code — unlike CodeQL's extractor-build model for compiled languages.
   That materially shrinks D6's threat model: untrusted code stays data.

**Per-language coverage vs our ICP** (AI-era builders shipping fast: Python/Django, TS/JS/Node,
Go, some Ruby/Java): all first-class in Opengrep, with cross-function taint for the top languages
(R2/R6). **Honest ceiling:** cross-*file* taint stays Semgrep-Pro-only (R6) — multi-file flows
will under-report. We compensate with curated high-confidence rules (D4), the triage agent's
LLM validation pass, and contextual re-rank — we do not pretend to Pro-depth recall.

**Rules sourcing (the licensing trap, handled):** ship a curated subset drawn from
(a) `opengrep/opengrep-rules` — the pre-relicense 2024-12-13 snapshot (R4), (b) consortium/community
packs, and (c) our own first-party rules (the compounding asset — Remediation Memory tells us which
rules produce merged fixes). **Never** pull anything published under Semgrep Rules License v1.0
into the product. The rules corpus is frozen-at-fork upstream (R4), so P1 includes a **per-pack
license audit** with provenance recorded per rule pack, and rule freshness is owned by us
thereafter — that is a real ongoing cost, priced in, not hidden.

**Pinning (pin-versions HARD RULE):** the engine runs as a pinned official artifact —
`ghcr.io/opengrep/opengrep:<version>@sha256:<digest>` if the org's GHCR image proves to be the
canonical distribution (R3), else a minimal image we build `FROM` a pinned base installing the
pinned official release binary (still native CLI + native output — **no custom SDK wrapper**; the
Prowler `prowler_sdk_runner.py` mistake is the named anti-pattern, per `improve-dont-replicate.md`).
`OPENGREP_IMAGE` env var, like `TRIVY_IMAGE`/`PROWLER_IMAGE`. Boy-scout note: `_TRIVY_IMAGE` is
currently tag-pinned only (`aquasec/trivy:0.58.0`); when this pillar lands, add digests to all
three engine pins in the same change.

**Rejected engines:**

| Engine | Verdict | Why |
|---|---|---|
| GitHub CodeQL | **Rejected — license** | Prohibited on non-OSS codebases outside GitHub's products; commercial use on private repos requires a GHAS-class license (R5). Also requires build steps for compiled languages (execution surface). |
| Semgrep CE | **Rejected — rules license + defanged CE** | Engine LGPL is fine, but the rules we'd need are v1.0-restricted against competing SaaS (R1), and CE lacks fingerprinting + cross-function taint (R6) — the fork exists precisely because of this. |
| Bandit | **Rejected — coverage** | Python-only (R11); our ICP ships TS/JS/Go too. Its checks are largely represented in the Semgrep-format rule ecosystem anyway. |
| SonarQube CE | **Rejected — shape** | A stateful server product oriented to code *quality* with its own UI/DB; embedding it inverts the ephemeral-Job substrate and duplicates our SSOT/lifecycle. |
| Third-party SaaS SAST APIs (Snyk Code, etc.) | **Rejected — data boundary + dependency** | Customer source code would leave the tenant to a third party we don't control — unacceptable for a security product whose pitch includes data discipline; plus per-scan COGS and a rug-pull-shaped dependency (R1 is the cautionary tale). |
| Custom wrapper around any engine's internal SDK | **Rejected — the Prowler mistake** | Breaks on every engine version bump; official image + native CLI + native output is the standing precedent. |

### D2 — Architecture: a `code_security` bounded context (third pillar-context instance), an `OpengrepScanner` driven adapter behind the existing `ScannerPort`, running in the ADR 0006 substrate; findings land in the Finding SSOT with code locations; board/triage wiring via the proven recipe. **No parallel pipeline.** **[proposed]**

**Context placement:** a new thin `components/code_security/` mirroring `container_security`'s
layout (adapter + normalizer + snapshot + api + workers + tests). The architecture skill (§4)
warns a scanning mechanism "usually" doesn't earn a context — but the repo's settled shape after
ADR 0006 is one thin context per pillar (`cloud_posture`, `container_security`); the third
instance follows the established pattern rather than inventing a fold-in. **Explicitly argued and
rejected: folding into `container_security`.** The target type (a git ref vs an image), the
evidence shape (file/line/rule vs package/CVE), the trigger surface (repo events vs image builds),
and the config (allowlisted repos vs image refs) all differ; fusing them would couple two
lifecycles to share nothing but the word "scan" — the substrate (`scanning` context) is already
the shared part.

```
 VcsConnection.repo_allowlist          code_security (new, thin)                    existing spine
 (consent, ADR 0010)              ┌──────────────────────────────────┐
        │                         │ OpengrepScanner (ScannerPort     │   FindingObserved
        ▼                         │  driven adapter)                 │ ──────────────────▶ findings SSOT
 scan trigger (D3) ──────────────▶│   └─ ScanExecutionBackend        │   (dedup D4,          │
   on-connect · beat · webhook    │      ephemeral K8s Job (ADR 0006)│    lifecycle,         ▼
                                  │      gVisor · deny-all-ish NP    │    auto-reopen)   board Task card
                                  │ sarif→NormalizedFinding          │                   + triage agent
                                  │  normalizer (file/line/rule/     │                   + draft-PR loop
                                  │  snippet in attributes)          │                     (ADR 0017/0010)
                                  └──────────────────────────────────┘
```

- **Adapter:** `code_security/infrastructure/adapters/opengrep_scanner.py` implements
  `ScannerPort.scan(target)` where `ScanTarget.identifier = "owner/repo@ref"`,
  `target.credentials` = the vended read token envelope, `target.params` = ruleset id + excludes +
  changed-paths (for P3 incremental). It composes a `ScanJobSpec` exactly as `TrivyScanner` does:
  a small POSIX script that (1) fetches the repo **archive tarball** at the pinned commit SHA via
  the VCS provider's archive endpoint (one HTTPS call — shallow by construction, no `git` binary,
  no credential helper), (2) unpacks to the writable `emptyDir`, (3) runs
  `opengrep scan --sarif --metrics=off -f /rules ...` with **our** mounted ruleset, (4) emits one
  JSON envelope on stdout (the Trivy-envelope precedent).
- **Repo access via the EXISTING VcsPort seam:** ADR 0010's connection owns the credential.
  `VcsPort` gains one read method, `get_archive_url(repo, ref)` (or the token is vended directly
  into the Job env per D6) — read-only, allowlist-checked before dispatch, same
  `_require_allowlisted_repo`-style gate as the PR engine. Scans run against a **resolved commit
  SHA** of the default branch (recorded on the snapshot + every finding), never a moving ref.
- **Output + normalization:** native **SARIF** (`--sarif`) — the standard interchange format,
  standard fingerprints (R7), zero wrapper. The normalizer
  (`code_security/infrastructure/services/opengrep_normalizer.py`) projects SARIF results into
  `NormalizedFinding` with `source="code_security.opengrep"`, severity mapped from rule metadata,
  `asset_urn` = a repo URN (e.g. `urn:autosec:vcs:github:owner/repo` — the graph gains a
  lightweight repo asset node, correlated by value per C4), and `attributes` carrying:
  `repo`, `commit_sha`, `path`, `start_line`, `end_line`, `rule_id`, `rule_source` (pack),
  `cwe`/`owasp` tags, `confidence`, `language`, and `snippet` (per D8's rules). Scan-level counts
  land on a per-repo **snapshot row** (the `container_security` snapshot pattern) for the HUD tile.
- **Board + triage (the ~1-day recipe, fourth use):** a `_SOURCE_BOARD` entry for
  `code_security.opengrep` (card copy leads with rule + path:line), `ROUTABLE_SOURCE_TYPES` entry
  routing to the triage agent, a triage tool + deterministic-advisor branch, and a
  `finding_verifier` branch — same seam as logwatch/cloud_exposure/Trivy. "Routable without a
  tool is a silent no-op" — the tool ships in the same phase as the routing entry (P2).
- **Overlap policy (R10):** `code_security` owns **application-code** bugs/vulns. IaC misconfig
  rules are **excluded from the default ruleset** (Checkov-style IaC scanning is a future distinct
  spoke per ADR 0017's non-goals; Trivy already covers container/IaC surfaces). Secrets-in-repo
  detection is deliberately **out of P1** and decided once, for one owner, in OQ5 — not shipped
  twice by accident from two engines.

### D3 — Scan triggers: on-connect initial scan + scheduled beat cycle in P1; push-webhook incremental in P3. Default-branch only. Budgeted. **[proposed]**

- **On-connect / on-allowlist:** adding a repo to the allowlist (or connecting with repos already
  listed) enqueues an initial full scan per repo — the "wow, it found things in *my* code" moment
  lands during onboarding, like the AWS connect→Prowler flow.
- **Scheduled:** a Celery-beat cycle re-scans each allowlisted repo's default branch (default
  daily, off-peak, per-workspace jitter). Because identity is fingerprint-based (D4), a re-scan is
  cheap on the SSOT: unchanged findings just bump `last_seen`; fixed ones stop being observed
  (and the existing resolve/reconcile machinery closes them); new ones are genuinely new.
- **P3 — push-webhook incremental:** the VCS webhook (ADR 0010's provider seam) triggers a
  changed-paths scan on push to the default branch (`opengrep` over the touched files), keeping
  latency near-CI-time without full-scan cost. Webhook infra is P3 because it drags provider
  webhook registration + signature verification with it — a deliberate, separate slice.
- **Cost/noise controls (all P1):** per-workspace concurrent-scan cap; per-repo scan timeout
  (`activeDeadlineSeconds`) and repo-size guard (skip archives over a threshold with an honest
  snapshot note); default path excludes (`vendor/`, `node_modules/`, `dist/`, minified/generated
  files, test fixtures) applied from **our** config; default-branch only (feature-branch scanning
  is CI's job, not ours — we are posture, not a PR gate).

### D4 — Noise discipline: curated ruleset, severity floor, fingerprint dedupe, contextual re-rank. The SSOT absorbs everything; the board gets only what earns attention. **[proposed]**

The single biggest way this pillar fails is the wall-of-findings failure William named. Four
layers, in order:

1. **Ruleset curation (the floor of the funnel).** P1 ships a *curated security ruleset* —
   high-confidence security rules per ICP language (audited per D1's rules-licensing pass), not
   "every rule we can find". Correctness/bug rules (Henry's ask says *bugs* too) enter as a
   second, smaller curated tier, default-on but board-gated by severity. Every rule pack carries
   provenance + license in config; adding a pack is a reviewed change, not a default.
2. **Severity floor for the board.** ALL findings land in the Finding SSOT (visible in the HUD
   findings panel, filterable). Only findings at/above the board floor (default: high+critical)
   become board cards via the recipe. The floor is per-workspace config.
3. **Dedupe by stable fingerprint.** `fingerprint = repo | rule_id | path | opengrep_result_fingerprint`
   — Opengrep's restored result fingerprint (R2) is line-drift-tolerant, the same property GitHub's
   SARIF `partialFingerprints` exist for (R7). **Line numbers never enter the fingerprint** (edits
   above a finding must not mint a "new" finding). The SSOT's existing
   `(workspace, source, fingerprint)` identity + `observed()` auto-reopen then gives
   first_seen/last_seen/lifecycle across scans for free. Fallback when the engine fingerprint is
   absent: a `primaryLocationLineHash`-style content hash of the matched region (R7).
4. **Contextual re-rank (ADR 0013).** SAST severity is rule-static; rank boosts/damps by context
   where signals exist — is the repo linked to deployed workloads (cloud-graph correlation by the
   repo asset URN), does the rule map to CWE classes with KEV/EPSS-adjacent weight
   (`vuln_intel`), is the file hot (recently changed). The digest surface shows top-N by rank —
   *"what do I need to know today"*, not a count.

### D5 — The fix loop: a SAST finding is ADR 0017's easiest remediation class; a trivial location resolver feeds the ONE engine; draft-PR with snippet preview via the existing UI; PR volume is throttled and confidence-gated. **[proposed]**

- **Location resolution is a pass-through.** Register `SastLocationResolver` in ADR 0017's
  `CodeLocationResolverPort` registry: it reads `attributes` (repo/path/span/rule) straight into a
  `CodeLocation` with `confidence="authoritative"` — the scanner *is* the resolver. No state
  files, no reverse maps, no search heuristics. This is deliberately the cheapest possible proof
  of 0017's seam design (and lands only after 0017's P1 extraction, which this ADR sequences
  behind — see phases).
- **Patch generation:** the ONE universal advisor (0017 D4): fix *templates* where a rule has a
  mechanical fix (the Semgrep ecosystem's `fix:` metadata on autofixable rules seeds these), the
  LLM-grounded strategy otherwise — grounded on the real file content + the finding's snippet +
  rule guidance + Remediation-Memory priors, through the existing dialect validators
  (`PythonPatchValidator` et al., generic rules for the rest), fail closed.
- **Preview with snippet:** the existing `preview(...)` contract + `HudDraftPrPreviewModal` +
  `HudCodeBlock` render (a) the offending snippet at `path:start_line` and (b) the unified diff —
  Henry's "preview snippet code", with zero new UI primitives (the `dry-reuse` frontend rule).
- **PR discipline (R9 — load-bearing):** SAST is the highest-volume source we will ever connect
  to the PR engine, and ~85% of automated security PRs industry-wide rot unmerged. Therefore:
  **never bulk-fire PRs per scan cycle**; draft-PR proposals are (a) operator-initiated from the
  card/preview, or (b) triage-agent-proposed for at most **top-N by contextual rank per cycle**
  (N default 3, per-workspace config), (c) only for rules on the **autofix-confident list**
  (template-backed or empirically high-accept — the market gates the same way: Copilot ~2/3
  little-edit fixes, Semgrep Assistant ~40% outright accept, R8), (d) always draft, always
  human-merged, (e) always board-provenanced (the "every AI action posts to the board" hard
  rule). Merge rate is the pillar's success metric, tracked on the snapshot.
- **Lifecycle close:** the merged PR flows through the existing reconciler
  (`reconcile_applied_remediations` — already source-agnostic); the next scheduled scan is the
  verification (the finding stops being observed → resolved stays closed; a bad fix re-observes →
  auto-reopen). Remediation Memory captures the merged diff with `rule_id` as a tag — per-tenant,
  per-rule proven fixes compound (ADR 0012's wedge, now fed by its richest source).

### D6 — Security of the scanner itself: untrusted code is DATA, never executed; hardened ephemeral Job; minimal egress; one short-lived read token; nothing from the repo configures the scan. **[proposed]**

Scanning customer code means running our engine over adversarial input. Threat model + controls:

- **No execution of scanned code.** Opengrep parses; it has no build/exec step (D1 reason 4).
  We never run repo build tooling, hooks, or scripts. The archive is unpacked with a
  hardened extraction (no symlink escape, size caps) into the Job's `emptyDir`.
- **Repo-side config is untrusted data.** The scan runs with **our** mounted ruleset and **our**
  exclude list only. `.semgrepignore`/repo scanner configs are not honored (a malicious or
  compromised repo must not be able to silence its own findings), and repo-provided rule files are
  never loaded. `--metrics=off` always (no engine phone-home).
- **Job hardening = the ADR 0006 baseline, verbatim:** ephemeral K8s Job, gVisor
  `runtimeClassName` where available, read-only rootfs + writable `emptyDir` only,
  `allowPrivilegeEscalation: false`, non-root, CPU/memory limits, `activeDeadlineSeconds`.
- **Network:** a scan-job NetworkPolicy allowing egress **only** to the VCS host (archive fetch)
  + DNS — mirroring the Trivy policy's egress→trivy-server+registry shape. After the fetch the
  engine needs no network at all; the policy is least-privilege for the Job's lifetime.
- **Secrets:** exactly ONE secret enters the Job — a **short-lived, read-only** repo token
  (narrowest available grant for the provider; for GitHub, a fine-grained/installation token
  scoped to contents:read on the allowlisted repo where the connection type supports it), passed
  via env (never argv — argv is visible in `ps`/logs), never logged (`@sensitive_variables` on
  every function touching it), invalidated by TTL not by cleanup code. No AWS creds, no DB creds,
  no LLM keys in scan Jobs — the Job scans and prints; normalization/persistence happen in the
  worker.
- **Output is untrusted too:** the worker parses the Job's stdout envelope defensively (size
  caps, schema validation) — a hostile repo influences SARIF *content*, and that content flows to
  renderers only through the sanitized snippet path (D8).

### D8 — Snippet handling: store minimal context, render only through the sanitized primitive, mask secret-bearing matches, and never ship code externally. **[proposed]**

(Numbered D8 to keep D-numbers aligned with the section list; there is no D7.)

- **Store minimal.** `attributes.snippet` = the matched region ± 3 context lines, hard-capped
  (~2k chars), stored as plain text on the finding. Full files are never persisted — the preview
  flow reads file content live through `VcsPort.get_file` at preview time, as it does today.
- **Render sanitized.** Snippets and diffs render **only** through `HudCodeBlock` (text
  rendering, no HTML interpretation) — customer code is untrusted display content; no new
  render path, no dangerouslySetInnerHTML, ever.
- **Mask secret-shaped matches.** For rules whose class is hardcoded-credential/secret, the
  snippet is stored **masked** (the matched literal replaced with `••••` + last 4) — otherwise
  the finding itself would replicate the secret into the DB, the board card, and every projection.
- **External messages carry no code.** Slack/notification deliveries (ADR 0016) follow the
  existing world-readable standard: rule id, severity, repo + path:line, link back to the HUD —
  **never the snippet, never the diff** (a channel's membership is invisible to us; source code
  is customer-confidential by default).

## Consequences

**Positive:** the highest-leverage input the proven draft-PR loop can receive, at adapter-sized
cost — the pillar is an engine + normalizer + triggers; SSOT, board, triage, remediation, preview,
memory, and lifecycle are reuse. Completes Henry's connect-repo story: one consent surface
(`repo_allowlist`) now both finds and fixes. The demo/dogfood story is immediate (scan our own
repos, open a real fix PR on a real finding). Opengrep's licensing posture removes the rug-pull
class of risk CodeQL/Semgrep-rules carry.

**Negative / costs:** rule curation is an *ongoing* editorial responsibility (the community corpus
froze at the fork, R4) — priced in via first-party rules + the license audit, but real. Cross-file
taint stays out of reach (R6) — recall is honestly bounded. A new engine image joins the pinned
fleet (version-bump toil ×3). SAST's noise potential is the largest of any pillar — D4 is
load-bearing, not optional polish. Fork-divergence risk (R2): rule-format compat is intact as of
early 2026 but not guaranteed forever; mitigation is the pinned engine + our own rule corpus in
the compatible dialect.

## Non-goals

- **Not a CI/PR gate.** We scan the default branch as posture; blocking PRs in the customer's CI
  is their pipeline's job (and a different product shape).
- **Not IaC static scanning** (Checkov-shape) — excluded from the default ruleset (D2 overlap
  policy); if it comes, it is its own deliberate spoke decision.
- **Not SCA/dependency scanning** — Trivy owns package CVEs; and per ADR 0017's validation note,
  dependency *version-bump* remediation is a solver problem to be decided deliberately, never
  forced into the patch engine.
- **Not secrets scanning in P1** (OQ5 decides the single owner).
- **No auto-merge, ever.** Draft PRs, human-merged (R8/R9 — nobody credible auto-merges either).
- **No GitLab/Bitbucket-specific work** — inherited free when ADR 0010's other adapters land.

## Phased build plan (each phase awaits Henry's go — standing rule)

**P1 — engine + SSOT + board (the pillar exists):**
`code_security` context; `OpengrepScanner` adapter (pinned image tag+digest, envelope protocol,
hardened Job + NetworkPolicy per D6); SARIF normalizer → `NormalizedFinding` (D2 attributes,
D4 fingerprint); repo asset URN; snapshot row + HUD tile; on-connect + beat triggers with the D3
budget controls; curated P1 ruleset **with the per-pack license audit**; `_SOURCE_BOARD` card
entry + severity floor; query-count + architecture fitness tests (scanner-behind-port, no new
finding table, no cross-context infra imports). *Dogfood target: auto-sec-api + wanjala-api repos,
mirroring the log-pipeline dogfood.*

**P2 — triage + the fix loop (the pillar pays):**
`ROUTABLE_SOURCE_TYPES` + triage tool + verifier branch (the recipe's second half);
`SastLocationResolver` registered into ADR 0017's registry (sequenced behind 0017-P1's
extraction); autofix-confident rule list + fix templates for the top rules; draft-PR proposals
throttled per D5; preview modal wiring for the SAST card (snippet + diff via `HudCodeBlock`);
merge-rate metric on the snapshot; Remediation-Memory capture tagged by `rule_id`.

**P3 — incremental + polish (the pillar scales):**
push-webhook changed-paths scans (provider webhook registration + signature verification);
digest integration with contextual re-rank (ADR 0013) as its signals land; per-workspace ruleset
tuning surface (enable/disable packs, floor config); language/coverage expansion + a scheduled
re-audit of the Opengrep↔Semgrep divergence and rules licensing.

## Open questions (for Henry)

1. **Trigger default:** auto-scan every allowlisted repo on connect (opinionated, good demo), or
   an explicit per-repo "enable code scanning" toggle (quieter, more consent-shaped)? Proposal:
   auto-scan on allowlist — the allowlist *is* the consent — with a per-repo opt-out.
2. **Ruleset aggressiveness:** security-only for P1, or security + the high-confidence
   correctness/bug tier from day one? (Your ask said "bugs" — proposal: both tiers on, but only
   security high/critical reaches the board by default.)
3. **First repos:** dogfood order — `auto-sec-api` + `wanjala-api` (like the log pipeline), then
   Tom's org as the first real user under the "harden for Tom" priority?
4. **Board floor:** high+critical default OK, or medium+ while volume is still small?
5. **Secrets scanning owner:** Trivy `--scanners secret` on repo archives, Opengrep secret rules,
   or defer entirely? One owner, one decision — P1 ships neither until this is answered.
6. **Scan cadence default:** daily per repo OK, or weekly until webhook incremental (P3) lands?

[^semgrep-change]: Semgrep, "Important updates to Semgrep OSS" (2024-12): https://semgrep.dev/blog/2024/important-updates-to-semgrep-oss/
[^semgrep-license]: Semgrep licensing docs (CE engine LGPL-2.1; Semgrep Rules License v1.0 restricts competing/SaaS use): https://semgrep.dev/docs/licensing
[^opengrep-press]: SecurityWeek, "Endor Labs and Allies Launch Opengrep" (2025-01): https://www.securityweek.com/endor-labs-and-allies-launch-opengrep-reviving-true-oss-for-sast/ ; Socket, "Opengrep emerges as open source alternative amid Semgrep licensing changes" (2025-01): https://socket.dev/blog/opengrep-forks-semgrep ; The Stack, "Semgrep 'rug pull' triggers Opengrep fork storm" (2025-01): https://www.thestack.technology/semgrep-fork-opengrep/
[^aikido-fork]: Aikido, "Launching Opengrep — why we forked Semgrep" (2025-01): https://www.aikido.dev/blog/launching-opengrep-why-we-forked-semgrep ; Jit, "Announcing Opengrep" (2025-01): https://www.jit.io/resources/jit-security/announcing-opengrep-continuing-the-open-source-mission-for-static-code-analysis
[^opengrep-vs]: AppSec Santa, "OpenGrep vs Semgrep (2026): fork vs upstream comparison" (fetched 2026-08-07 — consortium membership, restored features, 30+ languages, LGPL-2.1, rule-compat "fully intact as of early 2026", divergence risk): https://appsecsanta.com/sast-tools/opengrep-vs-semgrep
[^opengrep-releases]: Opengrep releases (v1.26.0 2026-07-24; monthly cadence; fetched 2026-08-07): https://github.com/opengrep/opengrep/releases
[^opengrep-org]: Opengrep GitHub org (engine LGPL-2.1; `opengrep-rules` = archived fork of semgrep-rules at 2024-12-13; official Dockerfile + GHCR packages; fetched 2026-08-07): https://github.com/orgs/opengrep/repositories
[^codeql-license]: GitHub CodeQL Terms and Conditions (CodeQL CLI LICENSE.md — OSS-codebase-only permitted uses; private-repo commercial scanning requires a commercial license): https://github.com/github/codeql-cli-binaries/blob/main/LICENSE.md
[^semgrep-pro]: Semgrep docs, "Perform cross-file analysis" (CE = intraprocedural; `--pro` cross-file limited to 8 languages): https://semgrep.dev/docs/semgrep-code/semgrep-pro-engine-intro ; Semgrep, "Compare Semgrep to Opengrep": https://docs.semgrep.dev/faq/comparisons/opengrep
[^sarif-fp]: GitHub docs, "SARIF support for code scanning" (`partialFingerprints` / `primaryLocationLineHash` dedupe across runs; missing fingerprints → duplicate alerts): https://docs.github.com/en/code-security/reference/code-scanning/sarif-files/sarif-support
[^autofix-ga]: GitHub changelog, "Copilot Autofix for CodeQL code scanning alerts is now generally available" (2024-08-14; ~2/3 of addressed alerts fixed with little/no editing): https://github.blog/changelog/2024-08-14-copilot-autofix-for-codeql-code-scanning-alerts-is-now-generally-available/
[^autofix-agentic]: GitHub changelog, "Agentic autofix for code scanning alerts in public preview" (2026-07-10; ~90% of alert types in JS/TS/Java/Python; security campaigns batch with human review): https://github.blog/changelog/2026-07-10-agentic-autofix-for-code-scanning-alerts-in-public-preview/
[^semgrep-assistant]: Semgrep, "The tech behind Semgrep Assistant" (2024; ~40% of AI fixes outright accepted, ~40% good starting point; confidence-gated on triage agreement): https://semgrep.dev/blog/2024/the-tech-behind-semgrep-assistant/
[^snyk-agentfix]: Snyk, "Snyk Remediation Agent in the CLI" (one agentic remediation architecture; SCA shipped, SAST in active development): https://snyk.io/blog/snyk-remediation-agent-in-the-cli/
[^aikido-autofix]: Aikido, "AI SAST & IaC Autofix" (one-click AutoFix PRs; dual engine incl. Opengrep; 18 languages; fetched 2026-08-07): https://www.aikido.dev/features/autofix
[^pixee]: Pixee, "The merge-rate problem: ~85% of automated security PRs go unmerged": https://www.pixee.ai/blog/merge-rate-problem-security-prs-ignored
[^dependabot]: Dependabot usage studies (notification fatigue → rubber-stamping / abandonment): https://arxiv.org/pdf/2206.07230
[^trivy-misconf]: Trivy docs, "Misconfiguration scanning" (`--scanners vuln,misconfig,secret`; Terraform/CFN/K8s/Helm/Dockerfile via absorbed tfsec — no app-code dataflow analysis): https://trivy.dev/docs/latest/scanner/misconfiguration/
[^bandit]: PyCQA Bandit (Python-only AST security linter): https://github.com/PyCQA/bandit
