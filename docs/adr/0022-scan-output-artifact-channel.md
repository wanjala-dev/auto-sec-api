# ADR 0022 — Scan-Output Artifact Channel

Status: Accepted (2026-08-09)
Relates to: **ADR 0006 (Scanner Execution Substrate)** — this ADR resolves the follow-up
its D4 named ("K8s-Prowler output should move to a shared-`emptyDir`/object-store
transport — pod-log stdout truncates large outputs") and **supersedes that follow-up
note only**; ADR 0006's decisions A–D stand unchanged. Also relates to ADR 0004 (the
CNAPP `ScannerPort` spine), ADR 0009 (compliance evidence), ADR 0019 (SAST pillar).

## Context

### The failure

Raw scanner output travels from an ephemeral scan Job to the trusted worker on exactly
one channel: **the pod's stdout, read back through the kubelet log API**. That channel
has a size ceiling, and crossing it does not raise — it silently returns less than was
written.

Each pillar adapter then parsed that output *defensively*, returning `[]` / `{}` when the
JSON did not parse. Combined with an exit code of **0** — which a truncated-but-successful
engine run genuinely has — the result was a **COMPLETED `ScanRun` with zero findings over
a mutilated scan**: a customer's cloud account reported clean because its output was cut
off.

This is the worst failure mode a security product can have, and it **scales the wrong
way**: the largest, most valuable estates emit the most output and truncate first. A
customer's first real scan is the one most likely to lie.

### Measured evidence

Everything below was measured on the running system on 2026-08-09, not inferred.

| Fact | Value | Method |
|---|---|---|
| kubelet `containerLogMaxSize` | **10Mi** — the default, not overridden anywhere in `auto-sec-infra` | `kubectl get --raw /api/v1/nodes/docker-desktop/proxy/configz` |
| kubelet `containerLogMaxFiles` | 5 | same |
| Prowler scan of our **demo** AWS account (near-empty) | **3,980,099 bytes (3.98 MB)** | `kubectl -n autosec logs <prowler pod>` |
| Synthetic Job emitting 15.91 MiB of well-formed JSON, read back through the production code path | **round-tripped intact — no truncation** | k8s python client, `_preload_content=False`, executed from the `scanning-worker` pod |

The last row matters, and it corrects a naive reading of the problem.

**The local cluster cannot reproduce the bug.** Docker Desktop runs
`cri-dockerd` (`containerRuntimeEndpoint = unix:///var/run/cri-dockerd.sock`) with
Docker's `json-file` logging driver, which has **no default size cap**. Under
cri-dockerd, kubelet's `containerLogMaxSize` does not govern container logs at all — so
15.91 MiB passed through untouched.

**Production is a different runtime.** `auto-sec-infra/terraform` pins k3s
`v1.36.3+k3s1`, which uses **containerd**, where kubelet *does* enforce
`containerLogMaxSize`; and its cloud-init sets no kubelet log override. Per the
Kubernetes logging documentation, once rotation occurs `kubectl logs` returns at most the
current file — "if a Pod writes 40 MiB of logs and the kubelet rotates logs after 10 MiB,
running `kubectl logs` returns at most 10MiB of data."

So the honest verdict is **worse than "the review was right"**:

> The truncation is real in production, and **structurally invisible in development**.
> Our demo account already consumes 40% of the production budget. No amount of local
> testing would have caught it.

### Why not simply raise the limit

Raising `containerLogMaxSize` is a number, and a number is exceeded by a larger customer.
It also spends a node-wide, all-workloads setting to solve one workload's problem, and it
leaves every other property of the pod-log channel untouched: whole output buffered in
worker RAM, no replay, no debugging artifact, no evidence copy. It converts a certain
failure into a deferred one. That is the shortcut this ADR rejects.

## Decision

### D1 — Unusable engine output is a FAILED scan, never a clean one (shipped)

Independent of transport, and shipped first because it is the actual safety property:
**the pipeline must never report zero findings from output it cannot trust.**

Document-integrity validation lives in ONE place —
`components/scanning/domain/engine_output.py` — rather than three per-engine heuristics.
It relies on a property all three engines share: each returns its result as a **single
self-delimiting JSON document** (Prowler a top-level OCSF array; Trivy and Opengrep an
envelope object). **A truncated document cannot parse.** That makes "did it parse?" a
genuine completeness signal rather than a guess.

The two completeness signals relied on, named explicitly:

