# ADR 0033 — Agent evaluation, run from the product

- **Status:** Proposed
- **Date:** 2026-08-21
- **Supersedes:** nothing. Extends ADR 0032 (model & agent performance measurement) and
  consumes ADR 0031 (agent tool contract).
- **Decision owner:** Henry

## Context

A workspace owner can now see *how much* their AI ran, what it cost, and how often it
failed (ADR 0032, shipped). They cannot see whether it was any **good**, and they cannot
ask it to prove it. That is the gap this ADR closes: a first-class **EVALUATE** surface
beside AI PERFORMANCE, where a workspace admin presses a button, the agent is run against
cases drawn from their own history, and each result is either passed, failed, or honestly
marked not-measured — with every failure traceable to the run that produced it.

### What already exists (verified 2026-08-21, not assumed)

autosec inherited a real prompt-evaluation toolchain from the wanjala fork, and more of it
is wired than the empty-catalogue experience suggested:

| Asset | Location | State |
|---|---|---|
| Prompt evaluator | `components/agents/infrastructure/evaluation/prompt_evaluator.py` | works |
| SAST fix eval | `components/agents/infrastructure/evaluation/sast_fix_eval.py` | works |
| Eval example VO + port + repo + provider | `components/agents/{domain,application,infrastructure}` | works |
| `PromptEvalExample` model | `infrastructure/persistence/prompt_eval/models.py` | migrated |
| 5 CLI commands | `run_planner_eval`, `run_writing_eval`, `run_feedback_eval`, `run_sast_fix_eval`, `export_feedback_eval_dataset` | work |
| Rubric judge | `deep/rubric.py` + `domain/value_objects/rubric_verdict.py` (`RubricMiddleware`) | landed, flag-gated |
| Report API | `PromptEvalReportsViewSet` | reads `docs/eval-reports/*.json` **from disk** |
| HUD panel | `components/V2/HudPromptQualityPanel.jsx` | **mounted** at `CommandCenterV2Page:5680` |
| Reports | `docs/eval-reports/` | **30 files, committed to the repo** |
| Langfuse tracing | `infrastructure/adapters/tracing/langfuse.py` | present; **no keys set**, so `is_available()` is False and tracing is the null adapter |
| `run_reviewer_feedback_eval` | `infrastructure/tasks/eval_tasks.py` | task exists, **in no beat schedule** |

So this is not a greenfield build. It is a **productisation**, and the honest framing is
that what exists is a founder's toolchain, not a customer surface.

### Why it is not what a workspace owner needs

1. **It is not per-tenant.** The report API reads a directory off the filesystem. Every
   workspace sees the same 30 files, baked into the image at build time. Tom cannot see
   his own evals; he sees ours.
2. **Nothing can be run from the product.** Every path is a management command.
3. **Results are files, not rows** — no per-tenant history, no run-over-run comparison,
   and 30 artifacts committed to a repo that `repo-hygiene.md` says should not hold them.
4. **There is no failure provenance.** Langfuse is unconfigured, so there is no trace to
   link to. A failed case today is a red row with no "why".
5. **It grades prompts, not agents.** Planner, writing, SAST-fix. The question a customer
   asks is "is my triage agent any good", which is end-to-end.

### Inputs to this design

Henry's ask (2026-08-21), a LangChain webinar on the agent development lifecycle, and the
existing wanjala-era plans (`RAG_EVAL_BASELINE.md`,
`SIGN_OFF_FEEDBACK_TO_EVAL_PHASE_6C_2026-07-02.md`, `research/recommendations/bandits-eval.md`).

Four points from the webinar shape the decisions below, because they are testable rather
than merely sensible:

- **3–5 non-overlapping axes per task**, mostly binary. An axis a case cannot fail is not
  an axis.
- **Judge disagreement is a signal about the JUDGE.** If two frontier models grade the
  same case differently, the rubric prompt is ambiguous — that is a bug in our rubric, and
  we can detect it automatically.
