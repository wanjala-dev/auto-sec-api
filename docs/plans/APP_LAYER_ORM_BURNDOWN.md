# App-Layer ORM Burndown — Refactor 25 application-layer files to ORM-free (Rule 2 + C2/C3)

**Status:** scheduled, in progress (tracked as tasks #46–#58). **Owner:** Auto-Sec.

## Why
A 2026-08 architecture audit found `open_draft_pr_use_case.py` writing another context's ORM (`project.Task`) from the application layer — an Explicit-Architecture violation (manifesto Rule 2 "application layer must be ORM-free" + skill C2 "never change data you don't own" + C3 "cross-context reads are read-only"). A fitness-function guard (`test_application_layer_is_orm_free`, PR #198) now bans app-layer ORM imports and allowlists the 26 pre-existing offenders with `# TRANSITIONAL` tracking comments. This doc is the plan to burn the allowlist down to zero. Each PR deletes exactly its allowlist entries; never baseline a new one. The guard prevents regression.

## Persistence → owning-context map
| `infrastructure.persistence.<pkg>` | Owning context |
|---|---|
| `ai.*` (ai.models, ai.agents.models, ai.conversations.models) | agents |
| `project.models` (Task, TaskComment, Column, Project) | project |
| `workspaces.models` (Workspace, WorkspaceMembership, WorkspaceRole, WorkspacePermissionGrant, WorkspaceGroup*) | workspace |
| `workspaces.workflows.models` (Workflow, WorkflowBinding, WorkflowTemplate) | workflow |
| `integrations.models` (AwsOrganizationConnection, WorkspaceLogSource, IngestCheckpoint, LogPatternRollup, GitHubConnection) | integrations |
| `content.models` (Newsletter, WritingDraft) | content |
| `team.models` (Team, Invitation) | team |
| `users.models` (CustomUser, UserProfile) | identity |

## Violation types
- **A — cross-context WRITE** (writes another context's models) → C2. Highest priority. Fix: route through the OWNING context's application surface (or a shared-kernel event) via a port. Exemplar: the `open_draft_pr` refactor (PR #199) — a new `project.RecordFindingDraftPrUseCase` owns the write; integrations calls it through `FindingPrRecorderPort`.
- **B — cross-context READ** (reads another context's models) → C3. Fix: a read-port in this context + an infra adapter. Exemplar: `components/remediation/infrastructure/adapters/board_finding_facts_repository.py`.
- **C — same-context app-layer ORM** (touches its OWN context's persistence) → Rule 2 only. Fix: extract a repository/port WITHIN the context; the use case depends on the port; the adapter holds the ORM.

**Tally of the 25 (excludes `open_draft_pr`, fixed in PR #199):** A=4 · B=9 · C=12.

## The 13-PR sequence
**Wave 0 — shared seams (unblock the rest):**
- **#46 / PR-0a — agents adopt existing `WorkspaceQueryPort`** (kills `Workspace.objects.filter(id=).first()` across 6 files; NO new port — reuse `cross_context_query_port.py` / `orm_cross_context_repository.py` / `ai_provider.py`). Removes finding_raised_board_handler, project_at_risk_specialist_handler, project_specialist_handler; unblocks partials in detector_cycle/ai_governance/set_workspace_agent_capability/agent_chat. Type B.
- **#47 / PR-0b — project `TaskLookupPort` + `PostureFactsPort`** read seams, infra adapters reading `project.Task`, mirroring `board_finding_facts_repository`. Consumed by PR-4/5/6 + PR-2. These become the CNAPP Phase-3 seam (adapter internals later swap to the `findings` SSOT, callers unchanged). Type B seam.

**Wave 1 — cross-context writes (type A, highest priority, HUMAN-REVIEWED before merge):**
- **#48 / PR-1 — AI kill-switch → workspace write surface** (set_ai_kill_switch_use_case writes Workspace.ai_teammate_enabled). Type A.
- **#49 / PR-2 — sign_off reconcile → reuse project `MoveTaskToBoardUseCase` + `UpdateTaskUseCase`** (materialize_signoff_tasks WRITES project.Task via task.column/save — mislabeled "read" in the allowlist; its "no sanctioned move-task use case" comment is STALE, one exists). Type A.
- **#50 / PR-3 — team invites → identity + workspace surfaces** (accept/create_workspace_invite each write THREE contexts: team + identity users + workspace membership). `InviteUserProvisioningPort` (identity) + `WorkspaceMembershipWritePort` (workspace); own Invitation → team repo; keep atomic() at the boundary. Payment-path-level care. Heaviest PR. Type A.

**Wave 2 — cross-context reads (type B):**
- **#51 / PR-4** — persist_finding_as_task idempotency read → project `TaskLookupPort`.
- **#52 / PR-5** — agents posture_service + posture_dashboard_service → project `PostureFactsPort` + agents posture_read_port.
- **#53 / PR-6** — ai_governance_service → `TaskLookupPort` + a NEW integrations credential read-port (reduce `token_ciphertext` to a presence BOOLEAN inside the adapter — never expose ciphertext across the port) + `WorkspaceQueryPort` + agents read-port. Sequence AFTER PR-4/5.
- **#54 / PR-7** — membership_permission_service → membership-owned `RolePermissionsReadPort` + `GrantsReadPort` over workspace RBAC tables.
- **#55 / PR-8** — content: rag_index_newsletter/writing_draft handlers + dispatch_due_scheduled_newsletters + generate_newsletter → existing `NewsletterReaderPort`/`NewsletterStorePort` (+ list_due_scheduled, stamp_rag_indexed) + WritingDraftReaderPort + content WorkspaceProfilePort; also fix generate_newsletter's direct `OrmDonationWeeklyTotalsAdapter` import (inject via provider).

**Wave 3 — same-context (type C, lowest risk):**
- **#56 / PR-9** — integrations LogSource ports (`LogSourceReadPort` + `IngestCheckpointPort` + `LogPatternRollupPort`); aligns with ADR 0008.
- **#57 / PR-10** — agents own-context write ports (ai_teammate_facade, execution_cost_tracker `RunUsagePort`, set_workspace_agent_capability `AgentCapabilityPort`, agent_chat via existing `conversation_repository_port`, detector_cycle teammate.save via existing `teammate_profile_port`). Split into 2 PRs if large.
- **#58 / PR-11** — workflow: `WorkflowProvisioningPort` for ai_findings_workflow_facade.

## Callouts
- **CNAPP Phase-3 coupling:** every `project.Task` cross-context read (PR-4/5/6 + PR-2's reconcile) is governed by known debt #4 (Task-is-the-finding, skill §7). The `project` read-ports (PR-0b) are the right interim seam and become the natural home when the `findings` SSOT lands — swap the adapter, callers unchanged. Do them behind ports now; expect the adapter internals to move in Phase 3.
- **Debt #3** (agents importing another context's *infrastructure* — cloud_posture/provenance detectors) does NOT overlap these 25 app-layer files; it's the detector modules under `agents/infrastructure/.../detectors/`. Same allowlist discipline, separate work.
- **Shared ports that MUST unify multiple files (no N copies):** `WorkspaceQueryPort` (exists, 6 files), project `TaskLookupPort`/`PostureFactsPort` (5 files), content newsletter ports (exist), team invite port set (#50), integrations LogSource ports (#56).
- **Secret hazard (PR-6):** the GitHubConnection read must never let `token_ciphertext` cross the port — reduce to a presence boolean inside the adapter (matches logging.md "never log secrets").
- **Exemplars:** cross-context read → `remediation/infrastructure/adapters/board_finding_facts_repository.py`; cross-context write → `open_draft_pr` refactor (PR #199); same-context → any standard `<noun>_repository.py` implementing a `<noun>_port.py`.

## Shipping order
PR-0a → PR-0b → PR-1 → PR-2 → PR-3 (writes, reviewed) → PR-4 → PR-5 → PR-6 → PR-7 → PR-8 (reads) → PR-9 → PR-10 → PR-11 (same-context). Each PR deletes exactly its `_TRANSITIONAL_ALLOWLIST` entries.
