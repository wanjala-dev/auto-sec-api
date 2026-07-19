---
name: backup-recovery
description: >
  Use when working on the Wanjala API demo database backup & disaster-recovery
  pipeline — verifying the nightly dump landed, checking backup health, triggering
  a manual backup, running a non-destructive restore drill, or walking a recovery
  scenario ("is my backup healthy?", "trigger a backup", "restore yesterday's dump",
  "the EC2 is gone, what do I do"). Loads where backups live, the S3 layout, the
  operator CLI wrappers, the read-only health checks, and the three DR scenarios.
  Destructive restores stay in the operator's hands via the CLI — this skill informs,
  it does not auto-restore. Pair with the `ec2-manage` agent for host operations and
  `.claude/rules/ec2-deployment.md` for the canonical EC2 environment facts.
---

# Backup & Recovery — Wanjala API Demo

The demo database backup and disaster-recovery pipeline. The actual implementation is
documented in **`docs/runbooks/db-restore.md`** — read it before doing anything, not
during the incident.

## Architecture at a glance

| Item | Value |
|------|-------|
| Bucket | `s3://wanjala-demo-sandbox-data/` |
| Backup prefix | `backup/postgres/` |
| Media prefix | `media/` (reserved for django-storages — PR 2) |
| Cron schedule | 03:00 UTC daily |
| Cron file on host | `/etc/cron.d/backup-db` |
| Backup script on host | `/usr/local/bin/backup-db.sh` |
| Source of truth (repo) | `octopus-infra/demo-infra/workloads/sandbox/scripts/backup-db.sh` |
| Retention | 90 days for current versions, 7 days for superseded (versioning ON) |
| DB user | `wanjala-art-sql-user` |
| DB name | `wanjala-api-database` |
| Auth model | EC2 instance role (`wanjala-demo-sandbox-host`) — no long-lived keys on disk |
| AWS profile (operator laptop) | `octo-tf-admin` |

## How backups happen

The host-level cron runs `/usr/local/bin/backup-db.sh` as `ubuntu` at 03:00 UTC. The
script:

1. Verifies `compose-db-1` is running (refuses to upload a fake dump if postgres is down).
2. Streams `pg_dump | gzip | aws s3 cp -` straight to S3 — nothing intermediate lands on disk.
3. HEADs the uploaded object and **deletes + fails** if it's under 100 KB (catches empty
   pg_dump output that pipefail misses).
4. Promotes the timestamped dump to `backup/postgres/latest/dump.sql.gz` via server-side copy.

S3 layout:
```
backup/postgres/
  ├── 2026-06-05/dump-0300-utc.sql.gz   ← cron
  ├── 2026-06-06/dump-0300-utc.sql.gz   ← cron
  ├── 2026-06-06/dump-1742-utc.sql.gz   ← manual via backup-db
  └── latest/dump.sql.gz                ← server-side copy of newest good
```

## Operator commands

These are wrappers in `octopus-infra/demo-infra/workloads/sandbox/manage-ec2.sh`:

```bash
# Trigger an immediate backup (same script the cron runs):
./manage-ec2.sh backup-db

# Non-destructive DR drill -- pulls the latest dump, loads into a
# throwaway pgvector container, runs smoke counts, tears down.
# Use this to validate the pipeline monthly without touching prod:
./manage-ec2.sh test-restore
./manage-ec2.sh test-restore 2026-06-05

# Restore the most recent dump (DESTRUCTIVE -- requires typed
# confirmation):
./manage-ec2.sh restore-db latest

# Restore a specific date -- picks the most recent dump in that
# day's folder:
./manage-ec2.sh restore-db 2026-06-05
```

`restore-db` requires typing `RESTORE <when>` exactly to confirm — this is intentional.
Do NOT bypass that confirmation in any script wrapper.

## Read-only health checks (run these first when asked "are backups healthy?")

```bash
# 1. Did today's dump land?
AWS_PROFILE=octo-tf-admin aws s3 ls s3://wanjala-demo-sandbox-data/backup/postgres/$(date -u +%Y-%m-%d)/

# 2. What does "latest" point at, and how big is it?
AWS_PROFILE=octo-tf-admin aws s3api head-object \
  --bucket wanjala-demo-sandbox-data \
  --key backup/postgres/latest/dump.sql.gz \
  --query '{Size:ContentLength,LastModified:LastModified}'

# 3. Last 14 days of cron runs (look for gaps):
AWS_PROFILE=octo-tf-admin aws s3 ls s3://wanjala-demo-sandbox-data/backup/postgres/ \
  | awk '{print $2}' | grep -E '^20[0-9]{2}-[0-9]{2}-[0-9]{2}/$' | sort | tail -14

# 4. Cron is loaded on the host (requires SSH):
ssh "${SSH_OPTS[@]}" "ubuntu@$IP" 'cat /etc/cron.d/backup-db'

# 5. Last cron run log (host-side):
ssh "${SSH_OPTS[@]}" "ubuntu@$IP" 'sudo grep backup-db /var/log/syslog | tail -20'
```

