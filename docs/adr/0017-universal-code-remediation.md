# ADR 0017 — Universal code remediation: ONE engine, pluggable location resolvers + dialect validators (cloud-misconfig resolvers first)

Status: Proposed (2026-08-05) — design only; the build follows this spec.

Relates to: **ADR 0010** (`VcsPort` / `VcsConnection` / repo-allowlist — the draft-PR engine this
ADR extends, never forks), **ADR 0012** (Remediation Memory — the capture/retrieval loop every
merged fix feeds), **ADR 0008 / ADR 0016** (the port + per-workspace-config + registry template,
applied here to *evidence→location resolution* and *patch validation*), **ADR 0004** (Finding SSOT +
`AssetUrn` correlation-by-value), **ADR 0006** (scanner-execution substrate — the ephemeral-Job home
for any future `terraform validate` step), **ADR 0013** (contextual risk — ranks which finding
deserves the PR first), the **response-action framework** (`components/response` —
propose/approve/execute/rollback; the *runtime stopgap* this ADR pairs with the *root fix*), and
Tom's operator feedback: **remediation → IaC PR is his #1-ranked build gap** — fix the misconfig at
its source of truth, not in the console.

Henry's scoping corrections (2026-08-04/05, supersede the earlier Terraform-first framing): *the
system must be code-agnostic, period — if a VCS repo is connected, remediation adapts to WHATEVER
is in it: Django, Go, Ruby, Terraform, CloudFormation, CDK, Pulumi, raw AWS-SDK scripts. This is
NOT an "IaC remediation subsystem"; it is the ONE remediation engine growing two plugin seams.*

## Context

### The universal engine already exists — and it is language-agnostic

Auto-Sec's remediation engine is built and **proven on real code**: a log-watch finding is triaged,
the grounded advisor (`LogPatchAdvisor`,
`components/integrations/infrastructure/services/log_patch_advisor_service.py`) searches the
allowlisted repo, grounds a full-file patch against the *actual* file contents (plus
Remediation-Memory priors, ADR 0012), deterministic guardrails validate it,
`OpenDraftPrUseCase` (`components/integrations/application/use_cases/open_draft_pr_use_case.py`)
opens a draft PR through `VcsPort` behind the `repo_allowlist` consent boundary, `preview(...)`
feeds the frontend modal (`path` + unified `diff` + `change_summary` + `grounding[]`), the board
card records provenance, the merge-detection reconciler
(`components/remediation/…::reconcile_applied_remediations`) auto-resolves the finding when the PR
merges, and Remediation Memory captures the proven fix. The loop was proven end-to-end on a real
grounded **Python** fix shipped as a dogfood draft PR (2026-08-04) — and nothing in the engine is
Python-specific: repo search, diffing, preview, consent, provenance, merge detection, and capture
are all language-agnostic. **Any language flows through this engine today.** That engine is the
foundation of this ADR — not a fallback afterthought.

What the engine does NOT yet have are two pieces of *pluggable intelligence*:

1. **Location resolution beyond stack traces.** Today the only way a finding's evidence becomes a
   code location is the traceback/log-path heuristic living *implicitly inside* the advisor
   (`derive_candidate_path` — deterministic traceback-frame parsing, repo-tree filtered). A
   cloud-posture finding carries no traceback — its evidence is a **resource ARN + region +
   account + check id** — and turning *that* into a file/block requires cloud-side reverse maps
   (Terraform state, CloudFormation stack APIs) the engine has no seam for.
2. **Validation beyond Python + generic text rules.** The guardrail chain
   (`validate_patch`: `patch_empty_or_noop` → `patch_does_not_parse` (`.py` AST) →
   `patch_removes_definitions` (top-level symbol drop = fail closed) → `patch_too_destructive`
   (retained-line fraction)) is Python-aware plus language-generic. A `.tf` or CFN-template patch
   deserves dialect-aware validation, because the **blast radius is asymmetric**: a bad app-code
   patch fails tests in CI; a bad Terraform patch that drops a resource block can *destroy
   infrastructure on merge+apply*.

This ADR adds exactly those two plugin seams — **`CodeLocationResolverPort`** and
**`PatchValidatorPort`** — plus a deterministic **fix-template strategy layer** for well-known
checks, all on the ONE engine. Cloud-misconfiguration resolvers (CloudFormation, Terraform-state)
ship first because they serve Tom's #1 ask; the seams are domain-neutral by construction.

### Why the cloud-misconfig resolvers matter (Tom's ask)

The cloud-posture pillar has everything *except* the code last-mile: Prowler findings land on the
board with remediation *text*, and the only actionable machinery is the runtime response action
(`REVOKE_SG_INGRESS`) — which fixes the *cloud*, not the *code*. A console/runtime fix to
IaC-managed infra is undone on the next deploy; the finding reopens; counts never go down. This
"remediation treadmill" is the single most-documented failure mode of CSPM programs[^cspm-cycle],
and it is exactly Tom's ask: he ships infra from code, so the fix must land in code.

