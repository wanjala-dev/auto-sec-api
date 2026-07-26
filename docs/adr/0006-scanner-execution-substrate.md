# ADR 0006 — Scanner Execution Substrate

Status: Accepted (2026-07-26)
Relates to: ADR 0004 (CNAPP unified Finding + Asset spine — `ScannerPort` was Phase 4),
the `auto-sec-infra` k8s Kustomize stack (the runtime substrate).

## Context

Auto-Sec runs a growing fleet of security scanners — Prowler (CSPM), Trivy (container
SCA), and more to come (OSINT, recon, IaC, secrets). The question that forced this ADR:
**how do we run them in a way that is secure *and* scalable as the fleet grows?**

The conversation kept conflating three *separate* concerns. Untangling them is the whole
decision:

| Concern | Question | Owner |
|---|---|---|
| **A. Orchestration** | enqueue / schedule / track / retry a scan | **Celery** (unchanged) |
| **B. Engine integration** | build Prowler-vs-Trivy args; parse native output → `NormalizedFinding` | **`ScannerPort` adapter** (ADR 0004 Phase 4) — one per tool |
| **C. Execution** | *where/how* the engine runs against **untrusted input** (isolation, resource caps, scale) | **`ScanExecutionBackend`** — the NEW seam this ADR adds |