1. **Engine exit code** (`ScanJobResult.ok`) — catches crash, OOM, timeout.
2. **Parseability of the self-delimiting result document** — catches truncation and
   corruption, which exit code 0 structurally cannot.

Unusable output raises `IncompleteScanOutputError`, a `ScanExecutionError` subclass, so it
rides the **existing** fail-loud path (`run_scan_and_ingest` → FAILED `ScanRun` + honest
error + `audit_scan_failed` + re-raise). One failure path, not a second one.

Tolerance is preserved exactly where it is correct — a genuinely clean scan must still
complete, or every clean account cries wolf. Prowler's `[]`, a Trivy envelope with no
vulnerabilities, a clean SARIF, legacy plain-Trivy JSON and bare-SARIF dev harnesses all
pass; the normalizers keep skipping individual malformed *records* inside a well-formed
document.

### D2 — Raw scan output moves off pod logs onto an object-storage artifact channel

The Job's result file goes to object storage; the worker fetches and parses **the
artifact**, not stdout. Pod logs return to what they are for: diagnostics.

- **One channel for all engines**, expressed on the existing `ScanJobSpec` /
  `ScanExecutionBackend` seam — not a per-pillar path. Adding a pillar stays "a new
  adapter", never "a new transport".
- **Storage reuses the SBOM seam** (`minio_sbom_store` conventions): MinIO in-cluster
  today, real S3 in prod, `SBOM_S3_*`-style settings.
