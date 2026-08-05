# ADR 0017 — Cloud-misconfiguration remediation via VCS: Prowler finding → grounded IaC patch → draft PR (format-agnostic; Terraform + CloudFormation first)

Status: Proposed (2026-08-05) — design only; the build follows this spec.

Relates to: **ADR 0010** (`VcsPort` / `VcsConnection` / repo-allowlist — the draft-PR loop this ADR
extends, never forks), **ADR 0012** (Remediation Memory — the capture/retrieval loop a merged IaC fix
feeds), **ADR 0008 / ADR 0016** (the port + per-workspace-config + registry template, applied here a
**fourth** time — to IaC *formats* instead of providers/channels), **ADR 0004** (Finding SSOT +
`AssetUrn` correlation-by-value), **ADR 0006** (scanner-execution substrate — the ephemeral-Job home
for any future `terraform validate` step), **ADR 0013** (contextual risk — ranks which finding
deserves the PR first), the **response-action framework** (`components/response` —
propose/approve/execute/rollback; the *runtime stopgap* this ADR pairs with the *root fix*), and
Tom's operator feedback: **remediation → IaC PR is his #1-ranked build gap** — fix the misconfig at
its source of truth, not in the console.

Henry's scoping correction (2026-08-04, supersedes the Terraform-only framing): *the remediation
target is "wherever the customer's infra is defined in any VCS-integrated repo" — Terraform,
CloudFormation, CDK, Pulumi, SAM, or raw AWS-SDK provisioning scripts. Terraform is only the FIRST
adapter, exactly like GitHub is the first `VcsPort` provider and S3 the first `LogSourcePort`
adapter.*

## Context

Auto-Sec already closes the loop for **application-code** findings: a log-watch finding is triaged,
`LogPatchAdvisor` grounds a patch against the actual repo file, deterministic guardrails validate it,
`OpenDraftPrUseCase` opens a draft PR on an allowlisted repo, the merge-detection reconciler
auto-resolves the finding when the PR merges, and Remediation Memory captures the proven fix. The
**cloud-posture** pillar has everything *except* that last mile: Prowler findings land on the board
with remediation *text*, and the only actionable machinery is the runtime response action
(`REVOKE_SG_INGRESS`) — which fixes the *cloud*, not the *code*. A console/runtime fix to
IaC-managed infra is undone on the next deploy; the finding reopens; counts never go down. This
"remediation treadmill" is the single most-documented failure mode of CSPM programs[^cspm-cycle],
and it is exactly Tom's ask: he ships infra from code, so the fix must land in code.

The competitive bar is set: Wiz maps every live resource back to "the exact module, file, line of
code, and author that defined it" and opens a targeted PR at the source[^wiz]; Prisma Cloud
(Bridgecrew) detects drift and raises automatic PRs fixing the drifted HCL[^checkov]. Nobody in the
"security team you don't hire" price class does this — it is wedge territory, but only if the
mapping is honest (see D2's fallback tier).

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
**Everything a mapper needs — ARN, region, account, check id — is already on the finding.**

**2. The draft-PR loop to reuse (this ADR is a composition, not a rewrite).**
`components/integrations/application/use_cases/open_draft_pr_use_case.py::OpenDraftPrUseCase` is
the single choke point: ordered gates (`_require_connection` → `_require_allowlisted_repo` →
actionable-finding → idempotency → capability → token), then `create_branch` / `commit_file` /
`open_draft_pr` through `VcsPort` (ADR 0010; GitHub adapter proven end-to-end on a real dogfood
PR). `preview(...)` runs the **identical** validation path with zero writes and returns the
frontend's modal contract (`DraftPrPreviewResource`: `path`, unified `diff` ≤ 12k chars,
`change_summary`, `grounding[]`, `repo`, `already_opened`, `pr_url`). Guardrails
(`log_patch_advisor_service.py::validate_patch`) are deterministic and ordered:
`patch_empty_or_noop` → `patch_does_not_parse` (`.py` AST) → `patch_removes_definitions`
(top-level symbol drop = fail closed) → `patch_too_destructive` (any file shrunk below 40 % of
non-blank lines). The consent boundary is `VcsConnection.repo_allowlist`
(`infrastructure/persistence/integrations/models.py` — a repo not listed is rejected before any
API call). Provenance is recorded on the board card (`record_draft_pr` → payload patch + card
comment + provenance event + owner notification) — the "every AI action posts to the board" hard
rule. **Two things are log-watch-specific today and must be generalized, not duplicated:** the
actionable-finding gate is source-gated to `ai.log_watch`, and the only patch advisor is
`LogPatchAdvisor` (full-file LLM rewrite grounded by traceback-derived paths + Remediation-Memory
priors, `_is_grounded` salient-token check).

