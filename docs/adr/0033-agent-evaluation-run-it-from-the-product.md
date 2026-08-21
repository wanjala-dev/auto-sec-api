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

### Henry's Logseq notes (Anthropic course, "Prompt evaluation")

These were supplied directly after an earlier draft claimed they could not be found — that
claim was wrong; the graph searched was the wrong one. They are the most directly
applicable input of the three, because they are a working pipeline rather than commentary,
and several decisions below are lifted from them.

- **Three grader kinds, with an explicit division of labour**: *code* graders (length, word
  presence, syntax validity, readability), *model* graders (quality, instruction-following,
  completeness, helpfulness, safety), *human* graders (comprehensiveness, depth,
  conciseness, relevance). The worked example maps criteria onto graders deliberately —
  *format* and *valid syntax* to code, *task following* to a model. D2's split between
  deterministic verifiers and the LLM judge is the same move.
- **The grader must emit `strengths`, `weaknesses` and `reasoning` BEFORE `score`**, because
  "without this context, models tend to default to middling scores around 6". This is
  **independent confirmation of D6** from Anthropic's own teaching material, arrived at from
  a different direction than the κ research (which measured 0.55 → 0.75). Two unrelated
  sources, same instruction: make the judge reason first.
- **Two-stage dataset generation** — first generate N *unique ideas* ("clearly distinct from
  the others", "specific enough to guide a full test case"), then expand each idea into a
  full case. Adopted in D3: mining traces without a diversity step produces near-duplicate
  cases clustered on whatever the workspace happened to do most.
- **Per-case `solution_criteria`, 1–4 items**, with an explicit warning to keep them tied to
  the task: *"avoid over-specifying criteria with requirements that go beyond the core
  task"*. Adopted in D10.
- **Anti-harshness scoring instructions**, which are the surprising part: *"Grade the output
  based ONLY on the listed criteria. Do not add your own extra requirements… If a solution
  meets all of the mandatory and secondary criteria give it a 10. Don't complain that the
  solution 'only' meets the criteria."* A judge that invents standards makes our agent look
  worse than it is — the mirror image of the over-claiming this codebase usually guards
  against, and just as dishonest.
- **Mandatory vs secondary criteria**: a violation of a mandatory requirement caps the score
  at 3 regardless of everything else. That is the same shape as D2's deterministic axes.
- **Operational details worth copying**: grade at `temperature=0.0`, generate ideas at 1.0
  and cases at 0.7; bounded concurrency with a configurable limit because rate limits are
  the real constraint; progress reported at milestones; an HTML report carrying scenario,
  inputs, criteria, output, score and reasoning per case, plus a **pass rate at ≥7** rather
  than only a mean.

### What the field says (researched 2026-08-21, sources at the end)

The webinar is one practitioner's view; these are the points current practice adds or
contradicts, and each changed a decision below rather than merely decorating it.

- **Evaluate at three levels**, not one: end-to-end (did the task succeed), trajectory
  (was the path sound and efficient), component (which tool or retriever broke). Our D2
  starts end-to-end because that is the customer's question — but `DeepRunLog` already
  stores the ordered trajectory, so trajectory-level scoring is a P4 extension of stored
  data, not a new pipeline.
- **Trace mining beats synthetic suites** for ecological validity. Independent confirmation
  of D3.
- **Raw agreement is a trap on imbalanced labels.** This one is load-bearing and is why D6
  changed: a judge that always says "pass" scores 90% raw agreement on a 90%-pass suite
  with Cohen's κ near zero.
- **Judges that reason before grading agree far more** — inter-judge κ ~0.55 → ~0.75 simply
  by demanding a rationale first.
- **Human-calibration sets are 50–200 items** in the literature; the target band for
  judge–human κ is 0.7–0.8, the human–human ceiling.
- **≥500 cases before aggregate metrics are trustworthy.** This directly contradicts the
  webinar's "10 or more per axis" and is the uncomfortable finding: no young workspace will
  have 500 labelled cases. Rather than split the difference silently, D9 states the tiers.
- **Prime Intellect's `verifiers` v1** decomposes an environment into *taskset* (data,
  tools, scoring), *harness* (solves it, produces a rollout) and *runtime* (local **or
  sandbox**). That is independent convergence on the shape of D8 + D5 — and the explicit
  runtime/sandbox split is the strongest external argument that D5's isolation is the
  standard move, not our paranoia.

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

Mining runs in **two stages**, taken from the Logseq pipeline: first cluster the workspace's
history into *distinct scenarios*, then expand each scenario into a case. Skipping the
diversity stage produces near-duplicate cases piled on whatever the workspace happened to do
most that month — a suite that measures one thing ten times and reports it as ten
observations, which is exactly the false-denominator problem ADR 0032 exists to prevent.

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

### D6 — Judge agreement is measured with Cohen's κ, and the judge reasons before it grades