- **Mine real traces into a few task clusters** rather than simulating a world. We already
  persist the traces: `Finding`, `DeepRun`/`DeepRunLog`, and sign-off decisions.
- **Calibrate across model strengths.** A suite every model passes tells you nothing; the
  interesting suite is one where a weak model fails and a strong one passes.

Henry's Logseq notes on prompt evaluation could not be located — the graph at
`~/Documents/logseq` holds two unrelated pages. **Fold them in when pointed at the right
graph**; this ADR does not claim to incorporate them.

## Decisions

### D1 — EVALUATE is a sibling surface to AI PERFORMANCE, not a tab inside it

Same placement pattern, which already works and is already mounted in both places:
Settings ▸ Workspace ▸ EVALUATE, and an `EVALUATE` panel in the HUD dock. It inherits
ADR 0032's honesty rules verbatim — a metric with no observations reads **NOT MEASURED**,
never as clean; every rate carries its denominator; below `MIN_TRIALS` nothing is a
judgement.

### D2 — v1 grades the AGENT end to end, not the prompt

The unit is: *given this case, did the agent produce an acceptable outcome?* Prompt-level
eval keeps working via the existing commands and folds into the same spine in Phase 4.

Starting axes for the triage agent — binary, non-overlapping, each independently failable:

| Axis | Passes when |
|---|---|
| `grounded` | every cited artifact exists and says what the agent claims |
| `severity_sound` | assigned severity matches the labelled outcome |
| `fix_applies` | the produced patch applies cleanly to the target revision |
| `scope_respected` | the agent touched only what the case authorises |
| `no_fabricated_asset` | every asset/URN referenced resolves in this workspace |

`fix_applies` and `no_fabricated_asset` are **deterministic** — no judge, no tokens. Per
the webinar, prefer a verifier to a judge wherever the check can be mechanical; reserve
the LLM judge (`RubricMiddleware`) for `grounded` and `severity_sound`.

### D3 — Cases are mined from the workspace's own history

Sources, in order of signal quality, all of which we already store:

- **sign-off decisions** — an approved artifact is a labelled positive, a rejected one a
  labelled negative. This is the wanjala Phase 6C idea, and it is the cheapest real labels
  we will ever get.
- **findings with a resolved outcome** — fixed/confirmed vs suppressed-as-false-positive.
- **DeepRuns** — clustered into 2–3 task shapes rather than replayed one by one.

A brand-new workspace has no history. That is a **first-run problem identical to the empty
model catalogue**, and it must not be solved by pretending: the surface says *"not enough
history to build a suite yet — N cases needed, M available"* and names what would produce
them. It does not show a green tile.

### D4 — Provenance comes from our own run records, not a vendor

Every `EvalCaseResult` carries a FK to the `DeepRun` that produced it. `DeepRunLog`
already persists, per event: `event_type`, `tool_name`, `payload`, `system_prompt`,
`user_prompt`, `llm_response`, `model_used`. That is the "why did it fail" drill-down, in
our database, for every tenant, with no third party holding customer prompts.

Two constraints carried over rather than rediscovered:

- **Run detail is owner-only** — the existing DeepRun read-authz contract. Teammates get
  the redacted projection. EVALUATE must not become a way around it.
- Langfuse stays **our** internal lens, unconfigured in tenant-facing paths. If it is ever
  enabled, it is additive, never the source of truth a customer depends on.

### D5 — An eval run MUST NOT mutate product state

This is the decision most likely to cause an incident if it is got wrong, so it is stated
as an invariant rather than an intention.

Running the triage agent for evaluation means running an agent that can, in normal
operation, **open draft PRs on a customer's repository**, write findings, and move board
cards. An eval run does none of that. Enforcement, in order:

1. Eval runs execute under an explicit `evaluation` execution mode threaded through the
   ADR 0031 tool contract; every state-changing tool is refused in that mode — the same
   read/write classification #446 established, reused rather than re-derived.