**3. The lifecycle machinery already in place.** `components/remediation/` owns the merge-detection
reconciler (`reconcile_applied_remediations` — candidate predicate is *already source-agnostic*:
any board Task carrying `payload.draft_pr`), wired via injected callables to integrations'
`CheckPullRequestMergedUseCase` (allowlist-enforced, fails closed to `merged=False`), project's
resolve-finding use case (`resolved_by="system:remediation_reconciler"`), and ADR 0012's
`capture_remediation_if_gated` entry gate. A merged IaC PR flows through this **unchanged**.

**4. The runtime counterpart.** `components/response/` implements
propose (reversible, agent-ok, `dry_run=True` default) → approve (human-only, justification
required) → execute → rollback, linked to the finding **by value** via `finding_fingerprint`
(C4-clean). Its only kind today, `REVOKE_SG_INGRESS`, targets exactly the security-group findings
in this ADR's P1 set — the stopgap/root-fix pairing (D6) is sitting there waiting to be named.

**5. Credentials.** `AwsRoleCredentialsPort` / `AwsAccountAccessPort`
(`components/integrations/application/ports/`) are the single STS token-vending seam (assume-role +
ExternalId, secrets never in argv/logs) that already feeds Prowler Jobs (ADR 0006). Any cloud-side
read the mapper needs (state object, `DescribeStackResources`) uses the same seam.

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
  sits beside the code. The Terraform mapping tier (D2) reads a state *backend*, so P1 carries a
  named prerequisite: migrate the sandbox to an S3 backend (`terraform init -migrate-state`) — a
  boy-scout improvement octopus-infra needs anyway.
- **CFN proof target:** Auto-Sec's own AWS onboarding provisions the audit role via a
  CloudFormation template/StackSet in customer accounts — the demo's role is Terraform-provisioned,
  so whether the demo account holds any live CFN stack to prove the CFN adapter against is an open
  question (OQ2); creating a tiny deliberately-misconfigured stack is a 10-minute fallback.

### Why format-agnostic is the design, not a generalization for taste

The mapping and patching problem is **per-dialect** (state files vs stack APIs vs synthesized
metadata; HCL vs JSON/YAML vs Python), but everything around it — consent, PR mechanics, preview,
guardrail philosophy, lifecycle, memory — is **format-invariant** and already built. That is
precisely the shape ADR 0008 (log sources), ADR 0010 (VCS providers), and ADR 0016 (delivery
channels) solved three times: a port shaped to the core's need, per-X adapters, a registry, honest
fallbacks. Designing Terraform-only would guarantee a copy-paste second pipeline the day a CDK
customer shows up — the exact anti-pattern `improve-dont-replicate.md` names.

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
| R11 | Drift detection at HashiCorp itself = periodic **refresh-only plans against state** (health assessments) — state access is the canonical substrate for cloud↔code comparison, validating the state-read tier | HCP Terraform docs[^hcp-drift] |
| R12 | Deterministic per-check fixes are the industry shape for the head of the distribution: Checkov's 750+ policies with auto-generated "fixed code" / Smart Fixes; LLMs are the tail, not the default | Checkov/Prisma docs[^checkov] |

## Decisions (LOCKED)