Where an axis is judged rather than verified, the case is graded by two models where the
catalogue offers two (it now does — this ADR depends on #453 for that). A suite whose
judges disagree beyond threshold is reported as **rubric ambiguity** — a defect in our
prompt, surfaced to us, not billed to the customer as a failing agent.

Three specifics, taken from the research rather than invented:

1. **Cohen's κ, never raw agreement.** Raw agreement inflates badly on imbalanced labels:
   if 90% of cases pass, a judge that answers "pass" unconditionally scores 90% raw
   agreement and κ ≈ 0. Since a healthy security agent's suite *should* be mostly passes,
   raw agreement here would be a number that looks excellent precisely when it means
   nothing — the exact failure mode this codebase keeps shipping. κ is the honest statistic.
2. **Target κ 0.7–0.8**, the human–human ceiling reported in the literature. Below ~0.6 the
   suite is reported as **not measurable** rather than as a result, consistent with how
   ADR 0032 treats under-powered rates.
3. **The judge writes a one-paragraph rationale BEFORE emitting its verdict.** This is
   reported to lift inter-judge κ from ~0.55 to ~0.75 — a large gain for a prompt-ordering
   change and a few tokens. The rationale is also exactly what a human needs when they open
   a failed case, so it is stored, not discarded.

### D6a — Human calibration is a first-class step, not an afterthought

A judge nobody checked is an opinion with a percent sign. Calibration sets in the
literature are **50–200 human-labelled items**, which is tractable: the sign-off decisions
D3 mines are already human labels, so calibration means measuring **judge-vs-human κ** on
that existing set rather than asking anyone to label afresh. A rubric ships only once it
agrees with the humans who produced the labels.

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

### D9 — A suite states which tier of claim it can support

The field says ≥500 cases before aggregate metrics are trustworthy. The webinar says 10+
per axis. Both are right about different claims, and a young workspace will have neither.
Splitting the difference quietly would produce a confident number from six cases, which is
this codebase's signature defect. So the tier is stated on the surface:

| Cases on the axis | What the panel is allowed to say |
|---|---|
| < 10 | **NOT MEASURED** — count only, no rate, no verdict |
| 10–49 | **DIRECTIONAL** — rate with denominator, explicitly "too few to conclude" |
| 50–499 | **MEASURED** — rate + trend; κ against human labels reported |
| ≥ 500 | **AGGREGATE-GRADE** — comparison across models and time is defensible |

This reuses ADR 0032's `MIN_TRIALS = 10` as the floor rather than inventing a second
threshold, and it means the surface starts honest on day one instead of waiting for enough
data to be honest.

### D10 — Global axes AND per-case criteria; binary axes, not a 1–10 score

The Logseq pipeline scores 1–10; D2 grades binary axes. Both are kept, at different levels,
because they answer different questions and the reconciliation matters:

- **Global axes (binary, per D2)** are the product surface. "83% of cases were grounded" is
  a claim a workspace owner can act on. A mean of 7.4/10 is not — it is uninterpretable
  across cases, it drifts with judge mood, and a rate needs a denominator to be honest
  (ADR 0032). Cohen's κ, which D6 depends on, is also defined for categorical judgements;
  it does not apply cleanly to a 1–10 scale.
- **Per-case `solution_criteria` (1–4 items, from the notes)** are the *inputs* to the axis
  judgement, not a separate score. Mined cases carry what "right" meant for that specific
  case — the sign-off reviewer's actual objection, for instance. The judge grades the axis
  against those criteria rather than against a generic standard it invented.

The judge prompt therefore takes its **structure** from the notes and its **output type**
from the research: `strengths` → `weaknesses` → `reasoning` → **per-axis pass/fail**, in
that order, at `temperature=0.0`, with the anti-harshness instruction included verbatim in
spirit — grade only against the stated criteria, and a case meeting all of them passes.

Deterministic verifiers (`fix_applies`, `no_fabricated_asset`) do not go near the judge.

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
4. **Minimum viable suite size.** D9 proposes tiered claims rather than a single threshold,
   which is my recommendation. The alternative is withholding EVALUATE entirely until a
   workspace clears 50 cases — cleaner, but it means Tom sees nothing for weeks.
5. **Trajectory-level scoring in P4 or sooner?** The data is already in `DeepRunLog`, and
   "the agent got the right answer the wrong way" is precisely what a security buyer
   distrusts. It may deserve to be earlier than P4.

## Sources

- [LLM-as-a-Judge in 2026: techniques and best practices — DeepEval](https://deepeval.com/blog/llm-as-a-judge)
- [LLM Agent Evaluation Metrics in 2026: tool calling, task completion, trace-based evals — Confident AI](https://www.confident-ai.com/blog/llm-agent-evaluation-complete-guide)
- [LLM-as-Judge patterns for agent evaluation: calibration, bias, trajectory — Zylos Research](https://zylos.ai/research/2026-05-26-llm-as-judge-agent-evaluation-patterns/)
- [Cohen's kappa: inter-annotator agreement beyond raw percent — ZeroEntropy](https://zeroentropy.dev/concepts/cohens-kappa/)
- [How to calibrate your LLM judge with human annotations — Galileo](https://galileo.ai/blog/calibrate-llm-judge-human-annotations)
- [Judge's Verdict: a comprehensive analysis of LLM judges (arXiv 2510.09738)](https://arxiv.org/pdf/2510.09738)
- [Can LLM-as-a-Judge reliably verify rubrics in agentic scenarios? (arXiv 2606.29920)](https://arxiv.org/pdf/2606.29920)
- [verifiers v1: decomposing tasksets and harnesses for agentic RL & evaluations — Prime Intellect](https://www.primeintellect.ai/blog/verifiers-v1)
- [verifiers — environments docs](https://docs.primeintellect.ai/verifiers/environments)
- [LLM-as-a-judge — Langfuse docs](https://langfuse.com/docs/evaluation/evaluation-methods/llm-as-a-judge)
