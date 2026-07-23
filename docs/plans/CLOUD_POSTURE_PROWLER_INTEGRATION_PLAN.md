# Cloud Posture (CSPM) — Prowler Integration Plan (Phase A)

**Date:** 2026-07-23. **Status:** Implementation plan (the *decision* is already made — this is the build).
**Decision of record:** `SECURITY_POSTURE_VISION_2026-07-20.md` §3.3 (#41) — *"do NOT hand-roll the cloud-
config scanner — embed Prowler (Apache-2.0) as the detection engine."* This doc turns that decision into a
concrete, grounded build that reuses existing rails. **Gate:** the operator's read-only IAM audit role
rollout to linked accounts (Henry's infra call) — unchanged.

---

## 1. Context

Phase 3 of the posture vision is CSPM/CIEM via **Prowler-as-engine**. It is the nearest CNAPP-relevant value
because the decision is settled and the plumbing it needs already exists. The **engine/SOC split** holds:
Prowler emits raw cloud-config findings; **our AI layer is the value-add** (triage verifies + grounds,
`cloud_posture_agent` narrates, the board tracks remediation, `report_agent` maps compliance). Prowler is not
a competitor to what we built — it is the cloud detection engine our analysts were missing.

## 2. Architecture — wrap the engine, reuse everything else

```
per AwsAccountLink (existing) ─assume-role (existing STS plumbing)→ Prowler OSS run (Celery/container)
   → JSON/OCSF output → normalize + severity-map + dedupe (aggregate-don't-dump)
   → CloudPostureSnapshot (new) + per-check findings (source_type="ai.cloud_posture")
   → persist_finding_as_task (existing)  → board card w/ evidence + provenance
   → AiFindingRouterDetector (existing)  → triage_agent (verify/ground) + cloud_posture_agent (narrate)
   → report_agent (existing)             → compliance-framework mapping in the branded report
```

**Reused, not rebuilt (DRY):**
- **Credentials:** `sts_org_adapter.py` / `log_ingest_service.py::_assume_role_s3_client` — same
  per-`AwsAccountLink` assume-role + `ExternalId`. Prowler (Python/boto3) assumes-role the same way.
- **Findings:** `specialist_persistence_service.py::persist_finding_as_task` — the single idempotent path.
- **Routing:** add `"ai.cloud_posture"` to `ROUTABLE_SOURCE_TYPES` (`logwatch.py`) — the whole routing change.
- **Cadence:** a new detector on `detector_cycle.py` (nightly), same as `posture_report` / `logwatch`.
- **Reporting:** `report_agent.generate_pentest_report` already scopes by `source_type` + date window.
- **Governance:** `sign_off` already gates report/analysis delivery.

## 3. What's new (small, bounded)

- **`CloudPostureSnapshot`** model (`infrastructure/persistence/...`) — one row per account per scan:
  `workspace`, `aws_account_link` (FK), `scanned_at`, `prowler_version`, `checks_total`/`checks_failed`,
  `raw_output_ref` (S3/MinIO pointer — do **not** stuff raw JSON in the row), `summary` (JSONB: fails by
  severity + by framework). Immutable; nightly.
- **`cloud_posture.scan` detector** — assume-role → run Prowler (vendored OSS CLI/SDK, **Apache-2.0**, pinned)
  → parse → emit `DetectorResult`s (`action_type="cloud_posture"`, evidence = the failed check + resource +
  region, `impact_score` from Prowler severity). **Aggregate-don't-dump:** collapse identical checks across
  resources; cap + rank; never one card per resource.
- **`cloud_posture_agent`** specialist (`.../langchain/agents/cloud_posture_agent.py`, `@register_agent`) —
  the security-engineer lens: roles with root/`*` access, SCP coverage per account, access-key age,
  MFA-on-root, wildcard-policy inventory. **Reads snapshots, never live-scans mid-chat** (same discipline as
  `posture_agent`: answer only from tool output). Tools: `list_cloud_posture_findings`,
  `get_posture_snapshot`, `explain_check`.
- **Compliance mapping** in `report_agent` — Prowler ships CIS / SOC 2 / PCI-DSS / HIPAA / NIST 800-53 / CSF /
  FedRAMP / ENS natively; surface framework pass/fail in the report from `CloudPostureSnapshot.summary`.

## 4. Vendoring & safety

- **Embed Prowler OSS** (CLI/SDK, Apache-2.0) — **NOT Prowler Cloud** (their SaaS). Pin the version; run it in
  the Celery AI-teammate worker or a dedicated container.
- **Read-only:** the audit role is read-only; **no write-back / remediation** here (that is Phase E, behind
  `sign_off`). This phase only *reads and reports* posture.
- **Prompt-injection boundary:** deterministic engine fires findings; the LLM only triages/narrates over
  normalized output — never over raw cloud data it could be steered by (same rule as CloudTrail triage).
- **Multi-cloud for free (later):** Prowler also covers Azure / GCP / K8s / GitHub / M365 — one integration
  future-proofs multi-cloud without per-cloud scanners; wire GCP/Azure connectors when their onboarding
  adapters land (`INTEGRATIONS_AWS_POC` §6 ports).

## 5. Scope, verification, risks

**Deliverable:** `CloudPostureSnapshot` + `cloud_posture.scan` detector + `cloud_posture_agent` +
`ai.cloud_posture` routing + compliance surfacing in `report_agent`, feature-flagged, AWS/one account.

**Verification (read-only, end-to-end):**
- Run the detector against a **Prowler sample JSON fixture** (no live account needed until the audit role
  lands) → assert a `CloudPostureSnapshot` + deduped, severity-ranked `ai.cloud_posture` cards land on the
  board with evidence + provenance (existing detector-cycle integration-test pattern). Run twice → idempotent.
- `AgentTestCase` (stubbed LLM) for `cloud_posture_agent` tools → assert facts come only from snapshot output.
- `report_agent` scoped to `ai.cloud_posture` → assert framework pass/fail appears; narrative is
  faithfulness-gated (cannot cite a check not in the input).

**Risks / dependencies:**
- **Operator gate:** read-only IAM audit role rollout — blocks *live* scans only; build + test on fixtures now.
- **Prowler output volume:** enforce aggregate-don't-dump or the board floods (the vision's explicit rule).
- **Run cost/time:** Prowler org-wide is heavy → nightly, per-account, budgeted; never in the chat path.

## 6. Relationship to the asset graph

Prowler's output is also the **cheapest bootstrap for the Phase-B asset graph** (see
`CLOUD_ASSET_GRAPH_SPIKE.md`, Option A): the resources + relationships Prowler already enumerates seed
`CloudAsset`/`CloudAssetEdge` with zero new dependency. So: **land this (Phase A) → spike the graph on its
output (Phase B) → decide CloudQuery promotion → Phase C engines correlate onto the graph.**