2. Refusal is **fail-closed**: a tool with no declared mode support is refused, not allowed.
3. A fitness test asserts that a full eval run produces zero rows in `Finding`, `Task`,
   and the VCS draft-PR path. This is the test that must never be baselined away.

### D6 — Judge disagreement is recorded, not hidden

Where an axis is judged rather than verified, the case is graded by two models where the
catalogue offers two (it now does — ADR 0033 depends on #453 for that). Agreement is
recorded per case. A suite whose judges disagree above a threshold is reported as
**rubric ambiguity** — a defect in our prompt, surfaced to us, not billed to the customer
as a failing agent.

### D7 — Cost is stated before the run, and capped

An eval run is N cases × agent execution × judge calls. That is real money, and the same
principle as the model picker applies: the spend is stated **before** the button is
pressed, as an estimate with its assumptions visible, and the run is bounded by the
workspace's configured cost cap. A run that would exceed the cap is refused with the
number, not silently truncated.

### D8 — Results are rows, per workspace

New persistence app `evaluation`:

- `EvalSuite` — workspace, name, agent type, axis definitions, provenance of its cases
- `EvalCase` — suite, source kind + reference, input payload, label, per-axis expectation
- `EvalRun` — workspace, suite, agent type, **model slug at run time**, status, totals,
  cost, FK to `BackgroundJob` for live progress
- `EvalCaseResult` — run, case, per-axis verdicts, judge model(s), agreement, **FK to the
  `DeepRun`**, failure reason, cost

`model_slug` on the run is load-bearing: per ADR 0032, measurements do not transfer
between models, so a suite result is only meaningful against the model that produced it.
Switching models must invalidate the standing of prior eval results exactly as it
invalidates fix-confidence.

`docs/eval-reports/*.json` and the disk-reading viewset are **retired** in Phase 4, not
left beside the new surface. Two sources of eval truth is the defect this codebase keeps
producing.

## Phases

| Phase | Deliverable | Notes |
|---|---|---|
| **P1** | `evaluation` context + models + case mining from sign-off decisions + read-only EVALUATE panel | proves the spine on real labels |
| **P2** | RUN EVAL button → Celery → `BackgroundJob` progress → results | reuses the existing progress primitive |
| **P3** | Failure drill-down: case → `DeepRun` → `DeepRunLog` tool calls and prompts | D4, owner-only |
| **P4** | Judge agreement (D6), model calibration, fold the prompt harness in, retire `docs/eval-reports/` | one place evals live |

P1+P2 are the smallest thing that answers Henry's question. P3 is what makes a failure
actionable rather than merely visible.

## Consequences

- A workspace owner can finally answer "is my AI any good", with evidence they can inspect.
- We inherit a maintenance duty: axes and rubrics are product surface now, and a bad rubric
  is a bug we ship. D6 exists to catch that.
- Eval runs cost money and take time; D7 keeps that honest and bounded.
- The riskiest part is D5. An eval harness that can write to a customer's repo is worse
  than no eval harness.

## Open questions for Henry

1. **Who may run an eval?** Workspace admin only, or any member? Running costs money, which
   argues admin — but "as a team member I want to evaluate" was part of the ask.
2. **Cadence.** Manual button only in v1, or also a scheduled weekly run so the panel has
   history without anyone remembering? Scheduled means recurring spend.
3. **Do eval results feed remediation memory?** A case the agent reliably fails is exactly
   what the fix-confidence machinery should down-weight. Powerful, and a coupling worth
   deciding deliberately rather than drifting into.
4. **Minimum viable suite size.** The webinar suggests ~10 cases per axis. With five axes
   that is a lot of labelled history for a young workspace. Do we ship with fewer and mark
   it under-powered (consistent with `MIN_TRIALS`), or withhold the surface until it can
   support a judgement?