The competitive bar is set: Wiz maps every live resource back to "the exact module, file, line of
code, and author that defined it" and opens a targeted PR at the source[^wiz]; Prisma Cloud
(Bridgecrew) detects drift and raises automatic PRs fixing the drifted HCL[^checkov]. Nobody in the
"security team you don't hire" price class does this — it is wedge territory, but only if the
mapping is honest (see D2's unmapped tier).

### What exists today (grounding — read, not guessed)

**1. What a Prowler finding carries.** The OCSF normalizer
(`components/cloud_posture/infrastructure/services/prowler_ingest_service.py::parse_prowler_ocsf`)
projects Prowler's `json-ocsf` output into `NormalizedPostureFinding`
(`components/cloud_posture/domain/entities/posture_finding_entity.py`) and then into the
shared-kernel `NormalizedFinding` with `source="cloud_posture.prowler"`,
`fingerprint = check_id|account_id|resource_uid`, `asset_urn`, `remediation` (Prowler's
`remediation.desc` text), and an `attributes` dict carrying **`check_id`** (e.g.
`ec2_securitygroup_allow_ingress_from_internet_to_tcp_port_22`), **`resource_uid` (the ARN)**,
**`region`**, **`account_id`**, `resource_type`, `resource_name`, `service`. The Finding SSOT row
(`infrastructure/persistence/findings/models.py::Finding`, ADR 0004 D1) persists all of it —
identity `(workspace, source, fingerprint)`, lifecycle `open → resolved/suppressed` with
auto-reopen on re-observation (`FindingEntity.observed()`), operator status endpoint (PR #232).
**Everything a resolver needs — ARN, region, account, check id — is already on the finding.**

**2. The engine details being reused verbatim.** `OpenDraftPrUseCase` is the single choke point:
ordered gates (`_require_connection` → `_require_allowlisted_repo` → actionable-finding →
idempotency → capability → token), then `create_branch` / `commit_file` / `open_draft_pr` through
`VcsPort` (ADR 0010; GitHub adapter proven). `preview(...)` runs the **identical** validation path
with zero writes (`DraftPrPreviewResource`: `path`, unified `diff` ≤ 12k chars, `change_summary`,
`grounding[]`, `repo`, `already_opened`, `pr_url`). Consent = `VcsConnection.repo_allowlist`
(`infrastructure/persistence/integrations/models.py` — a repo not listed is rejected before any
API call). Provenance = `record_draft_pr` → payload patch + card comment + provenance event +
owner notification (the "every AI action posts to the board" hard rule). **Two engine facts this
ADR generalizes rather than duplicates:** the actionable-finding gate is source-gated to
`ai.log_watch` today, and the location heuristic + Python guardrails are hard-wired rather than
registry-resolved.

**3. The lifecycle machinery already in place.** `components/remediation/` owns the merge-detection
reconciler (`reconcile_applied_remediations` — candidate predicate is *already source-agnostic*:
any board Task carrying `payload.draft_pr`), wired via injected callables to integrations'
`CheckPullRequestMergedUseCase` (allowlist-enforced, fails closed to `merged=False`), project's
resolve-finding use case (`resolved_by="system:remediation_reconciler"`), and ADR 0012's
`capture_remediation_if_gated` entry gate. A merged infra PR flows through this **unchanged**.

**4. The runtime counterpart.** `components/response/` implements
propose (reversible, agent-ok, `dry_run=True` default) → approve (human-only, justification
required) → execute → rollback, linked to the finding **by value** via `finding_fingerprint`
(C4-clean). Its only kind today, `REVOKE_SG_INGRESS`, targets exactly the security-group findings
in this ADR's P1 set — the stopgap/root-fix pairing (D6) is sitting there waiting to be named.

**5. Credentials.** `AwsRoleCredentialsPort` / `AwsAccountAccessPort`
(`components/integrations/application/ports/`) are the single STS token-vending seam (assume-role +
ExternalId, secrets never in argv/logs) that already feeds Prowler Jobs (ADR 0006). Any cloud-side
read a resolver needs (state object, `DescribeStackResources`) uses the same seam.

**6. The proving ground.** The demo AWS account's infra (863183417583) IS Terraform:
`wanjala-api-v2.0/octopus-infra/demo-infra/workloads/sandbox/` (incl. `autosec.tf` — the audit
role itself). Grounded facts that shape P1:

- **Open ingress, demo-provable:** `terraform.tfvars` sets `demo_allowed_cidrs = ["0.0.0.0/0"]`
  feeding `modules/ec2/main.tf::aws_security_group.demo` dynamic ingress on ports **22**, 80, 443,
  and **5555 (Celery Flower)**; same for the umami host. Prowler's SSH/any-port open-ingress checks
  FAIL here today.
- **S3:** the `reports` bucket has **no versioning** (`data` does) and neither bucket declares
  `aws_s3_bucket_server_side_encryption_configuration` — but since AWS default-encrypts (SSE-S3),
  the encryption check likely PASSes, so it is **not** a P1 proof target (honest grounding).
  Public-access-block is present on both (all four flags) — also not provable here.
- **State is LOCAL** — no `backend "s3"` block anywhere under `demo-infra`; `terraform.tfstate`
  sits beside the code. The Terraform resolver (D2) reads a state *backend*, so P1 carries a
  named prerequisite: migrate the sandbox to an S3 backend (`terraform init -migrate-state`) — a
  boy-scout improvement octopus-infra needs anyway.
- **CFN proof target:** Auto-Sec's own AWS onboarding provisions the audit role via a
  CloudFormation template/StackSet in customer accounts — the demo's role is Terraform-provisioned,
  so whether the demo account holds any live CFN stack to prove the CFN resolver against is an open
  question (OQ2); creating a tiny deliberately-misconfigured stack is a 10-minute fallback.

### Why plugin seams on one engine, not a subsystem

The *only* things that vary by domain/dialect are (a) how evidence becomes a code location
(traceback frame vs state file vs stack API vs plain search) and (b) what "a safe patch" means for
a given file type (AST symbols vs HCL blocks vs template logical resources vs generic text rules).
Everything else — consent, PR mechanics, preview, provenance, lifecycle, memory — is invariant and
already built. That is exactly the shape ADR 0008 (log sources), ADR 0010 (VCS providers), and
ADR 0016 (delivery channels) solved: a port shaped to the core's need, per-X adapters, a registry,
honest fallbacks. An "IaC remediation subsystem" would have been the copy-paste second pipeline
this house's rules exist to prevent (`dry-reuse.md` rule 4: one canonical thing per concern).

## Research grounding (claim → source)

| # | Claim | Source |
|---|---|---|
| R1 | Prowler check metadata natively carries per-check remediation code — `Remediation.Code` with **Terraform**, NativeIaC (CFN), CLI and Other variants (CSV columns `REMEDIATION_CODE_TERRAFORM` / `REMEDIATION_CODE_NATIVEIAC`), plus recommendation text/URL — i.e. the scanner itself ships a canonical per-check IaC fix *snippet* | Prowler check model + reporting docs[^prowler-meta] |
| R2 | Terraform mapping = two joins: **state** holds address ↔ cloud-id (`resources[].instances[].attributes.id/arn`), and repo scanning locates address → file/block; commercial cloud-to-code (Firefly) enriches every asset with "links to the IaC code and Terraform state managing it"; driftctl reads "terraform state backends of all types" to compare cloud vs state (now maintenance-mode); mapping physical-id→address requires a per-resource-type id-property table | Firefly docs, ControlMonkey, driftctl guides[^tf-mapping] |
| R3 | Terraform state **contains secrets** (plaintext values, credentials); best practice = backend-level read-only IAM, encryption, audit of state reads, expose the minimum | state-security guides[^tf-state-sec] |
| R4 | Lossless surgical HCL editing is `hclwrite` (Go) territory; `python-hcl2` gained a writer (2024) but is not a lossless formatter — so Python-side patches must be **anchored text splices re-validated by parse**, not parse→mutate→serialize round-trips | HCL tooling comparison[^hcl-tools] |
| R5 | `terraform init -backend=false` + `terraform validate` needs **no credentials and no state** — ideal for an ephemeral container; `terraform plan` requires backend init + creds and pulls state — a categorically heavier, riskier step | HashiCorp issue/docs, CI guides[^tf-validate] |
| R6 | CloudFormation offers a **server-side authoritative reverse map**: `DescribeStackResources(PhysicalResourceId=…)` returns the owning stack + logical resource id for a live resource ("pass the EC2 InstanceId … to find which stack the instance belongs to") — no state file needed; CFN-created resources also carry `aws:cloudformation:stack-name/logical-id` tags | AWS API reference[^cfn-map] |
| R7 | CDK-synthesized templates stamp every resource with `Metadata.aws:cdk:path` — the construct path mapping a CFN resource back to its construct in CDK source | AWS CDK docs/issues[^cdk-path] |
| R8 | Pulumi state (`pulumi stack export` / Cloud REST API) maps each resource's **URN** (`urn:pulumi:<stack>::<project>::<type>::<logical-name>`) to the provider-assigned physical id | Pulumi docs[^pulumi] |
| R9 | The productized bar: **Wiz** maps live resource → exact module/file/line/author and opens a targeted PR at the source; **Prisma Cloud (Bridgecrew)** raises automatic PRs fixing drifted HCL and ships per-check "fixed code"; both treat cloud-to-code as the remediation product | Wiz Code, Prisma/Checkov docs[^wiz][^checkov] |
| R10 | The treadmill: "a console fix closes the CSPM finding until the next deployment, at which point the IaC definition redeploys the misconfigured state and the finding reopens … the leading reason finding counts do not decrease" | CSPM remediation guides[^cspm-cycle] |
| R11 | Drift detection at HashiCorp itself = periodic **refresh-only plans against state** (health assessments) — state access is the canonical substrate for cloud↔code comparison, validating the state-read resolver | HCP Terraform docs[^hcp-drift] |
| R12 | Deterministic per-check fixes are the industry shape for the head of the distribution: Checkov's 750+ policies with auto-generated "fixed code" / Smart Fixes; LLMs are the tail, not the default | Checkov/Prisma docs[^checkov] |

## Decisions (LOCKED)

### D0 — ONE engine. No remediation path may ever fork per language, dialect, or finding domain. New domains add resolvers, validators, and fix templates — nothing else. **[locked]**

The universal engine — grounded advisor → guardrails → preview → `OpenDraftPrUseCase` → provenance
→ reconciler → Remediation Memory — is the only road from any finding to any repo change. A second
"open PR" use case, a per-domain advisor pipeline, a per-language preview contract, or a scanner
that commits to repos directly is a defect on sight (the `dry-reuse.md` "one canonical thing per
concern" rule, made specific). Extending remediation to a new domain (KSPM manifests, Dockerfiles,
CI configs, a new cloud) means: register a **location resolver** (D1/D2) if its evidence type needs
one, register a **dialect validator** (D4) if its file type needs one, optionally add **fix
templates** (D4) for its well-known findings — and touch nothing else. The engine's fitness
functions (architecture tests) enforce that `open_draft_pr` / `preview` have exactly one
implementation and that no other context imports `VcsPort` write capabilities.

### D1 — The two plugin seams: `CodeLocationResolverPort` (evidence → code locations) and `PatchValidatorPort` (dialect-aware patch safety), each with a registry in `components/remediation`; the engine consumes them through its advisor. The existing implicit resolver (stack-trace) and validator (Python) are NAMED and become the first registrants. **[locked]**

```python
# components/remediation/application/ports/code_location_resolver_port.py
@dataclass(frozen=True)
class FindingEvidence:               # shaped to the core's need (C5), from Finding + attributes
    source: str                      # "cloud_posture.prowler" | "ai.log_watch" | ...
    check_id: str = ""               # scanner check, when present
    resource: CloudResourceRef | None = None   # provider/account/region/ARN/type, when present
    traceback: str = ""              # raw evidence text (log excerpt / stack trace), when present
    salient_tokens: tuple[str, ...] = ()

@dataclass(frozen=True)
class CodeLocation:
    repo: str
    path: str                        # file within the allowlisted repo
    block_address: str               # dialect-native: TF address / CFN logical id / CDK construct
                                     #   path / function or symbol name / "" for whole-file
    span: tuple[int, int] | None     # 1-based line span when known
    dialect: str                     # "hcl" | "cfn" | "python" | "generic" | ...
    confidence: str                  # "authoritative" | "matched" | "heuristic"
    evidence: str                    # human-readable why ("state address module.demo_host.aws_security_group.demo")

class CodeLocationResolverPort(ABC):
    def resolve(self, evidence: FindingEvidence, repos: RepoReader) -> list[CodeLocation]: ...

# components/remediation/application/ports/patch_validator_port.py
class PatchValidatorPort(ABC):
    dialect: str                     # registry key, matched from CodeLocation.dialect / file ext
    def validate(self, *, original_content: str, updated_content: str, path: str) -> None: ...
        # raises PatchRejected(reason_code) — the existing _REASON_STATUS → 422 surface
```

- **Resolvers registered in P1:** `StackTraceLocationResolver` — the existing
  `derive_candidate_path` traceback logic **extracted behavior-identically** from
  `LogPatchAdvisor` and locked by the existing tests (naming the implicit first instance — the
  ADR 0016 "converge the side-door" move, applied to our own engine);
  `CloudFormationLocationResolver` and `TerraformStateLocationResolver` (D2); and the
  **`RepoSearchLocationResolver`** — the universal search-based resolver (salient-token /
  resource-name search over allowlisted repo trees, any language including raw SDK scripts),
  which is the generalization of what the grounded advisor already does when the traceback path
  misses. A finding may resolve via **multiple** resolvers; results are ordered
  `authoritative > matched > heuristic`, deduped by `(repo, path, span)`, and every location
  carries `confidence` + `evidence` into the preview modal and PR body.
- **Validators registered in P1:** `PythonPatchValidator` — the existing AST +
  `patch_removes_definitions` rules, extracted as-is; `HclPatchValidator` and
  `CfnTemplatePatchValidator` (D4); and the **generic validator** (empty/noop +
  retained-line-fraction text rules) that every dialect ALSO passes through — unknown dialects get
  the generic rules alone, which is exactly what any-language patches get today. The dialect
  validators exist because of **blast-radius asymmetry**: a bad app patch fails tests in the
  customer's CI; a bad `.tf`/template patch that drops a block can destroy infrastructure at the
  next apply — so infra dialects earn stricter, structure-aware fail-closed rules.
- **Placement:** both ports + registries (`components/remediation/application/providers/`) live in
  `components/remediation` — it already owns cross-context remediation choreography (the
  reconciler, the ADR 0012 gate) and composes integrations via application-layer wiring (Rule 3 /
  C3 clean). Cloud-side resolver adapters live in
  `components/remediation/infrastructure/adapters/resolvers/`, using **integrations'
  `AwsAccountAccessPort`** for creds. Repo reads go through a thin `RepoReader` facade over
  `VcsPort.list_tree`/`get_file`, injected by the composition root — the same wiring style the
  reconciler already uses for `check_merged`.
- **Engine hookup:** the advisor inside the engine becomes the **one universal advisor**: gather
  `FindingEvidence` from the finding (per-source evidence extraction replaces the log-watch-only
  `_require_actionable_finding` gate) → run the resolver registry → choose a patch strategy (D4)
  → validate via the validator registry → the untouched preview/open/provenance path.
  `LogPatchAdvisor`'s LLM machinery (full-file rewrite, temperature 0.1, strict JSON,
  Remediation-Memory grounding block, `_is_grounded` salient-token gate) is that universal
  advisor's LLM strategy — renamed, not rewritten, behavior locked by existing tests.

Rejected placements: *a new `iac` bounded context* (a remediation silo; fails "unify before you
multiply"); *resolvers inside `cloud_posture`* (the scanner pillar is a spoke-in; tomorrow's
Checkov/KSPM findings must reuse the same resolvers); *a second `OpenIacPrUseCase`* (forbidden by
D0).

### D2 — Cloud-misconfig resolvers (the crux): per-format deterministic tiers, with the universal search resolver as the honest floor shared by ALL formats and languages. When nothing resolves: "no code mapping found + here's the guidance" — never a guess. **[locked — grounded R2/R6/R7/R8]**

| Resolver | Deterministic mapping | Confidence |
|---|---|---|
| **CloudFormation** (P1) | `DescribeStackResources(PhysicalResourceId=…)` → owning stack + logical id, **server-side, no state file** (R6); then locate the template in the allowlisted repo (template files declaring that logical id + resource type; `GetTemplate` diff as a tiebreaker). Arguably *more* deterministic than Terraform — AWS itself holds the reverse index — which is why CFN ships in P1 beside TF, not after it. | `authoritative` (stack membership is a cloud fact) |
| **Terraform-state** (P1) | Two joins (R2): read the **state backend** → build an in-memory `address ↔ id/arn` index (`resources[].instances[].attributes`, per-resource-type id property); parse repo HCL (read-only, `python-hcl2`) → `address ↔ file/block-span`. Join on the finding's `resource_uid`. Where the state lives comes from a per-workspace **`IacCodeSource`** config row (D5). | `matched` (state is customer-maintained truth) |
| **CDK-path** (P2) | Route through the CFN resolver first (a CDK resource IS a CFN resource); the synthesized template's `Metadata.aws:cdk:path` (R7) gives the construct path; repo search for the construct id anchors the source location. Location is deterministic; the *patch* is LLM-strategy with construct-anchored grounding (Python/TS source has no per-resource block grammar). | `matched` → LLM strategy |
| **Pulumi-URN** (P3) | State URN via `pulumi stack export` / Cloud REST API (R8): `urn … ::<type>::<logical-name>` ↔ physical id; repo search on logical name. | `matched` |
| **Repo-search (universal)** | The search-based resolver — salient tokens / resource names / ids / tags over allowlisted repo trees. Works for **any repo and any language**, including raw SDK provisioning scripts, SAM, and app code; it is the same grounding move the engine's Python path proved. Strong hit → `heuristic` location with the evidence shown; below threshold → no location. | `heuristic` or none |

**Failure is a first-class outcome.** When no resolver produces a location above its threshold, the
result is a **guidance card, not a guess**: the finding's card gets Prowler's remediation text +
the per-check fix snippet (R1) rendered per detected dialect + "Auto-Sec could not map this
resource to code in your connected repos (searched: …)". Mapping precision is the product's
credibility (the Wiz bar is file+line, R9); a wrong-file PR would burn trust faster than no PR.

Known Terraform hard cases, named now, tiered honestly: **modules** (the demo's own SG lives in
`modules/ec2/` behind `module.demo_host…` — the state address encodes the module path, so P1
locates blocks inside local modules); **variable indirection** (the demo's `0.0.0.0/0` literally
lives in `terraform.tfvars`, one hop from the ingress block — P1 follows a single
`var.<name>` hop to its tfvars/default assignment; deeper indirection → guidance tier, OQ3);
**workspaces/Terragrunt/remote registry modules** → P3.

### D3 — Resolver selection: a fixed ladder per finding, cheapest-authoritative first; results cached per scan cycle; the whole pipeline runs in Celery. **[locked]**

For a finding carrying a `CloudResourceRef` (cloud-misconfig evidence):

1. **CFN check (authoritative, one API call):** `DescribeStackResources(PhysicalResourceId)` — if
   the resource belongs to a stack, the CFN resolver owns it. If the stack template carries
   `aws:cdk:path` metadata, route onward to the CDK resolver (P2; until then, honest guidance:
   "managed by CDK stack X — fix in the CDK app").
2. **Terraform state match:** probe the workspace's configured `IacCodeSource` state sources for
   the `resource_uid`; a hit routes to the TF resolver.
3. **Repo content sniffing:** if neither cloud-side index claims the resource, sniff allowlisted
   repos (`.tf` files / `AWSTemplateFormatVersion` templates / `cdk.json` / `Pulumi.yaml`) to
   *suggest* the org's dialect — feeding the search resolver and the guidance card, never a patch
   by itself.
4. **Universal repo-search resolver** → else **unmapped guidance**.

Findings whose evidence is a traceback (log-watch et al.) go straight to the stack-trace resolver
with the search resolver as today's fallback — the ladder is per-evidence-type, one registry.
Resolver results are cached per `(resource_uid)` for the scan cycle — the ladder runs read-only
cloud calls and must not multiply per finding in a 400-finding scan (perf rule §7: locate/propose
runs in Celery, never in-request; the preview endpoint reads the prepared proposal exactly as
today).

### D4 — Patch strategies: deterministic per-check fix TEMPLATES for well-known checks, layered ABOVE the universal LLM-grounded advisor — one advisor, two strategies; dialect validators make both fail closed. **[locked — grounded R1/R4/R12]**

- **Strategy selection, in the one advisor:** if `(check_id, dialect)` has a registered fix
  template → template strategy; else → the universal LLM-grounded strategy (the proven engine
  path). Deterministic-before-LLM is the same discipline `derive_candidate_path` already encodes;
  it is a *strategy layer*, not a different pipeline — both strategies emit the same
  full-`updated_content` proposal into the same validator chain, preview contract, and PR path.
- **Templates.** For each P1 check (D8) the fix is mechanical and known (R12 — Checkov ships 750+
  of these): *restrict/remove an offending ingress `cidr_blocks` entry*, *add an
  `aws_s3_bucket_versioning` / `aws_s3_bucket_logging` sibling block referencing the located
  bucket*. A template = `(check_id, dialect) → transform` operating on the located block's span:
  attribute-edit archetype or additive-sibling archetype. Prowler's own
  `Remediation.Code.Terraform` / `NativeIaC` snippets (R1) are the *reference shape* each template
  is written against — not spliced verbatim, because a snippet is generic while the patch must be
  anchored to the customer's real block names/references.
- **Splice, don't round-trip.** Python has no lossless HCL formatter (R4) — so template patches
  are **text splices at the located span** producing a full `updated_content`, then re-validated:
  full-file `updated_content` keeps the existing diff/preview/commit machinery byte-identical to
  today.
- **Dialect validators** (`PatchValidatorPort`, D1) generalize the guardrail chain while keeping
  its reason codes: `HclPatchValidator` — whole-file `python-hcl2` re-parse + a
  **`patch_removes_definitions` analog**: a patch may never drop a `resource`/`module`/`data`
  block present in the original (fail closed, exactly the top-level-symbol rule);
  `CfnTemplatePatchValidator` — YAML/JSON parse + template-schema sanity (`cfn-lint`-level) + no
  logical-resource removal; `PythonPatchValidator` — today's rules unchanged. Every dialect also
  passes the generic text rules (`patch_empty_or_noop`, `patch_too_destructive` retained-line
  fraction). Same `_REASON_STATUS` → 422 surface to the preview modal.
- **LLM strategy for infra dialects (flagged, P2):** for checks without a template and for
  CDK/script dialects, the universal LLM strategy (Remediation-Memory grounding, `_is_grounded`
  gate — here: the patch must touch the located span / the resource's name tokens) runs **behind
  `feature.iac_remediation_llm` (default off)** through the identical validator chain.
- **`terraform validate` in the scanner substrate — P2, optional deepening.**
  `init -backend=false` + `validate` needs no creds/state (R5) and fits the ADR 0006 ephemeral-Job
  pattern (pinned `hashicorp/terraform` image by digest, repo tree mounted, no network). It
  upgrades "parses" to "schema-valid". **`terraform plan` is explicitly rejected** for the PR path:
  it needs backend creds + state read + provider auth, can take locks, and its blast surface
  (arbitrary providers executing) is not worth it when the PR itself is reviewed by a human and
  validated by the post-merge rescan (D7) — the customer's own CI plan on the PR is the right
  place for plan-level truth (a PR-body note tells them so).

### D5 — Consent + security: the repo allowlist is the write boundary for EVERY dialect; state access is a NEW explicit read consent (`IacCodeSource`); state is processed in memory only — never persisted, never logged; the PR carries evidence, never secrets. **[locked — grounded R3]**

- **Write consent (exists, unchanged):** any target repo — app or infra — must be on
  `VcsConnection.repo_allowlist`; same pre-API-call rejection, same `CanManageIntegrations`
  surface. octopus-infra gets allowlisted like any repo.
- **Read consent (new):** Terraform state is a secrets-bearing artifact (R3). Auto-Sec never
  discovers or trawls buckets for state. A per-workspace **`IacCodeSource`** row
  (`infrastructure/persistence/integrations/` — the `WorkspaceLogSource` template, third instance)
  names exactly what the customer consents to: `kind` (`tf_state_s3` first), `account_id`,
  `bucket/key/region` (or key prefix for workspaces), linked `VcsConnection` + repo. The
  onboarding docs ship a minimal IAM statement — `s3:GetObject` on that object ARN only — added to
  the existing audit role; CFN needs `cloudformation:DescribeStackResources` + `GetTemplate`,
  already inside the `ViewOnlyAccess`/`SecurityAudit` managed policies the role attaches.
- **State handling (hard rules):** read via the existing assume-role seam; parsed **in memory**;
  only the derived `address ↔ resource-id` index is used; the raw document is never written to
  DB/disk/logs/traces (`@sensitive_variables` on every function touching the body — the
  `SlackAlertAdapter` discipline); the index itself is per-run and discarded. `attributes` values
  other than the id property are never read — the resolver needs identity, not contents.
- **PR/preview content:** check id, severity, resource ARN/region, the diff, `CodeLocation`
  evidence, and a link back to the finding. Never state contents, never credentials, never raw
  scanner payloads (the ADR 0016 D6 world-readable standard — a repo's watchers are invisible to
  us).
- **Board provenance:** unchanged and mandatory — preview and open both record to the card exactly
  as today.

### D6 — Relationship to response actions: runtime action = reversible STOPGAP, code PR = ROOT FIX; for findings where both exist, Auto-Sec proposes the pair on the same finding, and says which is which. **[locked]**

The two frameworks already correlate by value on the same key (`finding_fingerprint` /
`task_id → fingerprint`). P1 names the relationship in product:

- When the advisor produces a patch for a finding whose check maps to a response-action kind
  (P1: the SG-ingress checks ↔ `REVOKE_SG_INGRESS`), the triage output presents **both**:
  *"Stopgap (minutes, reversible): revoke the rule in the account — will be undone by the next
  deploy. Root fix (durable): this draft PR — closes the finding permanently."* The PR body and
  the preview modal carry the pairing line (and the R10 treadmill fact — it is the best one-line
  sales pitch for the PR).
- Approving the stopgap does **not** resolve the finding (the SSOT resolves only via D7's
  merge→rescan path or the operator endpoint) — precisely because the runtime fix is expected to
  be reverted by the customer's next apply.
- No new machinery: the pairing is a read-side join at triage/preview time; each framework keeps
  its own lifecycle, sign-off posture (agent may propose both; only a human approves/executes
  either), and provenance trail.

### D7 — Lifecycle: the existing reconciler closes the loop unchanged; the post-merge rescan is the VERIFICATION; Remediation Memory captures the proven fix, whatever its dialect. **[locked]**

- Merged PR → `reconcile_applied_remediations` (predicate already source-agnostic) → finding
  resolved (`reason="remediated"`, `resolved_by="system:remediation_reconciler"`).
- **The rescan is the honesty check:** if the merge didn't actually fix the cloud (PR merged but
  not applied; wrong attribute), the next Prowler cycle re-observes and
  `FindingEntity.observed()` **auto-reopens** — already-built SSOT behavior doubling as fix
  verification. The reopen also feeds ADR 0012's "did this fix hold?" ranking signal down.
- **Remediation Memory:** the capture gate (`pr_applied=True` + resolved + sign-off posture)
  admits the diff with `language=hcl|yaml|json|python|…` and the `check_id` as a tag — the next
  finding with the same check retrieves a same-workspace proven fix as grounding (D2 of ADR 0012:
  grounds, never authorizes). This is the compounding wedge: per-tenant fix memory over *their*
  code, whatever it is written in, which no scanner vendor productizes.

### D8 — P1 check set: four Prowler checks, chosen to cover both template archetypes on both P1 dialects and to be provable on the demo repo today. **[locked]**

| Check | Why | Archetype | Demo-provable |
|---|---|---|---|
| `ec2_securitygroup_allow_ingress_from_internet_to_tcp_port_22` | The canonical open-SSH finding; pairs with `REVOKE_SG_INGRESS` (D6) | attribute-edit (restrict/remove the `0.0.0.0/0` cidr) | YES — `demo_allowed_cidrs=["0.0.0.0/0"]` on port 22 |
| `ec2_securitygroup_allow_ingress_from_internet_to_any_port` | Catches the exposed Flower dashboard (5555) — the demo's own dogfood story | attribute-edit | YES — port 5555 open |
| `s3_bucket_object_versioning` | Clean additive fix; visible diff | additive-sibling (`aws_s3_bucket_versioning` block) | YES — `reports` bucket lacks it |
| `s3_bucket_server_access_logging` | Second additive archetype; high compliance-lens value (ADR 0009 evidence) | additive-sibling (`aws_s3_bucket_logging`) | YES — neither bucket logs |

Rejected for P1 with reasons: `s3_bucket_default_encryption` (AWS default SSE makes it PASS on the
demo — nothing to prove); public-access-block checks (demo already covered); IAM access-key
rotation (the fix is an operational rotation, not a code diff — guidance tier); anything requiring
multi-resource choreography (logging *target* bucket creation is bundled into the logging template
as a named limitation: P1 targets an existing bucket or falls to guidance). Both SG checks route
through the module + one-hop variable indirection (D2) — deliberately, because that IS the demo
repo's real shape; if P1 can't patch `terraform.tfvars` it hasn't met the proving ground.

## Consequences

**Positive**
- Tom's #1 ask lands as plugins on the proven engine: the new surface is resolvers + validators +
  templates; consent, PR mechanics, preview, provenance, merge-detection, and capture are reused
  byte-identical.
- The engine's implicit smarts get NAMED seams: the stack-trace heuristic and the Python guardrails
  become the first registrants, so the next domain (KSPM manifests, Dockerfiles, another cloud) is
  resolver/validator/template-sized work — D0 makes that structural, not aspirational.
- The stopgap/root-fix pairing turns the response framework and the PR loop into one coherent story
  on a finding card — differentiated against both console-fix CSPMs and PR-only IaC scanners.
- The rescan-verified, memory-captured loop compounds per-tenant across every dialect (ADR 0012's
  wedge, now universal).
- Honest-mapping posture (confidence + evidence + guidance tier) protects trust where competitors
  overreach.

**Negative / costs**
- Cloud-side read surface grows (state object read, CFN describes) — bounded by explicit
  `IacCodeSource` consent + in-memory-only handling, but real review surface for a security product.
- Extracting the stack-trace resolver and Python validator out of the proven advisor is refactor
  risk on the flagship path — mitigated by behavior-identical extraction locked by the existing
  test suite before any new registrant lands.
- Per-dialect resolvers/validators carry per-dialect parsing fragility (HCL edge cases, template
  functions); fail-closed validation converts fragility into "no patch" rather than bad patches.
- Terraform variable indirection beyond one hop, Terragrunt, and remote modules stay unmapped until
  P3 — some real repos will land in the guidance tier at first.

## Non-goals

- **Not auto-merge / auto-apply.** Draft PR only; the customer's review + CI (their `terraform
  plan`, their test suite) stays the deploy authority. No `terraform apply` from Auto-Sec, ever,
  in this ADR.
- **Not drift detection** (state-vs-cloud diffing as a product surface — HCP/driftctl territory,
  R11). We resolve locations for remediation; a drift lens would be its own ADR.
- **Not IaC static scanning** (Checkov-style pre-deploy PR checks) — that is a future scanner
  spoke-in via `ScannerPort`, not this remediation spoke-out.
- **Not codification** of unmanaged resources (Firefly's import territory) — unmanaged resources
  get the guidance tier, "this resource isn't in your code".
- No GitLab/Bitbucket work — inherited free when ADR 0010's adapters land.

## Implementation plan (each phase ships on its own; this ADR is the spec)

**P1 — the two seams + TF/CFN resolvers + templates, proven end-to-end on the demo**
1. Extract-and-name: `CodeLocationResolverPort` + `PatchValidatorPort` + registries in
   `components/remediation`; `StackTraceLocationResolver` + `PythonPatchValidator` +
   `RepoSearchLocationResolver` extracted behavior-identically from the existing advisor/guardrails
   (locked by existing tests); the engine's advisor consumes the registries; per-source evidence
   extraction replaces the log-watch-only gate.
2. `TerraformStateLocationResolver`: state read (via `IacCodeSource` + `AwsAccountAccessPort`),
   address↔id index, HCL locate (modules + one-hop var); `HclPatchValidator`.
3. `CloudFormationLocationResolver`: `DescribeStackResources` reverse map + template locate;
   `CfnTemplatePatchValidator`.
4. Fix templates for the four D8 checks in both dialects (splice + re-parse), registered as the
   template strategy above the LLM strategy.
5. `IacCodeSource` model + CRUD in the integrations Settings surface (the `WorkspaceLogSource`
   panel pattern); minimal IAM statement documented in onboarding.
6. Demo proof: migrate octopus-infra sandbox state to an S3 backend (prereq, OQ1); allowlist the
   repo; run the loop finding→preview→draft PR→merge→rescan-resolve on the SSH/Flower/versioning
   findings; stopgap pairing visible on the SG findings (D6).
7. Tests: unit (resolver joins, ladder, each template, each validator branch, splice idempotence),
   integration (evidence routing, preview contract unchanged, consent rejections, in-memory-state
   discipline via log/DB assertions), architecture (one-engine fitness function per D0;
   remediation imports only integrations' application layer).

**P2 — breadth + LLM strategy for infra + CDK**
More checks per archetype (data-driven from real workspace findings); `feature.iac_remediation_llm`
LLM strategy for infra dialects under the validator chain; `terraform validate` ephemeral Job (R5,
flagged); `CdkPathLocationResolver` (CFN tier + `aws:cdk:path` + construct-anchored LLM patches);
multi-repo / multi-state-source resolution; delivery-channel notification on PR opened (ADR 0016
`draft_pr_opened` — free).

**P3 — long tail**
`PulumiUrnLocationResolver`; Terragrunt / remote registry modules / deep variable chains;
state-backend variants (Terraform Cloud API, GitLab-managed state); SAM; per-check fix-template
contribution loop from Remediation Memory stats (which template fixes hold, which get reverted).

## Open questions (for Henry)

1. **Demo state backend:** OK to migrate the octopus-infra sandbox to an S3 backend as the P1
   prerequisite (`terraform init -migrate-state`, one-time, also removes plaintext state from the
   laptop/repo dir — an improvement it needs regardless)?
2. **CFN proof target:** does the demo account have any live CFN stack (the onboarding template is
   Terraform-provisioned there)? If not, ship a tiny deliberately-misconfigured demo stack to prove
   the CFN resolver end-to-end?
3. **Variable-indirection depth:** P1 follows one `var.` hop (which covers the demo's tfvars case).
   Enough for the first real customers, or invest in full expression tracing earlier?
4. **Stopgap auto-pairing:** should the response-action proposal be auto-created beside every SG
   code PR (agent-proposed, human-gated as today), or only surfaced as a suggestion the operator
   clicks?
5. **Commit identity for infra repos:** infra PRs are higher-blast-radius than app-code PRs —
   default `commit_identity=operator` (approving human as author) for connections whose allowlist
   contains an infra repo, or keep `pat_owner` and leave it to the customer?
6. **Naming:** `IacCodeSource` vs folding state-location config into `VcsConnection` (kept separate
   here because one repo can have N states and the consent objects differ — but it is one more
   Settings row).

[^prowler-meta]: Prowler check metadata model (`Remediation.Code`: NativeIaC / Terraform / CLI / Other; `Recommendation`) — https://github.com/prowler-cloud/prowler/blob/master/prowler/lib/check/models.py ; reporting fields (`REMEDIATION_CODE_TERRAFORM`, `REMEDIATION_CODE_NATIVEIAC`) — https://docs.prowler.com/user-guide/cli/tutorials/reporting ; custom check metadata tutorial — https://docs.prowler.com/projects/prowler-open-source/en/latest/tutorials/custom-checks-metadata/
[^tf-mapping]: Firefly — asset↔IaC/state mapping + codification: https://docs.firefly.ai/key-features/cloud-asset-inventory , https://docs.firefly.ai/detailed-guides/codification ; ControlMonkey, "Is your AWS resource Terraformed" (physical-id → per-type id-property mapping): https://controlmonkey.io/blog/is-your-aws-resource-terraformed/ ; driftctl (scans cloud vs state, all backend types; maintenance mode): https://seifrajhi.github.io/blog/drift-detecting-in-terraform/
[^tf-state-sec]: Terraform state security — secrets in state, read-only backend IAM, minimum exposure, audit: https://cycode.com/blog/secrets-in-terraform/ , https://oneuptime.com/blog/post/2026-02-23-how-to-use-read-only-state-access-in-terraform/view , https://www.firefly.ai/academy/secret-management-in-terraform-keeping-sensitive-data-out-of-state-files
[^hcl-tools]: hclwrite (surgical HCL edits, Go): https://husin.dev/terraform-hclwrite/ ; python-hcl2 (writer added 2024; parse-oriented): https://pypi.org/project/python-hcl2 , https://nklya.medium.com/how-to-write-hcl2-from-python-53ac12e45874
[^tf-validate]: `terraform validate` without creds (`init -backend=false`): https://github.com/hashicorp/terraform/issues/15811 , https://spacelift.io/blog/terraform-validate , https://developer.hashicorp.com/terraform/language/backend
[^cfn-map]: `DescribeStackResources` — physical-id → stack + logical id ("pass the EC2 InstanceId … to find which stack the instance belongs to"): https://docs.aws.amazon.com/AWSCloudFormation/latest/APIReference/API_DescribeStackResources.html ; PhysicalResourceId semantics: https://innablr.com.au/blog/physicalresourceid-in-cloudformation/
[^cdk-path]: CDK `aws:cdk:path` template metadata (construct path per resource): https://docs.aws.amazon.com/cdk/v2/guide/cli.html , https://github.com/aws/aws-cdk/issues/16964
[^pulumi]: Pulumi URN format + `pulumi stack export` (URN ↔ physical id): https://www.pulumi.com/docs/iac/concepts/resources/names/ , https://www.pulumi.com/docs/reference/cloud-rest-api/stacks/
[^wiz]: Wiz Code — cloud-to-code: live resource → module/file/line/author, targeted PR at the source: https://www.wiz.io/platform/wiz-code , https://www.wiz.io/blog/wiz-hcp-terraform-close-the-cloud-security-gap
[^checkov]: Checkov (750+ policies) + Prisma Cloud fixes/Smart Fixes + drift PRs in HCL: https://www.checkov.io/1.Welcome/What%20is%20Checkov.html , https://www.prismacloud.io/prisma/cloud/infrastructure-as-code-security , https://scalr.com/learning-center/bridgecrew-terraform-pricing-use-cases-best-practices-alternatives
[^cspm-cycle]: The console-fix-reopens treadmill — CSPM remediation must land in IaC: https://www.decryptiondigest.com/blog/cspm-findings-remediation-workflow ; CSPM shift-left context: https://orca.security/resources/blog/best-cspm-tools/
[^hcp-drift]: HCP Terraform health assessments — refresh-only plans against state as the drift substrate: https://developer.hashicorp.com/terraform/cloud-docs/workspaces/health , https://spacelift.io/blog/terraform-cloud-drift-detection