### D1 — The seam: an `IacFormatPort` + per-format adapters + registry in `components/remediation`; ONE `IacRemediationAdvisor` plugged into the existing `OpenDraftPrUseCase` via a source-routed advisor seam. No parallel PR path — ever. **[locked]**

The fourth application of the house template (ADR 0008/0010/0016), pointed at IaC *dialects*:

```python
# components/remediation/application/ports/iac_format_port.py
@dataclass(frozen=True)
class CloudResourceRef:            # shaped to the core's need (C5), from Finding.attributes
    provider: str                  # "aws"
    account_id: str
    region: str
    resource_uid: str              # the ARN
    resource_type: str

@dataclass(frozen=True)
class IacCodeLocation:
    repo: str
    path: str                      # file within the allowlisted repo
    block_address: str             # dialect-native: TF address / CFN logical id / CDK construct path
    span: tuple[int, int]          # 1-based line span of the located block
    confidence: str                # "authoritative" | "matched" | "heuristic"
    evidence: str                  # human-readable why ("state address module.demo_host.aws_security_group.demo")

@dataclass(frozen=True)
class IacPatchProposal:
    path: str
    updated_content: str           # full file after the anchored splice (verifiable, diffable)
    change_summary: str
    fix_kind: str                  # "template:<check_id>" | "llm"

class IacFormatPort(ABC):
    def locate(self, ref: CloudResourceRef, repo_reader: RepoReader) -> IacCodeLocation | None: ...
    def propose_patch(self, facts: IacFindingFacts, location: IacCodeLocation,
                      content: str) -> IacPatchProposal | None: ...
    def validate_patch(self, *, original_content: str, updated_content: str, path: str) -> None: ...
```

- **Adapters** live in `components/remediation/infrastructure/adapters/iac/` —
  `TerraformFormatAdapter` and `CloudFormationFormatAdapter` in P1, `CdkFormatAdapter` (P2),
  `PulumiFormatAdapter` (P3). Each owns (a) resource→code **mapping** for its dialect and (b) patch
  **generation + syntax validation** for its dialect. The registry
  (`components/remediation/application/providers/iac_format_provider.py`) is the composition root,
  mirroring `VcsProvider` / `LogSourceProvider`, flag-gating nascent adapters
  (`feature.iac_remediation_cfn` etc., default off, fail closed).
- **Cloud-side reads** (state object, `DescribeStackResources`) are driven adapters inside
  remediation infrastructure using **integrations' `AwsAccountAccessPort`** for creds — the same
  assume-role seam Prowler scans use; no new credential path.
- **Repo-side reads** reuse `VcsPort.list_tree` / `get_file` through a thin `RepoReader` facade
  injected by the composition root — the same cross-context wiring style the reconciler already
  uses for `check_merged` (remediation composes integrations' *application* surface, never its
  infrastructure — Rule 3 / C3 clean).
- **The advisor seam**: integrations' `OpenDraftPrUseCase._prepare_validated_proposal` is today
  hard-wired to `LogPatchAdvisor`. P1 introduces a `FindingPatchAdvisorPort` in
  `components/integrations/application/ports/` (given finding facts + repo access, return a
  validated proposal + grounding) and a **source-family route**: `ai.log_watch` → the existing
  `LogPatchAdvisor` (unchanged behavior), `cloud_posture.*` → remediation's
  **`IacRemediationAdvisor`** (application service: detect format (D3) → locate (D2) → propose
  (D4) → validate). The log-watch-only `_require_actionable_finding` gate widens to a per-source
  policy the same way. Preview, idempotency, allowlist, capability gates, provenance recording,
  and the reconciler are **inherited untouched** — this is the whole point.