Grounding (research):
- Production scanning platforms run **ephemeral, isolated, per-scan jobs**, not long-lived
  services: secureCodeBox is a Kubernetes-Jobs FaaS ("scans only consume cluster resources
  for a short amount of time"); trivy-operator spawns a per-scan Pod that is deleted after.
- Untrusted image processing (layer unpacking → parser exploits, decompression bombs) is the
  real attack surface; the consensus control is a sandboxed, resource-capped, ephemeral
  runtime (gVisor for untrusted code; Kata/Firecracker for hardware isolation).
- **Trivy client/server (gRPC) is a vuln-DB distribution optimization, NOT the execution
  substrate** — the client still unpacks the untrusted image; the server only matches package
  lists. Prowler has no server mode (it calls AWS APIs live), so gRPC cannot be the unifying
  layer. The unifying layer is Concern C.

## Decision

Introduce **`ScanExecutionBackend`** as a port, so *how* a scanner engine executes is
swappable per environment without touching the scanner adapters. Every scanner (Prowler,
Trivy, future) runs through the *same* backend; adding a tool is an adapter + a container
image + a registry line — isolation and scale are inherited, solved once.

```
Celery (orchestrate)                          ← Concern A
   │ dispatch_scan(source, target)
   ▼
run_scan_and_ingest  (DRY choreography)       ← creates a ScanRun; emits FindingObserved → SSOT
   │ scanner = scanner_registry.get(source)
   ▼
ScannerPort adapter (Prowler / Trivy / …)     ← Concern B: build argv + parse → NormalizedFinding
   │ backend.run(JobSpec(image, argv, env, limits, creds))
   ▼
ScanExecutionBackend (port)                   ← Concern C: WHERE/HOW it runs
   ├─ LocalSubprocessBackend   (CI / no cluster: fixed-argv subprocess in a hardened worker)
   └─ K8sJobBackend            (prod substrate: throwaway gVisor Job per scan)
   ▼
findings SSOT  ← FindingObserved (ADR 0004; NO per-pillar finding table — C6)
```

### D1 — `ScanExecutionBackend` port

Shaped to the core's need — *"run this engine invocation in isolation, return its raw
output"* — not to any runtime API. Lives in `components/scanning/application/ports/`.

```python
@dataclass(frozen=True)
class ScanJobSpec:
    source: str                 # "container_security.trivy" — labels + names the run
    image: str                  # minimal scanner image
    args: tuple[str, ...]       # fixed argv (NEVER a shell string)
    env: dict[str, str]         # non-secret env (e.g. AWS_EC2_METADATA_DISABLED=true)
    secret_env: dict[str, str]  # short-lived creds — mounted, never in argv/logs
    timeout_seconds: int = 1800

@dataclass(frozen=True)
class ScanJobResult:
    stdout: str                 # the scanner's raw output (the adapter parses this)
    exit_code: int
    timed_out: bool = False

class ScanExecutionBackend:
    def run(self, spec: ScanJobSpec, *, on_progress=None) -> ScanJobResult: ...
```

### D2 — `LocalSubprocessBackend` (dev/CI)

Runs the engine as a **fixed-argv, no-shell** subprocess (the proven Prowler-runner pattern):
no `shell=True`, creds via env not argv, `AWS_EC2_METADATA_DISABLED=true`, hard timeout. Used
by unit tests and single-node/no-cluster dev. This is what makes the substrate testable
without k8s.

### D3 — `K8sJobBackend` (the real substrate)

Renders one **ephemeral, hardened Kubernetes Job per scan** via the in-cluster API (the
`scanning` ServiceAccount's least-privilege RBAC: `batch/jobs` + `pods/log` + short-lived
cred `secrets`). The Job mirrors `auto-sec-infra/k8s/bases/scanning/scan-job-template.yaml`:
non-root, `readOnlyRootFilesystem` + emptyDir scratch, drop ALL caps, seccomp RuntimeDefault,
cpu/mem/**ephemeral-storage** limits, `activeDeadlineSeconds`, `automountServiceAccountToken:
false`, `runtimeClassName: gvisor` (when available), and the scan-jobs default-deny
NetworkPolicy (egress → trivy-server + registry + DNS only). The backend creates the Job,
watches to completion, collects the raw output (pod logs), deletes the cred Secret, and lets
the Job self-GC (`ttlSecondsAfterFinished`). The **untrusted work runs only inside this
throwaway pod**, with no DB/broker creds and no app code — the trusted worker parses the
result afterward.

Selected by config: `SCAN_EXECUTION_BACKEND=k8s_job` (prod) / `local_subprocess` (dev/CI).

### D4 — Trivy is the first pillar; Prowler refactors onto the same backend

- **`TrivyScanner(ScannerPort)`** (`components/container_security/`): builds
  `["image", "--server", $TRIVY_SERVER_URL, "--format", "json", "--scanners", "vuln",
  "--quiet", "--", <validated image ref>]`; parses `Results[].Vulnerabilities[]` →
  `NormalizedFinding` (severity UNKNOWN/…/CRITICAL → shared `Severity`; CVE/pkg/fixed-version
  ride in `attributes`). Trivy points `--server` at the `trivy-server` DB (gRPC) so Jobs never
  fetch the DB.
- **Prowler** (`components/cloud_posture/`): `ProwlerScanner` keeps its OCSF parser but now
  runs its engine through the *same* `ScanExecutionBackend` (the direct `prowler_runner`
  subprocess is deleted — DRY). The SDK runner streams a JSON-lines protocol on stdout
  (`{"t":"progress"}` per check batch, a final `{"t":"result","records":[...]}`); the backend
  forwards each line via `on_output_line`, so **live per-check progress is preserved** on the
  local backend and records return without a shared temp file. No `prowler-server` — Prowler
  has no DB.
  - *Follow-up (not this slice):* running Prowler as a K8s Job needs a Prowler engine image
    with the runner baked in (invocable on PATH). And because a full-account OCSF result can be
    multi-MB, K8s-Prowler output should move to a shared-`emptyDir`/object-store transport —
    **pod-log stdout truncates large outputs** (trivy-operator has hit exactly this). Trivy
    (small per-image output) and Prowler-on-local (a pipe) are unaffected.

### D5 — Untrusted-input gate: the image-reference validator

`components/container_security/domain/image_reference.py` — the security-critical unit:
strict image-reference regex, **reject a leading `-`** (arg/flag injection), enforce a
registry **allowlist** (tenant ECR), and always pass the ref after `--`. Unit-tested against
malicious inputs. This is what makes "run a tenant-supplied image ref" safe regardless of
backend.

### D6 — The spine emits to the SSOT, owns no finding table

`ScanRun` (`infrastructure/persistence/scanning/`) is ONE generic scan-execution record for
every pillar. `run_scan_and_ingest(source, target, scanner)` creates it, runs the scanner via
the backend, and emits one `FindingObserved` per finding → the `findings` SSOT. **No
`ContainerVulnerability` / per-pillar finding table** (ADR 0004 C6) — a CVE's specifics live
in `NormalizedFinding.attributes`. This is deliberately the anti-clone of `cloud_posture`'s
legacy snapshot tables.

## Consequences

- Adding the Nth scanner = a `ScannerPort` adapter + a minimal scanner image + one
  `scanner_registry` line. Isolation, resource caps, and horizontal scale come from the
  backend — never re-litigated per tool.
- `gVisor`/Kata is a `runtimeClassName` swap on the Job, not a code change.
- The `LocalSubprocessBackend` keeps the whole thing unit-testable without a cluster.
- `cloud_posture`'s legacy `CloudPostureScan`/`CloudPostureFinding` tables become redundant
  once Prowler is on the spine — a later strangler step (out of scope here).

## Implementation plan (this ADR is the spec)

1. Spine: `ScanRun` model + `run_scan_and_ingest` + `scanner_registry` + generic `run_scan`
   Celery task (dispatch to the source's queue). *(drafted; finalize onto the backend.)*
2. `ScanExecutionBackend` port + `LocalSubprocessBackend` (D1, D2) + tests.
3. `image_reference` validator (D5) + tests (malicious inputs).
4. `TrivyScanner` adapter (D4) + `records_to_scan_result` parser + tests (fixture Trivy JSON).
5. `K8sJobBackend` (D3) using the kubernetes client; integration-tested against Docker Desktop
   k8s + the `auto-sec-infra` scan-job template.
6. Minimal Trivy scanner image (or reuse `aquasec/trivy`) wired in the registry.
7. Refactor `ProwlerScanner` onto the backend (D4) — *done*: `on_output_line` streaming seam
   preserves live per-check progress; `prowler_runner` deleted.
8. `feature.container_security` flag; dark until opt-in — *done* (`seed_feature_flags`,
   prod-disabled).