- **Retention is short and explicit** — a configurable TTL, default **14 days** (inside
  the review's 7–30 window), enforced by a bucket lifecycle rule, under a per-workspace
  key prefix.
- **The artifact is referenced from the `ScanRun`**, so a run's raw output is retrievable
  for debugging and support.

### D3 — The Job uploads via a co-container, NOT a presigned PUT from the engine container

This is the decision that changed under verification, and it is why D2 is not a one-line
change.

The obvious design — have the engine container `curl -T` its result to a presigned PUT URL
— **does not work across our pinned images**. Probed directly:

| Image | Upload tooling present |
|---|---|
| `aquasec/trivy:0.58.0` (alpine) | **busybox `wget` only — cannot perform HTTP PUT** |
| `toniblyx/prowler:5.36.0` | `wget`, `python3` |
| `autosec-opengrep:1.26.0` | `curl` |

There is **no common uploader**. Making the engine containers upload would mean either
forking the transport per engine (rejected — one channel is the point) or rebuilding the
official Trivy and Prowler images to bake an uploader in. That second option directly
reverses `improve-dont-replicate.md`'s hard-won "official image + native CLI" principle —
the same principle that killed `prowler_sdk_runner.py`. Trading a maintained official
image for a hand-built one to solve a transport problem is a bad trade.

**Decision:** the engine container keeps writing its result file to the shared `emptyDir`
scratch at `/tmp` — **which all three already do** (`/tmp/*.ocsf.json`,
`/tmp/autosec-trivy-*.json`, `/tmp/autosec-opengrep.sarif.json`). A **second container in
the same pod**, running *our* pinned minimal uploader image, shares that `emptyDir`, waits
for the engine to signal completion via a sentinel file, and ships the artifact to object
storage.

This keeps the engine images untouched and official, keeps one transport for all engines,
and puts the credential for object storage in a container that never parses untrusted
scanner input.

### D4 — Hardening constraints the channel must respect

- **`readOnlyRootFilesystem`, non-root, drop ALL caps, seccomp `RuntimeDefault`,
  `automountServiceAccountToken: false`, gVisor** — unchanged for both containers. The
  uploader writes nothing outside the shared `emptyDir`.
- **NetworkPolicy** (`k8s/bases/scanning/networkpolicy.yaml`): the `scan-jobs` policy
  currently permits egress only to `trivy-server:4954`, DNS, and **`443/TCP`**. In-cluster
  MinIO listens on **9000**, so the artifact upload **would be blocked today**. The
  channel requires an explicit egress rule to the MinIO pod on its port (and, in prod, to
  the S3 endpoint — which *is* 443 and therefore already permitted by the existing broad
  443 rule). This must be a **narrow podSelector rule**, not a widening of the policy: the
  scan tier is untrusted, and its egress is the control that stops a compromised scanner
  from exfiltrating.
- **Object-storage credentials** are scoped to **write-only, prefix-restricted** access.
  A scan Job must not be able to read other workspaces' artifacts.
- **Size cap** on the artifact, enforced at upload; exceeding it is a FAILED run.
- **Upload failure is a FAILED run** — never a silent skip. This is D1's invariant
  applied to the new transport: if we cannot obtain trustworthy output, we do not report
  a clean scan.

### D5 — MinIO presigned URLs must not inherit the known prod bug

The infra review flagged that MinIO presigned URLs are broken-by-default in prod (the
public/internal endpoint split). The artifact channel's **read path is server-side** — the
trusted worker fetches the object with its own credentials over the internal endpoint, so
it does **not** depend on presigning at all. Any future operator-facing "download raw
output" surface must resolve the endpoint bug rather than replicate the SBOM adapter's
`public=True` presign as-is.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| **Raise `containerLogMaxSize`** (e.g. to 100Mi) | A number a bigger customer exceeds; node-wide setting for one workload; leaves RAM buffering, no replay, no evidence copy. Defers the failure instead of removing it. |
| **Stream-parse stdout incrementally** (`on_output_line` + incremental JSON) | Does not help: kubelet rotation drops bytes *before* we read them for a completed pod. Streaming a channel that already lost data solves nothing, and it would couple every adapter to an incremental parser. |
| **Presigned PUT from the engine container** | Disproven by probe (D3): Trivy's busybox `wget` cannot PUT. Would fork the transport per engine or force abandoning official images. |
| **A true k8s sidecar** (`initContainers` + `restartPolicy: Always`) | Native sidecars are designed to run *alongside* for the pod's life; we need a *post-run* step. The sentinel-file co-container expresses "after the engine finishes" directly and works on the pinned k8s version without relying on sidecar termination semantics. |
| **Persist the whole raw output in Postgres** | Multi-MB blobs per scan in the SSOT; wrong store, wrong cost curve, and Postgres is the *findings* SSOT — raw engine output is an artifact, not a finding. |
| **A data lake (Parquet/Iceberg/ETL)** | Explicitly out of scope. This is a narrow scan-output contract, not an analytics store. ADR-level guard against scope creep. |
| **Do nothing beyond D1** | D1 converts a silent false negative into a loud failure — a genuine and sufficient *safety* fix — but every large-account scan would then simply *fail*. Correct, and unusable. D2 is what makes large accounts actually work. |

## Consequences

### Good

- **The silent false negative is gone at the root.** D1 makes it impossible to report;
  D2 makes it stop happening.
- **Large accounts become scannable.** The output ceiling stops being a log-rotation
  setting and becomes an object-size limit orders of magnitude larger.
- **Replay / re-normalization becomes possible** — a parser bug or an improved normalizer
  can re-ingest yesterday's artifact without re-hitting the customer's cloud (which costs
  API load, money, and trust). *Noted as a natural benefit; not built here.*
- **Debuggability and support**: "why did this scan find nothing" becomes inspectable.
- **Compliance evidence (ADR 0009)**: the raw engine output is the first-party evidence
  object.
- **Industry-aligned**: secureCodeBox persists raw results to S3/MinIO; AWS Security Lake
  codifies raw→S3→normalize as the reference architecture.

### Costs and risks

- **Two-repo change.** D2/D4 need `auto-sec-infra` changes (NetworkPolicy egress rule, a
  pinned uploader image, MinIO/S3 settings) alongside the backend change. They must land
  together or scans break.
- **A new failure mode**: object storage is now on the scan path. Mitigated by D4 — an
  upload failure is an honest FAILED run, the same as any other unusable-output case.
- **Storage cost**: bounded by the 14-day TTL, the per-scan size cap, and a lifecycle
  rule. At demo scale (~4 MB/scan) this is negligible; the cap is what keeps it so at
  customer scale.
- **The uploader image is a new pinned dependency** — pinned by tag **and digest** per
  `pin-versions.md`, since we execute it.

## Implementation status

- **D1 — shipped** (PR #307): shared document-integrity guard,
  `IncompleteScanOutputError`, all three adapters, the `K8sJobBackend._collect`
  output-unavailable hole, and regression tests for truncated JSON, empty output, engine
  non-zero exit, and a genuinely-clean scan still completing.
- **D2–D5 — decided here, not yet built.** Deliberately deferred rather than half-built:
  it is a coordinated backend + `auto-sec-infra` change (uploader image, NetworkPolicy
  egress, storage settings), and D3's co-container design only became clear once the
  presigned-PUT assumption was disproven by probing the images.

D1 is correct and valuable independently of D2 and **remains so after it lands** — object
storage can fail too, and "unusable output is a failed scan" is the invariant either way.