Healthy signal: today's date present, dump size > 1 MB, no gaps in the trailing 14 days,
last syslog entry says `OK`.

## Disaster recovery scenarios

The runbook (`docs/runbooks/db-restore.md`) has the full text. The distillation:

### Scenario A — data loss but EC2 is alive

Bad migration, corrupted data, accidental truncate.

```bash
# Most recent good dump:
cd octopus-infra/demo-infra/workloads/sandbox/
./manage-ec2.sh restore-db latest

# Or a specific date:
./manage-ec2.sh restore-db 2026-06-05
```

Verify after with `curl https://api.wanjala.art/api/health/` and a spot check via Django admin.

### Scenario B — EC2 is gone (volume corruption, AMI broken, anything fatal requiring terraform destroy)

The backups survive `terraform destroy` because they live in S3, not on the EC2 root volume.

```bash
cd octopus-infra/demo-infra/workloads/sandbox/

# 1. Tear down the dead instance:
AWS_PROFILE=octo-tf-admin terraform destroy -target=module.demo_host -auto-approve

# 2. Provision a fresh one (the instance role + profile re-attach automatically):
AWS_PROFILE=octo-tf-admin terraform apply -auto-approve

# 3. Deploy the application:
./manage-ec2.sh deploy

# 4. Restore yesterday's data:
./manage-ec2.sh restore-db latest

# 5. Re-request SSL certs (the old certs went down with the volume):
./manage-ec2.sh certs

# 6. Verify:
curl https://api.wanjala.art/api/health/
```

Total downtime: ~10–15 minutes (DNS update if the public IP changes).

### Scenario C — regional AWS outage (S3 + EC2 both in `us-east-1`)

Out of scope at current cost. Wait for AWS to recover. Cross-region replication can be
added later if the cost/recovery tradeoff changes.

## Common failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Cron run logs `FATAL: role "postgres" does not exist` | Script defaulted to wrong DB user (pre-PR #202) | Update — should be `wanjala-art-sql-user` |
| Manual run says `aws: command not found` | awscli not on host (pre-PR #202) | `./manage-ec2.sh deploy` reinstalls it idempotently |
| 20-byte gzip object in dated folder | pg_dump empty stdout (e.g. DB down) | Pre-PR #202, garbage stayed. Post-fix, the script deletes + exits non-zero. Manual cleanup: `aws s3 rm <key>` |
| `AccessDenied` writing to `media/` from host | Intended — EC2 instance role is scoped to `backup/*` only | If genuinely needed, restore needs media too: that path goes through PR 2's IAM user, not the host role |
| `latest/` points at an old dump | Last cron run failed at the promote step | Re-run: `./manage-ec2.sh backup-db` (will redo upload + promote) |

## Rules

1. **Never run `restore-db` without typed `RESTORE <when>` confirmation.** The CLI requires it; never wrap around it.
2. **Never bypass the size guard** in `backup-db.sh`. If the dump is < 100 KB, something is wrong — investigate, don't override.
3. **Never edit `/usr/local/bin/backup-db.sh` on the host directly.** It's a copy of the file in the repo. Edit the repo file, then `./manage-ec2.sh deploy` reinstalls it.
4. **Never set `force_destroy = true` on the data bucket** in Terraform. That bucket holds the only copy of the DB backup — `terraform destroy` must not be able to wipe it.
5. **Read the runbook first.** `docs/runbooks/db-restore.md` is the source of truth; this skill is the cheat-sheet on top of it.
6. **Backup runs as `ubuntu`, not root.** Keeps blast radius small. If you're tempted to chown to root for some new feature, push back — the script doesn't need it.
7. **Destructive restore stays with the operator.** Even a future in-app agent (LangChain etc.) does NOT do restore — destructive ops stay in the operator's hands via the CLI.

## Cross-references

- Runbook: `api-v2.0/docs/runbooks/db-restore.md`
- Backup script source: `octopus-infra/demo-infra/workloads/sandbox/scripts/backup-db.sh`
- Cron entry source: `octopus-infra/demo-infra/workloads/sandbox/scripts/cron.d-backup-db`
- Operator CLI: `octopus-infra/demo-infra/workloads/sandbox/manage-ec2.sh` (`backup-db`, `restore-db` subcommands)
- Terraform: `octopus-infra/demo-infra/workloads/sandbox/main.tf` — search for "App data bucket"
- EC2 environment facts (SSOT): `.claude/rules/ec2-deployment.md`
- Host operations: the `ec2-manage` agent
