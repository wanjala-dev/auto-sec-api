# RESUME STATE — Phase 2, scan-output artifact channel (auto-sec-api)

Paused 2026-08-10 mid-build. **Nothing is merged. Do not merge on resume** — merges only
on Henry's explicit word.

## Landed already (merged to main, before this pause)

- **PR #307** — Phase 1 safety fix: unusable engine output is a FAILED scan, never a clean one.
- **PR #308** — ADR 0022, the scan-output artifact channel.

## This worktree: `feat/scan-artifact-channel-api`

Companion infra branch: `feat/scan-artifact-channel-infra` in `auto-sec-infra`. **The two
must land together** — the backend writes to object storage the infra branch authorizes.

### ADR 0022 decision status

| Decision | Status |
|---|---|
| **D1** unusable output = FAILED scan | **DONE** — merged in #307 |
| **D2** raw output → object-storage artifact channel | **CODE COMPLETE, UNVERIFIED LIVE** |
| **D3** co-container uploader (not presigned PUT from the engine) | **CODE COMPLETE, UNVERIFIED LIVE** |
| **D4** hardening: netpol, size cap, upload failure = FAILED run | **CODE COMPLETE, UNVERIFIED LIVE** |
| **D5** no inherited MinIO presign bug | **DONE** — read path is server-side, no presigned GET exists |

### What is built here

- `components/scanning/application/ports/scan_artifact_store_port.py` — new port.
  `presign_put` (one-object write capability) + `fetch` (server-side read).
- `components/scanning/infrastructure/adapters/minio_scan_artifact_store.py` — MinIO/S3
  adapter. Key: `scan-artifacts/<workspace>/<source>/<scan_run_id>.json`. Size cap,
  fail-loud on missing/empty/oversized.
- `components/scanning/application/providers/scan_artifact_store_provider.py` — composition root.
- `scan_execution_backend.py` (port) — `ScanJobSpec.artifact_path/workspace_id/scan_run_id`,
  `ScanJobResult.artifact_ref`, and **`artifact_emit_tail()` + `SCAN_ARTIFACT_PATH` /
  `SCAN_SENTINEL_PATH`** — the ONE Job-side protocol all three engines render from.
- `k8s_job_backend.py` — presigns before the Job exists, adds the `artifact-uploader`
  co-container (`curlimages/curl:8.11.1@sha256:c1fe...` — pinned by digest), fetches the
  artifact instead of pod-log stdout on success.
- All three adapters (prowler / trivy / opengrep) publish via `artifact_emit_tail` and
  carry `raw_artifact_ref` up.
- `ScanRun.raw_artifact_ref` + migration `0003_scanrun_raw_artifact_ref.py`.
- `run_scan_service.py` — injects `workspace_id`/`scan_run_id` into `target.params`,
  records `raw_artifact_ref` on the run.
- `api/settings/base.py` — `SCAN_ARTIFACT_S3_*`. **Subtle and load-bearing:**
  `SCAN_ARTIFACT_S3_ENDPOINT` is only *defined* when the env var is present; its presence
  is the switch that stops prod inheriting MinIO credentials against real S3.
- `components/scanning/tests/unit/test_artifact_channel.py` — 20 tests.

### Verification done

`339 passed` — `components/{scanning,cloud_posture,container_security,code_security}` +
`tests/architecture/`, hermetic in a throwaway container off `autosec-api:scanartifact2-test`
(image since deleted).

### NOT done — the exact next step

**The live end-to-end proof was never run.** Everything above is code + unit/integration
tests only. On resume, in order:

1. `kubectl kustomize k8s/overlays/local` — **currently fails in a fresh worktree** because
   `k8s/overlays/local/secrets/{env.local,aws-base.env}` are gitignored. Copy BOTH from the
   primary clone `/Users/henrywanjala/Desktop/auto-sec/auto-sec-infra/k8s/overlays/local/secrets/`
   before rendering. (I copied `env.local`, hit the missing `aws-base.env`, then deleted the
   copy so no secret would be committed — that is where the build stopped.)
2. Build + deploy: `docker build -t autosec-api:local -f k8s/local-image.Dockerfile <this worktree>`
   → `kubectl apply -k k8s/overlays/local` → **`kubectl rollout restart`** the api,
   celery-worker and scanning-worker deployments (same-tag rebuilds do NOT restart pods)
   → **grep a code marker inside the running pod** (`rollout status` lies). Suggested marker:
   `grep -c artifact_emit_tail /app/components/scanning/application/ports/scan_execution_backend.py`.
3. Run a REAL scan (demo AWS account, workspace `cc287133-b53c-43c8-9000-2873f8c8a1e3`) and show:
   the `scan-artifacts/...` object in MinIO, and `ScanRun.raw_artifact_ref` pointing at it.
4. **Prove the failure path**: break the upload (e.g. delete the MinIO netpol allow, or point
   `SCAN_ARTIFACT_S3_ENDPOINT` at a black hole) and assert a **FAILED** ScanRun — never a
   silent success. The uploader exits 72 → the Job fails → the adapter's existing fail-loud
   path marks the run FAILED.
5. Open the PRs for review (they are DRAFT).

### Known open questions / risks not yet resolved

- **Uploader uid.** `curlimages/curl` ships uid 100, but the pod security context forces
  `runAsUser: spec.run_as_user or 10001` (Prowler's Job runs as **1000**). The uploader must
  still be able to READ the engine's file on the shared `emptyDir`. `fsGroup` is set to the
  same uid, which *should* cover it — **this is the most likely thing to break on the first
  live run** and is precisely why step 3 above is not optional.
- **`_ensure_bucket` against real S3.** Harmless (head_bucket succeeds, no create attempted)
  but never exercised against AWS.
- The Prowler script now normalizes its exit code (`prowler` exits non-zero merely for
  *having* findings, so file-existence is the health signal). Verify on the live run.

## Cluster state left behind

**Untouched and coherent.** Phase 2 was never deployed. The only thing I ever applied was a
synthetic `autosec-truncation-repro` Job during Phase 0 evidence gathering, which was deleted.
No port-forwards, dev servers or watchers were started. Throwaway images
`autosec-api:scanartifact-test` and `autosec-api:scanartifact2-test` are deleted.
