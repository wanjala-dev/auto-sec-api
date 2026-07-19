---
name: integrations
description: Auto-Sec source/sink integrations — org-scale AWS onboarding (cross-account roles, StackSets, CloudTrail→S3→SQS ingestion), Slack sinks, and the connector registry. Invoke before touching components/integrations or the ingestion pipeline.
---

# Integrations — the connector layer

## Architecture (locked 2026-07-18, research-validated)

**Onboarding (AWS Organizations, any customer org):**
- One `AwsOrganizationConnection` per customer org per workspace. We GENERATE
  the `external_id` (vendor-side, never customer-chosen — confused-deputy
  defense, AWS SEC03-BP09). Customer launches our generated template in their
  MANAGEMENT account.
- **Both formats**: CloudFormation (quick-launch; includes an
  `AWS::CloudFormation::StackSet` with SERVICE_MANAGED permissions +
  AutoDeployment so every current AND future member account gets the audit
  role automatically) and a Terraform module (`?fmt=terraform`) for
  IaC-first customers.
- Verify = `sts:AssumeRole` dry-run → `organizations:ListAccounts` →
  `AwsAccountLink` rows. Per-account status: one broken account DEGRADES the
  org, never blocks it. AccessDenied on org discovery ⇒ single-account
  customer (valid, not an error).
- Role policy is least-privilege read: trail S3 objects, tagged SQS queues,
  org listing (mgmt only), `kms:Decrypt` via S3 only.

**Ingestion (storm-proof):**
- Primary channel: org trail → central S3 → S3 event notifications → **SQS**
  (+ DLQ). SQS consumers are STATELESS → horizontal scale + failover free;
  never LIST-storm the bucket. Fallback channel: S3 prefix listing with
  `IngestCheckpoint` cursors per (connection, account, region).
- Dedupe on CloudTrail `eventID` (AWS documents duplicate deliveries).
  `sqs:DeleteMessage` only after successful processing; poison → DLQ.
- STS sessions are cached per role and refreshed before expiry.

**Sinks:** `SinkConnector` (Slack first, Block Kit). Secrets via Fernet
envelope in `secret_ciphertext` — NEVER plaintext, never in `config`.

## Where things live
- Models: `infrastructure/persistence/integrations/models.py`
- Onboarding API: `components/integrations/api/controller.py`
  (`/integrations/workspaces/<ws>/aws/` + `<id>/cloudformation/?format=` +
  `<id>/verify/`) — gated by `manage_integrations`.
- STS/org adapter: `components/integrations/infrastructure/adapters/sts_org_adapter.py`
- Vendor AWS account id: `AUTOSEC_VENDOR_AWS_ACCOUNT_ID` setting/env.
- Full design + detections: `docs/plans/POC_CLOUDTRAIL_TRIAGE_2026-07-17.md`

## Not built yet (next phases)
SQS/S3 poller Celery workers → normalized events; the 5 MITRE detections →
findings on the triage board; Slack sink delivery; Settings ▸ Integrations UI;
Stratus Red Team demo path.

## Rules
- Never store customer AWS keys — role-assumption only.
- Never widen the role policy without updating BOTH template generators.
- Every ingestion write must be idempotent (eventID + document_key patterns).