Rejected placements: *a new `iac` bounded context* (a third remediation silo; the `remediation`
context already owns cross-context remediation choreography and the ADR 0012 gate — "unify before
you multiply"); *format adapters inside `cloud_posture`* (the scanner pillar is a spoke-in; patching
repos is remediation, and tomorrow's Checkov/KSPM findings must reuse the same adapters);
*a second `OpenIacPrUseCase`* (the forbidden parallel PR path — one choke point keeps consent,
idempotency, provenance and guardrails single-sourced).

### D2 — Mapping (the crux): per-format deterministic tiers, plus ONE honest fallback tier shared by all formats. When mapping fails: "no code mapping found + here's the guidance" — never a guess. **[locked — grounded R2/R6/R7/R8]**

| Format | Deterministic mapping | Confidence |
|---|---|---|
| **CloudFormation** | `DescribeStackResources(PhysicalResourceId=…)` → owning stack + logical id, **server-side, no state file** (R6); then locate the template in the allowlisted repo (template files declaring that logical id + resource type; `GetTemplate` diff as a tiebreaker). Arguably *more* deterministic than Terraform — AWS itself holds the reverse index — which is why CFN ships in P1 beside TF, not after it. | `authoritative` (stack membership is a cloud fact) |
| **Terraform** | Two joins (R2): read the **state backend** → build an in-memory `address ↔ id/arn` index (`resources[].instances[].attributes`, per-resource-type id property); parse repo HCL (read-only, `python-hcl2`) → `address ↔ file/block-span`. Join on the finding's `resource_uid`. Where the state lives comes from a per-workspace **`IacCodeSource`** config row (D5). | `matched` (state is customer-maintained truth) |
| **CDK** (P2) | Route through the CFN tier first (a CDK resource IS a CFN resource); the synthesized template's `Metadata.aws:cdk:path` (R7) gives the construct path; repo search for the construct id anchors the source location. Location is deterministic; the *patch* is LLM-tier with construct-anchored grounding (Python/TS source has no per-resource block grammar). | `matched` → patch via LLM tier |
| **Pulumi** (P3) | State URN via `pulumi stack export` / Cloud REST API (R8): `urn … ::<type>::<logical-name>` ↔ physical id; repo search on logical name. | `matched` |
| **Raw SDK scripts / SAM / anything else** | **No deterministic mapping exists** — this is the honest tier: the same grounded-repo-search approach the log-watch advisor uses for app code (search allowlisted repos for the resource name/id/tag strings; if a strong hit, offer it as `heuristic` with the evidence shown; below threshold, no patch). | `heuristic` or none |

**Failure is a first-class outcome.** When no tier produces a location above its threshold, the
result is a **guidance card, not a guess**: the finding's card gets Prowler's remediation text +
the per-check fix snippet (R1) rendered per detected format + "Auto-Sec could not map this
resource to code in your connected repos (searched: …)". Mapping precision is the product's
credibility (the Wiz bar is file+line, R9); a wrong-file PR would burn trust faster than no PR.
`IacCodeLocation.confidence` + `evidence` flow into the preview modal and the PR body so the
operator always sees *why* Auto-Sec believes this is the file.

Known Terraform hard cases, named now, tiered honestly: **modules** (the demo's own SG lives in
`modules/ec2/` behind `module.demo_host…` — the state address encodes the module path, so P1
locates blocks inside local modules); **variable indirection** (the demo's `0.0.0.0/0` literally
lives in `terraform.tfvars`, one hop from the ingress block — P1 follows a single
`var.<name>` hop to its tfvars/default assignment; deeper indirection → guidance tier, OQ3);
**workspaces/Terragrunt/remote registry modules** → P3.

### D3 — Format detection: a fixed ladder per finding, CFN stack membership authoritative first. **[locked]**

Given a finding's `CloudResourceRef` + the workspace's allowlisted repos and `IacCodeSource` rows:

1. **CFN check (authoritative, one API call):** `DescribeStackResources(PhysicalResourceId)` — if
   the resource belongs to a stack, the CFN adapter owns it. If the stack template carries
   `aws:cdk:path` metadata, route onward to the CDK adapter (P2; until then, honest guidance:
   "managed by CDK stack X — fix in the CDK app").
2. **Terraform state match:** probe the workspace's configured state sources for the
   `resource_uid`; a hit routes to the TF adapter.
3. **Repo content sniffing:** if neither cloud-side index claims the resource, sniff allowlisted
   repos (`.tf` files / `template.y(a)ml` + `AWSTemplateFormatVersion` / `cdk.json` /
   `Pulumi.yaml`) to *suggest* which dialect the org uses — feeding tier 4's search and the
   guidance card, never a patch by itself.
4. **Generic grounded fallback** (D2's last tier) → else **unmapped guidance**.

Detection results are cached per `(resource_uid)` for the scan cycle — the ladder runs read-only
cloud calls and must not multiply per finding in a 400-finding scan (perf rule §7: the whole
locate/propose pipeline runs in Celery, never in-request; the preview endpoint reads the already-
prepared proposal path just as it does today).

### D4 — Patch generation: deterministic per-check fix templates for the P1 check set, applied as anchored splices at the located block and re-validated by parse; the LLM is a flagged fallback tier under the SAME guardrail chain, never the default. **[locked — grounded R1/R4/R12]**

- **Templates first.** For each P1 check (D8) the fix is mechanical and known (R12 — Checkov ships
  750+ of these): *restrict/remove an offending ingress `cidr_blocks` entry*, *add an
  `aws_s3_bucket_versioning` / `aws_s3_bucket_logging` sibling block referencing the located
  bucket*. A template = `(check_id, dialect) → transform` operating on the located block's span:
  attribute-edit archetype (rewrite one attribute inside the span) or additive-sibling archetype
  (insert a new block after the span, address-referencing the located resource). Prowler's own
  `Remediation.Code.Terraform` / `NativeIaC` snippets (R1) are the *reference shape* each template
  is written against — not spliced verbatim, because a snippet is generic while the patch must be
  anchored to the customer's real block names/references.
- **Splice, don't round-trip.** Python has no lossless HCL formatter (R4) — so patches are **text
  splices at the located span** producing a full `updated_content`, then re-validated: TF →
  `python-hcl2` re-parse of the whole file; CFN → YAML/JSON parse + template-schema sanity
  (`cfn-lint` level checks); both → the format-generalized guardrails below. Full-file
  `updated_content` keeps the existing diff/preview/commit machinery byte-identical to today.
- **Guardrails generalize, not fork.** `validate_patch` grows format-aware branches while keeping
  its chain and reason codes: `patch_does_not_parse` (HCL/YAML/JSON parse per dialect, `.py`
  AST as today), a **`patch_removes_definitions` analog per dialect** — a TF patch may never drop a
  `resource`/`module`/`data` block present in the original; a CFN patch may never drop a logical
  resource — fail closed, exactly the top-level-symbol rule; `patch_too_destructive`
  (retained-line fraction) is already format-agnostic and stays. Same `_REASON_STATUS` → 422
  surface to the preview modal.
- **LLM tier (flagged, P2):** for checks without a template and for CDK/script dialects, the
  existing advisor pattern (full-file rewrite, temperature 0.1, strict JSON, Remediation-Memory
  grounding block, `_is_grounded` salient-token gate — here: the patch must touch the located
  span / the resource's name tokens) runs **behind `feature.iac_remediation_llm` (default off)**
  and through the identical guardrail chain. Deterministic-before-LLM is the same discipline
  `derive_candidate_path` already encodes.
- **`terraform validate` in the scanner substrate — P2, optional deepening.**
  `init -backend=false` + `validate` needs no creds/state (R5) and fits the ADR 0006 ephemeral-Job
  pattern (pinned `hashicorp/terraform` image by digest, repo tree mounted, no network). It
  upgrades "parses" to "schema-valid". **`terraform plan` is explicitly rejected** for the PR path:
  it needs backend creds + state read + provider auth, can take locks, and its blast surface
  (arbitrary providers executing) is not worth it when the PR itself is reviewed by a human and
  validated by the post-merge rescan (D7) — the customer's own CI plan on the PR is the right
  place for plan-level truth (a PR-body note tells them so).

### D5 — Consent + security: the repo allowlist is the write boundary; state access is a NEW explicit read consent (`IacCodeSource`); state is processed in memory only — never persisted, never logged; the PR carries evidence, never secrets. **[locked — grounded R3]**

- **Write consent (exists):** the infra repo must be on `VcsConnection.repo_allowlist` — the same
  boundary, same pre-API-call rejection, same `CanManageIntegrations` surface. Nothing new to
  build; octopus-infra gets allowlisted like any repo.
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
  other than the id property are never read — the mapper needs identity, not contents.
- **PR/preview content:** check id, severity, resource ARN/region, the diff, `IacCodeLocation`
  evidence, and a link back to the finding. Never state contents, never credentials, never raw
  scanner payloads (the ADR 0016 D6 world-readable standard — a repo's watchers are invisible to
  us).
- **Board provenance:** unchanged and mandatory — preview and open both record to the card exactly
  as the log-watch path does today.

### D6 — Relationship to response actions: runtime action = reversible STOPGAP, IaC PR = ROOT FIX; for findings where both exist, Auto-Sec proposes the pair on the same finding, and says which is which. **[locked]**

The two frameworks already correlate by value on the same key (`finding_fingerprint` /
`task_id → fingerprint`). P1 names the relationship in product:

- When the IaC advisor produces a patch for a finding whose check maps to a response-action kind
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

### D7 — Lifecycle: the existing reconciler closes the loop unchanged; the post-merge Prowler rescan is the VERIFICATION; Remediation Memory captures the proven IaC fix. **[locked]**

- Merged PR → `reconcile_applied_remediations` (predicate already source-agnostic) → finding
  resolved (`reason="remediated"`, `resolved_by="system:remediation_reconciler"`).
- **The rescan is the honesty check:** if the merge didn't actually fix the cloud (PR merged but
  not applied; wrong attribute), the next Prowler cycle re-observes and
  `FindingEntity.observed()` **auto-reopens** — already-built SSOT behavior doubling as fix
  verification. The reopen also feeds ADR 0012's "did this fix hold?" ranking signal down.
- **Remediation Memory:** the capture gate (`pr_applied=True` + resolved + sign-off posture)
  admits the `.tf`/template diff with `language=hcl|yaml|json` and the `check_id` as a tag — the
  next finding with the same check retrieves a same-workspace proven fix as grounding (D2 of ADR
  0012: grounds, never authorizes). This is the compounding wedge: per-tenant fix memory over
  *their* infra dialect, which no scanner vendor productizes.

### D8 — P1 check set: four Prowler checks, chosen to cover both patch archetypes on both P1 dialects and to be provable on the demo repo today. **[locked]**

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
- Tom's #1 ask lands as a composition: ~everything hard (consent, PR mechanics, preview, provenance,
  merge-detection, capture) is reused; the new surface is the mapper + templates + one advisor seam.
- The fourth registry-template application: CDK/Pulumi/SAM become adapter-sized work, not pipelines.
- The stopgap/root-fix pairing turns the response framework and the PR loop into one coherent story
  on a finding card — differentiated against both console-fix CSPMs and PR-only IaC scanners.
- The rescan-verified, memory-captured loop compounds per-tenant (ADR 0012's wedge, now for infra).
- Honest-mapping posture (confidence + evidence + guidance tier) protects trust where competitors
  overreach.

**Negative / costs**
- Cloud-side read surface grows (state object read, CFN describes) — bounded by explicit
  `IacCodeSource` consent + in-memory-only handling, but real review surface for a security product.
- Per-dialect adapters carry per-dialect parsing fragility (HCL edge cases, template functions);
  fail-closed validation converts fragility into "no patch" rather than bad patches.
- The advisor-seam refactor touches the proven log-watch path — mitigated by keeping
  `LogPatchAdvisor` behavior-identical behind the new port and locking it with the existing tests.
- Terraform variable indirection beyond one hop, Terragrunt, and remote modules stay unmapped until
  P3 — some real repos will land in the guidance tier at first.

## Non-goals

- **Not auto-merge / auto-apply.** Draft PR only; the customer's review + CI (their `terraform
  plan`) stays the deploy authority. No `terraform apply` from Auto-Sec, ever, in this ADR.
- **Not drift detection** (state-vs-cloud diffing as a product surface — HCP/driftctl territory,
  R11). We map for remediation; a drift lens would be its own ADR.
- **Not IaC static scanning** (Checkov-style pre-deploy PR checks) — that is a future scanner
  spoke-in via `ScannerPort`, not this remediation spoke-out.
- **Not codification** of unmanaged resources (Firefly's import territory) — unmanaged resources
  get the guidance tier, "this resource isn't in your code".
- No GitLab/Bitbucket work — inherited free when ADR 0010's adapters land.

## Implementation plan (each phase ships on its own; this ADR is the spec)

**P1 — TF + CFN adapters, template fixes, proven end-to-end on the demo**
1. `FindingPatchAdvisorPort` + source-family routing in `OpenDraftPrUseCase`/`preview`
   (log-watch behavior-identical, locked by existing tests); widen the actionable-finding gate
   per-source.
2. `IacFormatPort` + `IacFormatProvider` + `IacRemediationAdvisor` in `components/remediation`;
   `RepoReader` facade over `VcsPort`; detection ladder (D3) with per-cycle caching, all under
   Celery.
3. `TerraformFormatAdapter`: state read (via `IacCodeSource` + `AwsAccountAccessPort`),
   address↔id index, HCL locate (modules + one-hop var), the two SG + two S3 templates, splice +
   re-parse validation; format-generalized `validate_patch` branches.
4. `CloudFormationFormatAdapter`: `DescribeStackResources` reverse map, template locate in repo,
   NativeIaC-shaped templates for the same four checks, YAML/JSON validation.
5. `IacCodeSource` model + CRUD in the integrations Settings surface (the `WorkspaceLogSource`
   panel pattern); minimal IAM statement documented in onboarding.
6. Demo proof: migrate octopus-infra sandbox state to an S3 backend (prereq, OQ1); allowlist the
   repo; run the loop finding→preview→draft PR→merge→rescan-resolve on the SSH/Flower/versioning
   findings; stopgap pairing visible on the SG findings (D6).
7. Tests: unit (mapper joins, detection ladder, each template, guardrail branches, splice
   idempotence), integration (advisor routing, preview contract unchanged, consent rejections,
   in-memory-state discipline via log/DB assertions), architecture (remediation imports only
   integrations' application layer).

**P2 — breadth + LLM tier + CDK**
More checks per archetype (data-driven from real workspace findings); `feature.iac_remediation_llm`
fallback tier under the guardrail chain; `terraform validate` ephemeral Job (R5, flagged);
`CdkFormatAdapter` (CFN tier + `aws:cdk:path` + construct-anchored LLM patches); multi-repo /
multi-state-source resolution; delivery-channel notification on IaC PR opened (ADR 0016
`draft_pr_opened` — free).

**P3 — long tail**
Pulumi adapter (URN); Terragrunt / remote registry modules / deep variable chains; state-backend
variants (Terraform Cloud API, GitLab-managed state); SAM; per-check fix-template contribution
loop from Remediation Memory stats (which template fixes hold, which get reverted).

## Open questions (for Henry)

1. **Demo state backend:** OK to migrate the octopus-infra sandbox to an S3 backend as the P1
   prerequisite (`terraform init -migrate-state`, one-time, also removes plaintext state from the
   laptop/repo dir — an improvement it needs regardless)?
2. **CFN proof target:** does the demo account have any live CFN stack (the onboarding template is
   Terraform-provisioned there)? If not, ship a tiny deliberately-misconfigured demo stack to prove
   the CFN adapter end-to-end?
3. **Variable-indirection depth:** P1 follows one `var.` hop (which covers the demo's tfvars case).
   Enough for the first real customers, or invest in full expression tracing earlier?
4. **Stopgap auto-pairing:** should the response-action proposal be auto-created beside every SG
   IaC PR (agent-proposed, human-gated as today), or only surfaced as a suggestion the operator
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
