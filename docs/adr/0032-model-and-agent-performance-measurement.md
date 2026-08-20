# ADR 0032 — Model & agent performance: measure the configuration, not the model; ship trust, not a leaderboard

**Status:** Proposed (2026-08-20) — design only. No code in this ADR. Build deferred until Henry's
explicit go, behind the standing "harden the core loops for Tom's real use" priority.

**Deciders:** Henry

**Relates to:**
**ADR 0012** (Remediation Memory — already tracks outcomes; this ADR fixes the signal that feeds it),
**ADR 0018** (Judgment Flywheel — reconciled in §1.6, *not* re-opened),
**ADR 0019 / 0025** (SAST pillar + patch oracles — `fix_confidence.py` is the prior art this ADR generalises),
**ADR 0020** (entitlement chain — the precedent if model switching becomes tier-gated),
**ADR 0023** (agent runtime accountability — the customer-facing sibling; §1.5 explains why it is *not* this),
**ADR 0031** (tool contract + governance middleware — supplies the per-tool outcome/latency substrate; its OQ2 is this ADR's OQ1),
**ADR 0011** (sample-data mode), **ADR 0028/0029** (tenancy), **ADR 0004** (Finding SSOT).

**External grounding:** the reference Flask/Svelte tutorial app at
`~/Desktop/wanjala-llm/pdf_udemy/pdf` (read-only, §1.2), plus the literature in §1.4.

---

## 1. Context

### 1.1 What was asked

> "This tutorial did shed some light on how to take feedback from models when users upvote or
> downvote — we presented a dashboard for a user to know how the models are doing and how to switch
> models. I think we should add that to this, for the **workspace admin**: show them a **dashboard
> per tenant**, let them see how a model is performing and even be able to change models. Take
> inspiration from the app I shared and **improve on it**. … We could even take it further and
> **apply it to agents as well**." — Henry, 2026-08-19

Two asks, and they are not the same size:

1. A **per-tenant admin dashboard** showing model performance, with the ability to switch model.
2. The **same treatment at agent level**.

The honest answer, developed below, is that most of ask (1) is already built and dark, ask (2) is
mostly *not* what an operator actually wants, and the single highest-value thing in this whole area
is a bug fix, not a dashboard.

### 1.2 The reference app — what it does, and where it would mislead at product scale

The tutorial app is ~120 lines of scoring logic. It is worth reading precisely because it is small
enough to see the whole loop.

**How it works** (all paths relative to `~/Desktop/wanjala-llm/pdf_udemy/pdf`):

| Step | Mechanism |
|---|---|
| **Assign** | At conversation start, `chat.py:14-28` picks one `llm`, one `retriever`, one `memory` and **pins the triple to the conversation** (`chat.py:47-52`). Selection is a weighted random draw proportional to each component's running average score — `score.py:4-33`. |
| **Capture** | `POST /api/scores` with a score in `[-1, 1]` (`score_views.py:16`), attributed to the conversation's pinned triple (`score_views.py:19-25`). |
| **Store** | Six global Redis hashes — `{llm,retriever,memory}_score_{values,counts}` — incremented with `HINCRBY` (`score.py:40-47`). |
| **Aggregate** | `get_scores()` (`score.py:49-64`) returns `sum / count` per component name. |
| **Surface** | Three bar charts of those averages (`client/src/routes/scores/+page.svelte`). |
| **Switch** | There is no manual switch. The system re-weights itself; the operator only watches. |

**What it gets right, and what we should keep:**

- **Assignment is recorded before generation.** The conversation stores *which* llm/retriever/memory
  produced it. Most systems fail here and can never attribute anything afterwards. This is the
  embryo of the configuration-tuple idea in **D1**.
- **The measured unit is a tuple of components, not "the model".** It already understands that
  retrieval and memory are part of what the user is judging.
- **The loop is closed** — the score changes future behaviour rather than sitting in a chart.

**Where it would mislead at product scale — seven defects, each of which we would inherit by copying:**

1. **Credit assignment is broken by construction.** One score is written to all three components
   (`score.py:40-47`). A downvote caused entirely by bad retrieval also penalises the LLM and the
   memory. With three components you cannot tell which caused the vote; with our fourteen agent
   types, dozens of tools, and a prompt registry, you certainly cannot.
2. **The statistic is a bare mean with no n.** `score / count` (`score.py:61`), rendered as a bar.
   Two votes and two hundred votes look identical on the chart. This is exactly the "3 of 4 = 75%"
   trap.
3. **The cold-start prior is silently optimistic.** `int(values.get(name, 1))` / `int(counts.get(name, 1))`
   (`score.py:21-22`) means an *unmeasured* component reads as a perfect 1.0 average and immediately
   attracts traffic. A brand-new model looks like the best model. That is the "green because
   nothing ran" defect with a floor of `max(avg, 0.1)` bolted on (`score.py:24`).
4. **The score is clamped to `[0, 1]` on write** (`score.py:38`) even though the API accepts `[-1, 1]`
   (`score_views.py:16`). A downvote of `-1` is stored as `0`. Also: `HINCRBY` takes an integer, so
   the "float score" in the signature is fiction — the whole thing is binary.
5. **The weighted-random selector is a bandit with no exploration guarantee.** Proportional-to-mean
   selection has rich-get-richer dynamics: a model with a bad early run gets less traffic, so its
   estimate never corrects. See §1.4 item 12 — the literature is explicit that traffic share in a
   bandit is *not* evidence a model is better.
6. **Evidence is global, permanent and un-joinable.** Redis hashes, no tenant, no time window, no
   model version, no expiry, and no way to ask "which conversations produced this number?" A model
   that was bad in March drags its average forever. `fix_confidence.py` in *our* codebase already
   solves all four of these (§1.3).
7. **No cost, no latency, no failure rate.** A switching decision made on a preference average alone
   ignores the two axes an operator paying the bill actually cares about.

**The improvement thesis, in one line:** keep the tuple-attribution idea; throw away the statistic,
the storage, the selector and the chart.

### 1.3 What autosec already has — this is a convergence ADR, not a greenfield one

This is the crux. The DRY and improve-don't-replicate rules apply with full force: nearly every
primitive Henry asked for exists. Several are built and **dark** — wired but never lit.

#### 1.3.1 Built and working

| Capability | Where |
|---|---|
| Upvote/downvote on assistant messages | `AgentResponseFeedback`, `infrastructure/persistence/ai/conversations/models.py:82`; table `ai_agent_response_feedback` (`:109`); unique `(message, user)` (`:112-117`). Endpoint `POST/DELETE /api/ai/conversations/<id>/messages/<mid>/feedback/` — `components/agents/api/controller.py:2119-2205` |
| Feedback → dataset → eval pipeline | `promote_feedback_to_dataset.py:174` (downvotes → candidate eval cases, `:193-195`), `export_feedback_eval_dataset.py:42`, `run_feedback_eval.py:146`, `run_planner_eval.py:182`, `run_writing_eval.py:165` |
| Eval harness + judges | `components/agents/infrastructure/evaluation/prompt_evaluator.py`; graders under `components/agents/tests/prompt_eval/graders/` |
| SAST fix eval → measured evidence | `run_sast_fix_eval.py:134` writes `components/code_security/rules/remediation/fix_confidence.yaml` |
| **Wilson-bounded measured trust** | `components/code_security/domain/fix_confidence.py` — see §1.3.4 |
| Per-model cost/latency rollups | `AIModelDailyMetric` / `AIWorkspaceDailyMetric`, `infrastructure/persistence/ai/aggregations/models.py`; repo `ai_analytics_repository.py:29-101` |
| AI quality overview API | `GET /api/ai/agents/runs/analytics/overview/` — `controller.py:1722-1757`, resource `ai_quality_resources.py:67`. Already emits per-day `feedback_up/down`, per-model `cost_usd`, `latency_p50_ms`, `latency_p95_ms`, `failure_rate`, `positive_ratio`, `feedback_rate` |
| Run list / detail / events / stats | `controller.py:1605-1720`; owner-only redaction on detail + events (`:1655`, `:1675`) |
| Workspace AI config (model, fallback, budgets, caps) | `workspace_ai_config.py:129-190`; endpoints `controller.py:655-734` |
| Model catalog | `AIModel` / `AIModelProvider`, `infrastructure/persistence/ai/llms/models.py:10,38`, seeded by `seed_ai_models.py:19-42` |
| Prompt versioning | `components/agents/infrastructure/prompts/registry.py`; `planner.system` is at `active: v12` |
| Per-tool outcome + latency + declaration | ADR 0031 Phase 1, merged 2026-08-20 (`07fcd7b` / PR #437): `base.py:2494-2512` writes `DeepRunLog.status` and `payload["governance"]`; payload shape at `tool_spec.py:268-279` |
| Outcome tracking on remediations | `RemediationEntry.reuse_count/success_count/recurrence_count/score`, `infrastructure/persistence/remediation/models.py:77-81` |
| AI kill switch | `components/agents/application/policies/ai_kill_switch.py:29`, endpoint `controller.py:1019-1064`, permission `permissions.py:39-54` |
| Tool risk ladder | `components/agents/application/policies/tool_risk.py:26-71` |

#### 1.3.2 Built and DARK — wired, never lit

This list is the single most important finding in this document. **A large part of what Henry asked
for is already written and simply does not run.**

| Dark surface | Evidence | Consequence today |
|---|---|---|
| The AI-quality rollup task is **not scheduled** | `ai.rollup_ai_quality_daily` is declared at `ai_quality_rollup_tasks.py:205` and registered at `api/celery.py:35`, but appears in **no** `CELERY_BEAT_SCHEDULE` (`api/settings/prod.py` carries only `ai.rollup_ai_action_daily` at `:349`) | `GET /runs/analytics/overview/` reads only rollup tables (`ai_analytics_repository.py:29-101`) → **the series is all zeros in prod.** The dashboard Henry wants exists and returns nothing. |
| `AIModelChangeEvent` has **no writer** | Defined `infrastructure/persistence/ai/aggregations/models.py:208`, read `ai_analytics_repository.py:93` — repo-wide grep finds no producer. `update_ai_config` (`controller.py:671-695`) does not emit one | `model_changes[]` is permanently empty. The exact annotation a "did the switch help?" chart needs is missing. |
| RubricMiddleware verdicts **never read back** | Writer uses key `"verdict"` (`rubric.py:285-293`); reader looks for `"satisfied"` then `"passed"` (`orm_deep_run_query_repository.py:212-215`) and counts anything not explicitly `True` as a fail (`:216-220`) | `rubric_pass_count` on `GET /ai/agents/runs/` is **always 0**; `rubric_fail_count` equals the verdict count regardless of grading outcome. Our only judge reports 100% failure. |
| RubricMiddleware is **off in prod and covers 3 of 14 agent types** | Flag `DEEP_RUBRIC_MIDDLEWARE_ENABLED` defaults **false** at `api/settings/base.py:479` (prod inherits), true only in dev/local (`dev.py:529`, `local.py:665`). `CRITIC_ENABLED_AGENTS = {"triage_agent", "optimization_agent", "code_security_agent"}` — `deep/critic.py:36`; 14 agent types are registered under `components/agents/infrastructure/adapters/langchain/agents/` | There is no judge signal in production at all. |
| `fix_confidence` label is **written and never rendered** | Written at `code_security_agent.py:310`; no backend serializer or resource reads `payload["fix_confidence"]` | The one honest, statistically-grounded confidence number we compute is invisible to the operator. |
| Few-shot-negatives payoff has **no caller** | `build_get_few_shot_negatives_use_case` (`eval_example_provider.py:46`) is called from nowhere | The feedback loop captures but never closes. |
| The feedback-eval Celery task is **not scheduled** | `agents.run_reviewer_feedback_eval`, `eval_tasks.py:24-29`; docstring claims weekly, no beat entry exists | Feedback evals run only when someone types the command. |

#### 1.3.3 Built and BROKEN — the outcome signal is inverted

`RemediationEntry` tracks `recurrence_count` — "the fix did not hold" — which is the strongest
outcome signal we have and the natural spine of any trustworthy performance number.

**It never fires for SAST, container, cloud-posture, cloud-exposure, Vercel or planted-instruction
findings.** Chain of custody, verified line by line:

1. `board_finding_facts_repository.py:95` reads
   `str(payload.get("fingerprint") or metadata.get("fingerprint") or "")`.
2. No finding card writes a `fingerprint` key. The board convention is `lookup_key` — e.g. the SAST
   card builder `_build_code_security_card` writes `"lookup_key": finding.fingerprint`
   (`finding_raised_board_handler.py:231, 235`) and nothing named `fingerprint`. `grep -n '"fingerprint"'`
   over that file returns **no match**. `persist_finding_as_task` does not add one either
   (`specialist_persistence_service.py:181-198`).
3. So `FindingRemediationFacts.finding_fingerprint == ""`, copied verbatim into the entity at
   `record_remediation_entry_use_case.py:136`.
4. `propagate_remediation_outcomes_use_case.py:69-84` guards the recurrence branch with
   `if fp and (prior.finding_fingerprint or "").strip() == fp:` — with `fp == ""` the guard is
   **`False` for every prior, unconditionally**, so every prior takes the `else` branch and is
   awarded `record_reuse_success`.

**The sign is inverted.** A fix that did not hold is *promoted* in retrieval ranking
(`W_SUCCESS = 3`) instead of demoted (`W_RECURRENCE = 5`, `remediation_ranking_policy.py:44-46`).
Any dashboard leaning on this signal today would show **inflated** success, and the more a fix fails,
the better it would look.

Two honesty notes: the branch **is** reachable for `ai.log_watch` and `ai.log_optimization`, whose
contract does carry `fingerprint` (`log_ingest_service.py:431`, `log_pattern_analyzer_service.py:139`).
And the integration tests hand-construct `payload={"fingerprint": …}`
(`components/remediation/tests/integration/test_entry_gate_flow.py:50`) — which is precisely why the
suite is green over a dead branch. A second reader has the same defect:
`resolve_finding_task_repository.py:96`.

#### 1.3.4 The prior art that decides most of this ADR

`components/code_security/domain/fix_confidence.py` is already this codebase's answer to *"how do we
grade whether something works from measured outcomes without fooling ourselves on small samples."*
It is better than anything in the reference app and better than what most vendors ship:

- **One-sided 95% Wilson lower bound** — `_Z = 1.6448536269514722` (`:78`), `wilson_lower_bound` (`:148-163`).
  Its own docstring names the failure it exists to prevent: *"at our n the normal interval is not
  merely wide but wrong — for a clean run it collapses to [1.0, 1.0], reporting certainty from two
  observations."* Calibration: `2/2 → 0.43`, `20/20 → 0.88`.
- **Minimum-trials floor** — `AUTOFIX_MIN_TRIALS = 10` (`:89`), with the stated reason that a floor
  makes the refusal message say *"2 trials"* rather than an abstract score.
- **Evidence expiry** — `EVIDENCE_MAX_AGE_DAYS = 90` (`:94`): *"The model changes underneath a
  measurement without any commit on our side, so a number with no expiry slowly becomes a claim
  about a system that no longer exists."*
- **Three tiers, not a boolean** — `proven` / `measured_weak` / `unproven` (`:99-101`), because
  "never measured" and "measured and found wanting" are different facts leading to different work.
- **Fails closed on model** — undeclared model → unproven (`:255-256`); model mismatch → unproven
  with the message *"measured on X, running Y — measurements do not transfer between models"*
  (`:257-258`); past expiry → unproven (`:260-262`).
- **Absence is a verdict** — `confidence_for` never returns `None`.

The committed evidence file is `model: gpt-3.5-turbo`, four rules, `measured_at: 2026-08-17`, expiring
2026-11-15. **Any run on a different model resolves every rule to `unproven` today.** That is the
system working as designed, and it is the exact behaviour Henry's "let the admin change models"
feature will trigger at scale (D7).

#### 1.3.5 Built and UNGOVERNED — a live authorization hole in the endpoint this feature sits on

`PATCH /api/ai/agents/ai-config/update` is the endpoint that changes a workspace's model.

- Its docstring says *"Only workspace owner/admin can change"* — `controller.py:673`.
- `AgentViewSet.permission_classes = [IsAuthenticated]` — `controller.py:542-543`.
- The action declares **no** `permission_classes` override (contrast `kill_switch` at `:1019-1024`,
  which correctly requires `AiKillSwitchPermission` → `manage_agents`).
- The body reads `workspace_id` straight from `request.data` (`:674`) and performs **no membership
  or role check**; the adapter does none either (`workspace_ai_config_adapter.py:55-67`).
- The merge is a shallow `existing_dict.update(incoming)` (`:688`) and
  `WorkspaceAIConfig.is_model_valid()` (`workspace_ai_config.py:285-288`) is **never called on the
  write path** — an arbitrary model string can be persisted.

**Read plainly: any authenticated user of any tenant can today change any other tenant's AI model,
system-prompt addendum, spend caps and per-persona limits.** No test covers this endpoint. This is
the same class as the incidents fixed in #414, #416, #417 and #419. It is a blocking prerequisite
(§3, Phase 0) and should ship as its own security fix PR, not inside a dashboard change.

#### 1.3.6 Tenancy and sample-data facts that constrain any aggregate

- The canonical scoping pattern is an explicit `.filter(workspace_id=…)` on `DeepRun` and
  `deep_run__workspace_id=…` on `DeepRunLog` — `orm_deep_run_query_repository.py:421-422`. There is
  no tenant manager; scoping is caller-supplied at every call site.
- `DeepRun.workspace` is `null=True, on_delete=SET_NULL` (`infrastructure/persistence/ai/agents/models.py:361`).
  A run with a NULL workspace is invisible to every workspace aggregate — a silent undercount.
- `get_workspace_stats` degrades to a **cross-tenant global** when `workspace_id is None`
  (`orm_deep_run_query_repository.py:419-420`), and `GET /runs/stats/` permits that for `is_staff`
  (`controller.py:1709-1713`).
- `GET /api/ai/prompt-eval/reports/` reads eval reports off the filesystem with
  `permission_classes = [IsAuthenticated]` and **no workspace parameter** (`controller.py:2992-3095`) —
  any authenticated user of any tenant sees every eval report on disk.
- **Sample data is excluded in exactly one place in the codebase**: the report SSOT's
  `_inclusion_filter`, `components/report/infrastructure/repositories/ssot_finding_repository.py:246-253`,
  which also *counts what it dropped* (`:117`, `:135`, `:142`) so the exclusion is a stated number.
  That is the pattern to copy. It is **not** applied to compliance
  (`django_finding_repository.py:245-252`), ATT&CK coverage (`attck_coverage_repository.py:21-34`), or
  cloud exposure (`django_cloud_graph_repository.py:75-107`) — all three count sample rows as real.
  (I found no committed "sweep" fixing this; the code evidence stands on its own, and open task #159
  tracks the same class.)

### 1.4 What the research says

Cited items are grounded; where a commonly-repeated number could not be traced to a primary source I
say so rather than borrowing its authority.

**Online vs offline.** The accepted split is settled vendor vocabulary: offline evals benchmark and
regression-test against curated datasets; online evals score live traffic for quality patterns,
safety and anomalies — LangSmith, https://docs.langchain.com/langsmith/evaluation-concepts. Langfuse:
*"Effective LLM evaluation blends offline and online methods, because each catches errors the other
misses"* — https://langfuse.com/blog/2025-11-12-evals. OpenAI positions evals explicitly as the gate
*when upgrading or trying new models* — https://developers.openai.com/api/docs/guides/evals.

**Thumbs are sparse and negatively biased.** Langfuse documents explicit feedback's cons as *"Low
response rates"* and *"Unhappy users more likely to respond"*, and recommends implicit behavioural
signals (copy, accept, retry, abandonment) as the higher-volume complement —
https://langfuse.com/docs/observability/features/user-feedback. Their evals guide calls user feedback
*"free but sparse"* and *"sparse and noisy."*
⚠️ **The widely circulated "1–3% of users leave a thumb" figure could not be traced to any primary
source and is not on the Langfuse page it is usually attributed to. This ADR asserts the direction,
never a percentage.**

**LLM-as-judge biases are real, named, and primary-sourced.** Zheng et al., *Judging LLM-as-a-Judge
with MT-Bench and Chatbot Arena* (NeurIPS 2023), https://arxiv.org/abs/2306.05685 — names position
bias, verbosity bias and self-enhancement bias; GPT-4 reaches >80% agreement with humans, the same
level as human-to-human. Liu et al., *G-Eval* (EMNLP 2023), https://arxiv.org/abs/2303.16634 — flags
judges' bias toward LLM-generated text. Shi et al., https://arxiv.org/abs/2406.07791 — judge-model
choice dominates positional bias. *Pairwise or Pointwise?* (2025), https://arxiv.org/abs/2504.14716 —
with a distractor feature, pairwise preferences flip in 35% of cases vs 9% for pointwise. And the
hardest result for us: Dorner, Nastl & Hardt, *Limits to scalable evaluation at the frontier: LLM as
judge won't beat twice the data* (ICLR 2025 oral), https://arxiv.org/abs/2410.13341 — when the judge
is no more accurate than the evaluated model, **no debiasing method can reduce required ground-truth
labels by more than half.** Our grader is `gpt-4o-mini` (`rubric.py:48`) judging frontier-model work.

**Small samples.** Brown, Cai & DasGupta, *Interval Estimation for a Binomial Proportion*,
Statistical Science 16(2), https://projecteuclid.org/journals/statistical-science/volume-16/issue-2/Interval-Estimation-for-a-Binomial-Proportion/10.1214/ss/1009213286.full
— the Wald interval's coverage is erratic and *"common textbook prescriptions regarding its safety
are misleading and defective"*; Wilson recommended. Agresti & Coull (1998),
https://math.unm.edu/~james/Agresti1998.pdf — Wilson *"yields coverage probabilities close to nominal
confidence levels, even for very small sample sizes."* Wilson (1927), JASA 22(158):209-212. And the
rule of three — Hanley & Lippman-Hand (1983), JAMA 249(13):1743-1745,
https://jhanley.biostat.mcgill.ca/c607/ch08/zero_numerator.pdf — **zero failures in n trials gives a
95% upper bound of ≈ 3/n**, i.e. "0 failures in 12 runs" is consistent with a 25% failure rate.

**Peeking.** A dashboard is looked at continuously, which invalidates fixed-horizon inference.
Johari, Pekelis & Walsh, *Always Valid Inference*, https://arxiv.org/abs/1512.04922 — inferences are
*"wholly unreliable if users endogenously choose sample sizes by continuously monitoring their tests."*
Optimizely's write-up of the same simulations reports **>57% of A/A tests falsely declaring a winner
at least once** under per-visitor checking, dropping to ~3% with always-valid methods —
https://www.optimizely.com/insights/blog/statistics-for-the-internet-age-the-story-behind-optimizelys-new-stats-engine/.
Ramdas et al., *Safe Anytime-Valid Inference*, https://arxiv.org/abs/2210.01948.

**Confounding, and why paired comparison wins.** Radlinski, Kurup & Joachims, *How Does Clickthrough
Data Reflect Retrieval Quality?* CIKM '08,
https://www.cs.cornell.edu/people/tj/publications/radlinski_etal_08b.pdf — **none of eight absolute
usage metrics reliably reflected quality at realistic sample sizes, while paired/interleaved designs
produced accurate relative judgments.** This is the most transferable result in the whole literature
for our problem: absolute per-arm rates read off a dashboard are the thing that demonstrably does not
work. Deng, Xu, Kohavi & Walker (WSDM '13, CUPED) note that online you generally *cannot* pre-stratify
because data arrives over time; post-stratification/covariate adjustment is the practical answer.
Kohavi, Tang & Xu, *Trustworthy Online Controlled Experiments* (CUP 2020) is the standard reference.
⚠️ The frequently quoted "interleaving is 10×–100× more sensitive" and "CUPED cuts variance ~50%"
figures could not be verified against their primary texts; the *mechanisms* are cited, the numbers are not.

**Regression gating before a switch.** Braintrust documents the exact workflow —
*"Before switching to a new frontier model, you can run the existing eval suite against both models
side by side and compare cost, latency, and quality scores"* —
https://www.braintrust.dev/articles/eval-driven-development. Shadow deployment is best documented by
AWS SageMaker Shadow Tests (a shadow variant receives replicated traffic and returns nothing),
https://docs.aws.amazon.com/sagemaker/latest/dg/shadow-tests.html.

**Drift.** Evidently's comparison of five embedding-drift methods recommends a model-based domain
classifier scored by ROC AUC as the default, and states the caveat that matters most:
*"There is no universal way to define data changes that strictly correlate to model quality"* —
https://www.evidentlyai.com/blog/embedding-drift-detection. **Drift is a trigger to look, not evidence
of degradation.**

**Cost, latency, routing.** FrugalGPT (Chen, Zaharia & Zou), https://arxiv.org/abs/2305.05176 — cascades
match the best single model *"with up to 98% cost reduction."* RouteLLM (ICLR 2025),
https://arxiv.org/abs/2406.18665. Per-tenant cost attribution is the one thing the gateway ecosystem
has genuinely converged on: LiteLLM virtual keys + tag budgets
(https://docs.litellm.ai/docs/proxy/multi_tenant_architecture), Portkey metadata
(https://portkey.ai/docs/guides/use-cases/track-costs-using-metadata), Langfuse per-generation cost
(https://langfuse.com/docs/observability/features/token-and-cost-tracking). Not Diamond documents its
router adding ~100–150ms per request — routing is not free.

**Agent-specific evaluation.** LangSmith's trajectory evals define four match modes — strict,
unordered, subset (did it call *unnecessary* tools), superset —
https://docs.langchain.com/langsmith/trajectory-evals. And the single most useful result for a
security product: **τ-bench** (Yao et al., Sierra), https://arxiv.org/abs/2406.12045, which introduces
`pass^k` ("all k attempts succeeded") against the conventional `pass@k`, and finds state-of-the-art
models under 50% on single-attempt success with **pass^8 below 25%** in the retail domain. Since
`pass^k = p^k`, a 90%-success agent is only **57% reliable at k=8**. A single-attempt success rate
systematically overstates how much an operator can rely on an agent.

**Outcome vs preference, in our exact domain.** Google, *Resolving Code Review Comments with ML*
(ICSE 2024 SEIP), https://research.google/blog/resolving-code-review-comments-with-ml/ — *"40% to 50%
of all previewed suggested edits are applied by code authors."* GitHub Copilot Autofix claims
suggestions that remediate *"more than two-thirds of found vulnerabilities with little or no editing"*
— https://github.blog/news-insights/product-news/found-means-fixed-introducing-code-scanning-autofix-powered-by-github-copilot-and-codeql/
(the vendor blog carries this; the docs page does not). Meta's Getafix (OOPSLA 2019),
https://dl.acm.org/doi/10.1145/3360585 — ~80% of fix candidates pass all tests, and top-suggestion
exact-match ranges **12%–91% depending on bug category** — that per-category spread is itself the
argument for measuring per rule, as `fix_confidence.yaml` already does.
⚠️ Meta SapFix's "48% correctly repaired" is **not** in Meta's primary blog post; do not cite it.
⚠️ No lab-authored (Anthropic/OpenAI/Google) source asserting "outcome metrics beat preference
metrics" was found; that framing rests on practitioner writing.

**Bandits — the literature is against the reference app's design.** Optimizely's own docs:
*"you should never use MAB tests for exploratory hypotheses or variation selection"* and MABs
*"do not generate statistical significance and do not use a control or baseline experience"* —
https://support.optimizely.com/hc/en-us/articles/4410289035405. Eppo's head of statistics engineering
names four conditions under which a bandit is the wrong tool — biased estimates because *"the choices
they make in the future depend on past outcomes"*, non-stationarity, multiple guardrail metrics
requiring a single summary number, and delayed feedback —
https://www.geteppo.com/blog/bandit-or-experiment. **All four describe a thumbs-driven model router
exactly.** The rigorous version: Hadad, Hirshberg, Zhan, Wager & Athey, PNAS 118(15) (2021),
https://www.pnas.org/doi/10.1073/pnas.2014602118 — estimators on adaptively-collected data
*"can be biased or heavy-tailed."* If a bandit is ever wanted, the correct algorithms are Thompson
sampling (Chapelle & Li, NIPS 2011) or UCB (Auer et al., 2002) — not proportional-to-mean.

**Multi-tenant AI *quality* dashboards.** ⚠️ **There is no published prior art.** The vendor ecosystem
converged on per-tenant *cost* attribution and per-user score segmentation (Langfuse's user view is
the closest primitive, https://langfuse.com/docs/observability/features/users). Everything else
returned on this query was content marketing. This is worth stating plainly: we are not behind a
standard here, because there isn't one.

### 1.5 The Tom / Isaac test — answered honestly, because it changes the design

Henry's standing rule is *"does this move Tom / Isaac / Sephora forward?"* Tested rather than assumed:

**Tom: partially yes, and he asked for something more specific than a dashboard.**
`docs/product/STATE_AND_VISION.md:203-249` records Tom as a technical founder with ~15 years building
AI eval/test suites. Two of his ranked items land here:

- Gap #5, verbatim: *"LLM / agent-trace observability in the HUD — his home turf; **eval the whole
  agent trace**, replay provenance if something escapes the sandbox."* (`:241-243`)
- His meta-advice: *"trust agent output via **golden-dataset eval + confidence values**."* (`:247`)

So Tom validated **trace-level evaluation, replay, and per-output confidence values**. He did not ask
for a leaderboard of model averages — and being an eval professional, he is the single worst audience
for one. A bar chart of thumbs averages is the artifact he would dismantle in the first minute of a
demo. The design consequence is D11: build the *confidence value on the artifact* and the *trace*, and
treat the aggregate panel as secondary.

**Isaac: no. This does not move him, and the claim should not be made.**
ADR 0023 quotes the architecture review directly (`0023:72`):

> *"Provenance/audit of **our own agents** is BUILT and is a strength … Monitoring the **customer's**
> agents (Isaac's ~60: 'what did MY agents do, under what identity') is the genuinely unbuilt bet."*

Isaac's question is about **his** agents, not ours. A panel grading autosec's fourteen agent types
answers a question he did not ask. His named minimum bar is ADR 0021 P0 (a working Vercel Prowler
scan), and his buying trigger is a forwardable document for his own enterprise customers
(ADR 0023 D7, `:447-466`). **Henry's claim that agent-level grading is good for Isaac is not supported
by the record.** There is a genuine adjacency — the ADR 0031 per-tool outcome/latency/declaration
substrate is the same substrate ADR 0023 D2 would need — but that is an argument for *sequencing*,
not for telling Isaac this feature is for him.

**William: no, and he argues against the aggregate.** His feedback was *"a single actionable digest,
not a wall of findings."* A model-performance panel is, by construction, another wall — more numbers,
no action. It earns its place only if a number on it leads to a decision (switch, escalate,
investigate a trace).

**The reframing this forces.** The operator question is **not** *"how is this agent performing?"* It
is *"can I trust what it just did to my infrastructure?"* Those differ in three ways that matter:

| | "How is the agent performing?" | "Can I trust what it did?" |
|---|---|---|
| Unit | agent, aggregated over time | one artifact — this finding, this PR |
| Timing | retrospective | at the moment of the decision |
| Audience | workspace admin / buyer of the platform | on-call operator |
| Existing surface | the dark AI-quality overview | `fix_confidence` label, written and never rendered |

Both are legitimate; they are different products. **D11 splits them and refuses to merge them.**

### 1.6 Reconciliation with ADR 0018 — not re-opened

ADR 0018 (Judgment Flywheel) is Proposed / **BUILD DEFERRED** ("Henry: *'I want to build it, but not
today'*"). Its D1 extends Remediation Memory capture from *fixes* to *reasoning*. This ADR does not
re-litigate that thesis, does not propose the copilot or the drills, and takes no position on whether
0018 should be built.

The one place they touch: 0018 D1 depends on the same Remediation Memory outcome signals that §1.3.3
shows are currently inverted. **Fixing the fingerprint bug is a prerequisite for 0018 as much as for
this ADR** — a judgment store that promotes fixes which did not hold would poison the flywheel at its
source. That is a dependency note, not a re-opening.

---

## 2. Decision

### D1 — The unit of measurement is the **configuration tuple**, not the model. **[proposed]**

Measure and attribute against `(agent_type, prompt_version, model)`. Not "the model", and not "the
agent".

**Argued, not assumed.** When an agent regresses, four things could have changed: the model, the
system prompt, the tool set, or the rubric. Attributing a regression to "gpt-4o got worse" when the
real cause was `planner.system` moving from v11 to v12 is the credit-assignment failure the reference
app makes structurally (`score.py:40-47`, one score written to three components). We have the version
identities to avoid it — `PromptRegistry` already versions prompts by `<prompt_id>` × `<version>`
(`registry.py`; `planner.system` is at `active: v12` with v1–v12 retained).

**The gap that makes this a build item rather than an observation:** **no run records which prompt
version it used.** `DeepRunLog` has `system_prompt`/`user_prompt` raw text and `model_used`
(`infrastructure/persistence/ai/agents/models.py:398-406`) but no `prompt_id`/`prompt_version` column,
and a repo-wide grep for `prompt_version` outside tests returns nothing. `model_used` is populated
only on planner `llm_call` rows (`llm_planner.py:219`); a `tool_observation` row leaves it blank.
`DeepRun` itself has no model field at all. So today two runs on different prompt versions are
distinguishable only by diffing stored prompt blobs.

**Scoped honestly — the fourth dimension is deferred, with a reason.** The task proposed a four-part
tuple including tool-contract version. **Rejected for now**: there is no tool-contract *version* to
record. ADR 0031 D8 deliberately makes the contract *monotonic* (names byte-stable, schemas additive,
tiers may only rise) rather than versioned, precisely so callers never need to branch on a version.
If a tool dimension is wanted later the right shape is a **declaration digest** over the agent's
`ToolSpec` set, not a version number — see OQ5.

**Consequence.** Phase 1 stamps `prompt_version` and `model` on the run. Nothing else in this ADR is
meaningful without that stamp, which is why it is D1.

### D2 — Thumbs are a pointer to a trace, never a performance metric. **[proposed]**

A thumb measures irritation, not quality: explicit feedback has low response rates and unhappy users
are likelier to respond (Langfuse, §1.4). We already use it correctly —
`promote_feedback_to_dataset.py:193-195` turns **downvotes into candidate eval cases for human
review**, deliberately leaving `expected` empty (`:134`). That is the right treatment and it is built.

**Decided:**
- Feedback is displayed as **counts with an explicit denominator** — `feedback_up`, `feedback_down`,
  and `feedback_rate = (up + down) / assistant_messages`, all three of which
  `ai_quality_resources.py:74-112` already computes. Never a bare `positive_ratio` as a headline.
- No feedback figure is ever labelled "quality", "score", or "accuracy" in any surface.
- A downvote's primary product is a **link to the run**, so an operator can read the trace. That is
  the Tom ask (§1.5).
- **Rejected: implicit-signal capture in this ADR.** Copy/retry/edit/abandonment are the stronger
  signal per the literature, but capturing them is a frontend instrumentation project with its own
  privacy surface. Named as future work (OQ6), not smuggled into scope.

### D3 — One statistic for measured trust, and it already exists. Generalise `fix_confidence`; do not write a second. **[proposed]**

Every rate we display that drives a decision uses the **one-sided 95% Wilson lower bound with a
minimum-trials floor and an evidence-expiry window**, i.e. the exact mechanism in
`components/code_security/domain/fix_confidence.py`. Not a mean. Not a Wald interval. Not a bare
percentage.

**Decided:**
- **Generalise, don't copy.** The statistic and the tiering are domain-neutral; the SAST rule-corpus
  loader is not. Lift `wilson_lower_bound` + the tier ladder into the shared kernel and have
  `code_security` consume it, so there is exactly one implementation. A second copy would be the
  precise defect `dry-reuse.md` §4 forbids ("one canonical thing per concern"), and the divergence
  would show up as two different confidence numbers for the same fix.
- **Keep all four of its honest behaviours**: three tiers rather than a boolean; absence is a verdict
  (`confidence_for` never returns `None`); the floor exists so the message can say *"2 trials"*; and
  evidence expires.
- **Add the rule of three for zero-failure cases.** "0 failures in 12 runs" must not render as 100%;
  the 95% upper bound is ≈ 3/12 = 25% (Hanley & Lippman-Hand, §1.4). Display the bound, not the point
  estimate.
- **Rejected: the reference app's mean-with-optimistic-prior** (`score.py:21-24`), which reports a
  perfect score for an unmeasured component.

### D4 — Absence is a distinct, visible state. No panel is ever green because nothing ran. **[proposed]**

This is the #415 defect ("an empty report must not read as a clean one") applied to AI quality. Every
metric renders in exactly one of three states, and the state is part of the contract, not a frontend
choice:

| State | Condition | Renders as |
|---|---|---|
| `no_data` | zero observations in the window | *"Not measured — 0 runs in the last 30 days"*, visually neutral. **Never green.** |
| `too_few` | below the trials floor | the raw fraction plus *"too few runs to distinguish a good agent from a lucky one"* — the `measured_weak` wording already in `fix_confidence.py:266-277` |
| `measured` | at or above the floor | the Wilson lower bound, with n |

The overview endpoint already emits zero-activity days for a continuous axis
(`ai_analytics_repository.py:68-70`); those days must render as *no data*, not as a zero-height bar
that reads as "no failures".

**Corollary on peeking.** Because a dashboard is watched continuously, no panel may display a
significance verdict, a "winner", or a red/green comparison badge between two configurations
(Johari et al., Optimizely, §1.4). Comparisons live in the harness (D5) with a stated stopping rule.

### D5 — Comparison happens in the offline harness on identical inputs. The dashboard reports comparisons; it never computes one. **[proposed]**

Production aggregates cannot honestly compare two models, because assignment is not random: model A
may simply have drawn harder findings. Radlinski et al. (§1.4) found that *none* of eight absolute
usage metrics reliably reflected quality at realistic sample sizes, while paired comparison on
identical inputs did.

**Decided:**
- **Paired evaluation on identical inputs** is the comparison mechanism: the same frozen dataset, run
  through both configurations, scored the same way. We already have this —
  `run_planner_eval.py:182`, `run_writing_eval.py:165`, `run_feedback_eval.py:146`,
  `run_sast_fix_eval.py`, all emitting `_meta{prompt_id, version, gen_model, judge_provider}` blocks
  and `average_score` / `pass_rate_at_seven`. The harness is built; it is unscheduled and
  workspace-blind.
- **Chosen over randomisation and over stratification**, deliberately: online randomised assignment
  needs traffic volume we do not have at a single tenant; pre-stratification is impractical online
  because data arrives over time (Deng et al.); and paired-on-identical-inputs removes the confound
  outright rather than adjusting for it. It also costs nothing in production risk.
- **The panel displays the harness result** — "gpt-4o vs gpt-4o-mini on the 40-case planner set,
  2026-08-19" — and links to the report. It does not derive a comparison from live traffic.
- **Rejected: bandit / weighted-random selection** as in `score.py:4-33`. Optimizely: *"never use MAB
  for variation selection"*; Eppo's four disqualifying conditions all hold here; Hadad et al. show
  estimates on adaptively-collected data are biased. A traffic share is not evidence.
- **Rejected: shadow/replay traffic** for Phase 1. It is the right long-term mechanism (SageMaker
  Shadow Tests, §1.4) but doubles inference cost and needs a replay harness we do not have.
- **Reliability, not just success rate.** Where a configuration is compared on a repeated task, report
  τ-bench-style `pass^k` alongside `pass@1` (§1.4) — a 90% single-attempt agent is 57% reliable at
  k=8, and for a tool that edits infrastructure the second number is the one that matters.

### D6 — The strongest signal is outcome, not preference — and it must be repaired before it is displayed. **[proposed]**

For a security product, "the operator liked it" is not "the fix was right." The outcome signals we
have are: did the draft PR merge; did the finding recur; did the remediation hold; did the patch pass
the ADR 0025 oracles. Published analogues put fix-acceptance in the 40–70% range and show it varies
enormously by category (§1.4) — which is why per-rule measurement, as `fix_confidence.yaml` already
does, is the right granularity.

**Decided:**
- **The `finding_fingerprint` defect (§1.3.3) is a blocking prerequisite.** Until it is fixed, the
  recurrence branch cannot fire for SAST, container, cloud-posture, cloud-exposure, Vercel or
  planted-instruction findings, every prior is awarded `reuse_success`, and **a fix that did not hold
  is promoted rather than demoted.** Any outcome-based number shown today would be inflated in the
  most misleading possible direction.
- **The root fix is to converge the key, not to add a fallback.** The board convention is `lookup_key`
  (`finding_raised_board_handler.py:235`, and every non-logwatch card builder). Reading
  `payload.get("fingerprint")` in `board_finding_facts_repository.py:95` and
  `resolve_finding_task_repository.py:96` is the drift. Per `no-shortcuts.md`, the fix is one canonical
  key across all card builders and both readers — not an `or payload.get("lookup_key")` bandaid that
  leaves two names alive.
- **Add a fitness test that fails on a fingerprint-less card**, so the green suite stops passing over a
  dead branch. Today's integration tests hand-construct `payload={"fingerprint": …}`
  (`test_entry_gate_flow.py:50`), which is exactly why nobody noticed.
- **Outcome metrics are the headline; preference metrics are context.** Where both exist, the panel
  leads with outcome.

### D7 — Switching a model invalidates evidence gathered under the old one. Fail closed, and say so at the moment of the switch. **[proposed]**

This is the subtlest consequence of the feature Henry asked for, and the codebase has already decided
it once: `fix_confidence.py:257-258` returns `unproven` with *"measured on X, running Y — measurements
do not transfer between models"*. The committed evidence is `model: gpt-3.5-turbo`; **a workspace that
switches model today silently drops every SAST rule to `unproven`.**

**Decided — the same rule, generalised, made loud:**
1. **Evidence is keyed by the D1 tuple.** A change to any element starts a new measurement series. Old
   evidence is retained and clearly attributed to the old configuration; it is never silently
   re-used under the new one.
2. **Fail closed, consistently.** Post-switch the tuple is `no_data` (D4) until it clears the trials
   floor. It does **not** inherit the previous configuration's tier.
3. **The switch UI must state the cost before the switch, not after.** *"Switching to `<model>` will
   drop 4 SAST rules from `proven` to `unproven` and reset agent measurement for this workspace.
   Re-measurement requires ≥10 trials per rule."* A switch that quietly revokes measured trust is the
   same class of defect as a report that reads clean because nothing was scanned.
4. **Write the change event.** `AIModelChangeEvent` exists, is read by
   `ai_analytics_repository.py:93`, and **has no writer** — so the model-change annotation on the
   series is permanently empty. `update_ai_config` must emit one. Without it "did the switch help?"
   is unanswerable, and that is the whole point of the feature.
5. **Emit an audit event and a notification.** A model switch has cost, quality and trust blast
   radius; the audit context and notifications context both exist for exactly this.
6. **Anti-thrash.** The panel must not invite switching-on-noise. Because post-switch evidence starts
   empty and needs ≥10 trials, a workspace that switches weekly never accumulates measured trust —
   state this in the UI copy rather than relying on the admin to infer it.

### D8 — Aggregates are workspace-scoped, sample-excluded, and honest about what they dropped. **[proposed]**

1. **Scoping** follows the canonical pattern — `.filter(workspace_id=…)` on `DeepRun`,
   `deep_run__workspace_id=…` on `DeepRunLog` (`orm_deep_run_query_repository.py:421-422`). Every new
   read seam ships an isolation test, per `django-conventions.md` §Tenancy.
2. **No unscoped path.** The `workspace_id is None` → cross-tenant fallback at
   `orm_deep_run_query_repository.py:419-420` (reachable via `GET /runs/stats/` for `is_staff`,
   `controller.py:1709-1713`) must not be extended to any new endpoint. A staff/global view, if
   wanted, is a separate explicitly-named endpoint — never a nullable parameter on a tenant one.
3. **NULL-workspace runs are counted and disclosed.** `DeepRun.workspace` is nullable
   (`models.py:361`), so unattributed runs are invisible to every aggregate. The panel states
   *"N runs excluded (no workspace attribution)"* rather than silently undercounting.
4. **Sample data is excluded, and the exclusion is a stated number.** Copy the one correct precedent —
   `ssot_finding_repository.py:246-253` filters it out and `:117/:135/:142` count and report what was
   dropped. Sample findings must not enter any AI-quality aggregate. (Note for scope: the same
   exclusion is *missing* from compliance, ATT&CK and exposure totals — §1.3.6. That is a real defect
   and it is **not** this ADR's to fix; it is named so it is not lost.)
5. **Eval reports get workspace scoping.** `GET /api/ai/prompt-eval/reports/` currently serves every
   report on disk to any authenticated user of any tenant (`controller.py:2992-3095`). If the panel
   links to harness reports, that endpoint must be scoped first.

### D9 — Cost and latency are first-class in the switching decision, and they are already computed. **[proposed]**

A model choice is a quality/cost/latency trade, not a quality decision (§1.4: FrugalGPT, RouteLLM,
Not Diamond's ~100–150ms routing overhead). We already compute all three per model per day —
`ai_quality_resources.py:25-34` exposes `llm_calls`, `prompt_tokens`, `completion_tokens`, `cost_usd`,
`latency_p50_ms`, `latency_p95_ms`, priced by `components/agents/domain/services/llm_pricing.py::price_run`.

**Decided:** the switch surface shows quality, cost-per-run and p95 latency **side by side, for both
the current and the candidate configuration**, sourced from the harness (D5) for quality and from the
rollups for cost/latency. p95 rather than mean, because the tail is what an operator waiting on a
triage feels. Existing budget caps in `workspace_ai_config.py:156-158` remain the enforcement
mechanism; this panel is the *information* for the decision, not a second enforcement point.

### D10 — Changing a model is a governed action. Today it is not governed at all. **[proposed]**

**Blocking prerequisite (§1.3.5):** `PATCH /ai/agents/ai-config/update` has no membership or role
check and accepts any `workspace_id` from any authenticated user (`controller.py:671-695`). This ADR
cannot propose an admin model-switching feature on top of an endpoint with a cross-tenant write hole.
Fix ships first, as its own security PR.

**Decided, once the hole is closed:**
1. **Role:** require `manage_agents`, matching the kill switch (`permissions.py:39-54`,
   `controller.py:1019-1024`) — the closest existing analogue in blast radius. Per
   `seed_workspace_roles.py:75-80`, `owner` and `admin` hold it; `_MEMBER` and `_VIEWER` do not.
2. **Validate the write.** `WorkspaceAIConfig.is_model_valid()` (`workspace_ai_config.py:285-288`)
   exists and is never called on the write path, and there are two unreconciled sources of truth for
   the allowed model list — the DB catalog `AIModel` (`ai/llms/models.py:10,38`) and a hardcoded
   `AVAILABLE_MODELS` dict (`workspace_ai_config.py:30-53`). Converge on the DB catalog as the single
   source and validate against it. Also replace the blind `existing_dict.update(incoming)`
   (`controller.py:688`) with a field allowlist.
3. **Relationship to the kill switch:** the kill switch stops AI; the model switch changes it. Both
   are `manage_agents`. Neither is ever an agent tool — the controller docstring at `:1034-1035`
   (*"the AI can report on the switch but never touch it"*) is the correct precedent and applies
   equally here.
4. **Risk ladder:** a model switch is a `REVERSIBLE_WRITE` in the `tool_risk.py:26-31` vocabulary —
   reversible, but with a non-reversible side effect (measured evidence resets, D7). That asymmetry is
   why it warrants an audit event even though it is reversible.
5. **Sign-off:** *not decided here* — OQ2. `sign_off` today gates only `newsletter`, `writing_draft`
   and the remediation entry gate; **no AI or model-configuration artifact is gated**
   (`content_sign_off_provider.py:37-41`, `remediation/infrastructure/adapters/sign_off_gate_adapter.py:26-52`).
   Adding one is a product call about friction.
6. **Tier gating:** *not decided here* — OQ1. The mechanism exists
   (`tier_features.py:37-52`, resolution order at `feature_flags.py:181-213`) but **every tier's
   feature set is currently empty** (`tier_features.py:32-35`), so there is no working precedent for
   gating an AI feature by plan.

### D11 — Two audiences, two surfaces. Do not merge them. **[proposed]**

Per §1.5, "how is this agent performing?" and "can I trust what it just did?" are different products.

**Surface A — the artifact confidence label (operator; Tom's and William's actual ask).**
A confidence value on the finding, the suggestion and the draft PR, at the moment of the decision.
**Most of this is already computed and thrown away:** `fix_confidence(...).as_label()` is written to
`payload["fix_confidence"]` at `code_security_agent.py:310` and **no backend reader renders it**.
Making that label visible is the highest value-per-line change in this entire ADR, and it is
consistent with the standing rule that a grounding failure downgrades the confidence *label* and never
withholds the artifact.

**Surface B — the workspace AI-quality panel (workspace admin; Henry's literal ask).**
Per-tenant, windowed: runs, failure rate, per-model cost/latency, feedback counts with denominators,
model-change annotations, and a link to the latest harness comparison. Admin-only, secondary
navigation, not on the operator cockpit. **Every number on it obeys D3 and D4** — bound-with-n or an
explicit absence state.

**Rejected: an agent leaderboard.** Ranking our fourteen agent types against each other is the
reference app's bar chart with more rows. It confounds difficulty with quality (agents handle
different finding classes), invites a bandit response, and is the artifact Tom would take apart first.

### D12 — Turn on what exists before building what does not. **[proposed]**

Six built-and-dark surfaces are enumerated in §1.3.2. Lighting them is cheaper than any new feature
and delivers most of ask (1):

- schedule `ai.rollup_ai_quality_daily` → the overview endpoint stops returning zeros;
- fix the rubric verdict key mismatch (`rubric.py:285` writes `verdict`,
  `orm_deep_run_query_repository.py:212-215` reads `satisfied`/`passed`) → our only judge stops
  reporting 100% failure;
- write `AIModelChangeEvent` from `update_ai_config` → the switch annotation exists (D7.4);
- render the `fix_confidence` label (D11 Surface A);
- schedule `agents.run_reviewer_feedback_eval`;
- decide whether `build_get_few_shot_negatives_use_case` (no caller) should be wired or deleted —
  dead code either way.

**Two explicit non-decisions in this decision:**
- **RubricMiddleware stays off in production**, and no judge score appears on any admin surface, until
  it is calibrated against human labels on a sample. Our grader is `gpt-4o-mini` (`rubric.py:48`)
  grading frontier-model output, which is precisely the regime where Dorner et al. (ICLR 2025) show a
  judge cannot substitute for ground truth. Turning it on is a *measurement* task before it is a
  *display* task.
- **Expanding rubric coverage beyond 3 of 14 agent types** (`deep/critic.py:36`) is not decided here —
  OQ4. Each added agent adds a grading LLM call per worker answer.

---

## Alternatives considered and rejected

| Alternative | Why rejected |
|---|---|
| **Port the reference app's design** (global average + weighted-random selection) | Seven documented defects (§1.2): broken credit assignment, no n, optimistic cold-start prior, no tenancy, no expiry, no cost/latency, and a selector the bandit literature explicitly warns against for variation selection. |
| **Buy it — expose Langfuse or LangSmith per tenant** | Genuinely tempting: the Langfuse adapter is already built and pinned (`langfuse==3.15.0`, `requirements/base.txt:112`; adapter `tracing/langfuse.py:112`), and Langfuse's per-user score+cost segmentation is the closest documented primitive to what Henry described (§1.4). Rejected because (a) it is disabled — both keys default to `""` in `local.py:136-137` and `prod.py:124-125`, and the EC2 overlay drops the stack entirely; (b) traces are keyed by **conversation id, not run id** (`base.py:1233-1242`), so a Langfuse trace cannot be joined to a `DeepRun`, and scheduler/detector-initiated runs have no conversation and therefore no trace at all; (c) it knows nothing about findings, PR merges or recurrence — the outcome signals D6 says are the headline; (d) exposing a per-tenant view of our engineering observability tool is a tenancy surface we do not want. **Keep Langfuse for our own engineering; build the tenant-facing panel on our own rollups.** |
| **LLM-as-judge over all agent output, surfaced as the quality number** | §1.4: position, verbosity and self-preference biases are documented; pairwise preferences flip in 35% of cases under a distractor; and a `gpt-4o-mini` judge cannot beat ground truth for frontier-model output. A judge is a *triage* tool (find traces worth reading), not a metric. |
| **Automatic model switching based on measured performance** | The literature is against it for variation selection (Optimizely, Eppo, Hadad et al.), and for a security product an unattended model change is a change to the thing that writes to customer infrastructure. Henry asked for admin-driven switching; that is also the correct design. |
| **Drift detection in Phase 1** | Evidently's own caveat — *"no universal way to define data changes that strictly correlate to model quality"* — makes drift a trigger to look, not a metric. Not worth its complexity before the basics are lit. |
| **Add a `or payload.get("lookup_key")` fallback for the fingerprint bug** | A bandaid that leaves two key names alive and the drift unfixed (`no-shortcuts.md`). D6 converges the key instead. |

---

## 3. Phased plan

### Phase 0 — Blocking prerequisites. Not part of this feature; ship separately, first.

| # | Work | Why blocking |
|---|---|---|
| 0.1 | **Authorize `PATCH /ai/agents/ai-config/update`** (`controller.py:671-695`) — `manage_agents`, membership check on `workspace_id`, field allowlist, validate the model against the DB catalog. Add the tests that do not exist. | We cannot ship an admin model-switching feature on an endpoint any tenant can write to (§1.3.5). Same class as #414/#416/#417/#419. |
| 0.2 | **Fix `finding_fingerprint`** — converge on one key across card builders and both readers (`board_finding_facts_repository.py:95`, `resolve_finding_task_repository.py:96`), plus a fitness test that fails on a fingerprint-less card. | Until this lands, the outcome signal is inverted and any success number is inflated (§1.3.3). Also a prerequisite for ADR 0018 D1. |

### Phase 1 — Small, honest, mostly switch-flipping. *This is the recommended first slice.*

Nothing here invents a new statistic or a new page. Roughly: light the dark, stamp the tuple, render
the one honest number we already compute.

1. **Stamp the D1 tuple.** Persist `prompt_version` (and `model`) on the run so a measurement can be
   attributed. Without this, everything downstream is uninterpretable.
2. **Schedule `ai.rollup_ai_quality_daily`** so `GET /runs/analytics/overview/` stops returning zeros.
3. **Fix the rubric verdict key mismatch** so `rubric_pass_count` reports reality (it stays a dev-only
   signal per D12 — fixed, not surfaced).
4. **Write `AIModelChangeEvent`** from the config-update path.
5. **Render the `fix_confidence` label** on the finding / suggestion / draft PR (D11 Surface A) — the
   highest value-per-line item in the ADR, and the direct answer to Tom's *"confidence values"*.
6. **Generalise the Wilson/tier module** into the shared kernel; `code_security` consumes it (D3).
7. **One admin panel** (D11 Surface B) over the *existing* overview endpoint, with the three D4 states,
   n on every rate, sample and NULL-workspace exclusions counted and disclosed.
8. **The switch-cost warning** on the model-change UI (D7.3) plus the audit event.

**Explicitly NOT in Phase 1:** paired model comparison, agent-level grading, judge scores on any
customer surface, implicit-feedback capture, drift, routing.

### Phase 2 — Comparison you can act on

Schedule the harness (`run_planner_eval`, `run_writing_eval`, `run_feedback_eval`, `run_sast_fix_eval`);
make it workspace-aware (`run_planner_eval.py:44` and `run_writing_eval.py:40` hardcode
`EVAL_WORKSPACE_ID`); scope `GET /prompt-eval/reports/` (D8.5); add a **paired two-configuration run**
producing a single comparison artifact with quality + cost + p95 latency (D5, D9); make that artifact
the **gate before a switch** — the admin sees the comparison on the frozen dataset before committing.
Report `pass^k` alongside `pass@1`.

### Phase 3 — Outcome-linked confidence, and agent level if it earns its place

Once Phase 0.2 has been in place long enough to accumulate real recurrence data: extend the measured
tier from per-SAST-rule to per-configuration-tuple, keyed on outcomes (PR merged, finding did not
recur, oracle passed). **Only here does "how is this agent doing" become answerable honestly** — and
only for agents whose work produces a checkable outcome. For agents whose output is advice with no
verifiable outcome, say so rather than inventing a number.

### Phase 4 — Deferred, revisit with evidence

Judge calibration against human labels (prerequisite to any judge score on a customer surface);
implicit-feedback capture; drift detection; shadow/replay evaluation; expanding rubric coverage past
3 of 14.

---

## 4. Open questions for Henry

**OQ1 — Is model switching a paid capability?** Pure pricing. The mechanism exists
(`tier_features.py:37-52`) but every tier's feature set is empty (`:32-35`), so there is no working
precedent. This is the same question as **ADR 0031 OQ2** ("which capabilities exist, which agents hold
them, which are paid tier") and open task #126. Note the documented counter-precedent: the pricing
recommendation says `feature.ai_kill_switch` must **never** be gated, because no CNAPP in the market
paywalls a kill switch. Does the same logic apply to model choice? *Not decided here.*

**OQ2 — Should a model switch require sign-off?** Today no AI or model-configuration artifact is
sign-off-gated. Adding one buys an audit trail with an approver at the cost of friction on a
reversible action. Product call.

**OQ3 — Do we expose the model catalog per tenant, or a curated allowlist?** `AIModel` is a global
table with no workspace FK (`ai/llms/models.py:10`). Should every tenant see every model we have keys
for? A dedicated-tier tenant (ADR 0029) may want its own; a pooled tenant probably should not choose
a model we have not measured on their finding classes.

**OQ4 — Do we show customers how *our* agents score at all?** Tom would value it (he builds eval
suites). A less technical buyer may read "78% measured" as "your product is wrong 22% of the time."
The alternative is admin-only-and-off-by-default. This is positioning, not engineering.

**OQ5 — Is the tool dimension worth adding to the D1 tuple later?** It would need a declaration digest
over the agent's `ToolSpec` set, since ADR 0031 D8 deliberately versions nothing. Cheap to add, but
only once tool declarations are widespread (D1 is deferred on it today).

**OQ6 — Implicit feedback: worth the instrumentation?** The literature says copy/retry/edit/abandon
are the stronger signal. It is a frontend project with a privacy surface, and it is the natural
successor to D2 if thumbs stay as sparse as expected.

**OQ7 — Sequencing against the standing priority.** Does any of this clear the "harden the core loops
for Tom's real use" bar *now*? My reading: **Phase 0 does unambiguously** (an authz hole and an
inverted outcome signal are core-loop defects regardless of this feature), **Phase 1 item 5** — the
confidence label — does, because it is Tom's literal ask. The admin panel is a genuine but secondary
want. If only one thing ships, ship Phase 0.

---

## 5. What I could not verify

Stated plainly rather than papered over.

1. **Thumbs response-rate percentages.** No credible primary source exists for the commonly quoted
   "1–3%". The figure is not on the Langfuse page it is usually attributed to. Only the *direction*
   (sparse, negatively biased) is cited.
2. **Whether the rollup beat entries are absent in the *running* cluster.** I verified their absence
   from `api/settings/{dev,local,prod}.py` by reading the files. I did not query the live beat
   schedule (read-only constraint), so the possibility of an out-of-band schedule is not excluded.
   *Hypothesis, high confidence:* the overview series is empty in the running system.
2b. **The `AIModelDailyMetric` / `tool_observation` row counts** (a ~9,300-row figure was quoted to me).
   I did not query the database. Nothing in this ADR depends on the number.
3. **Whether the recurrence branch has ever fired for `ai.log_watch` / `ai.log_optimization`.** Those
   two sources *do* write `payload["fingerprint"]` (`log_ingest_service.py:431`,
   `log_pattern_analyzer_service.py:139`), so the branch is reachable for them in principle. I found
   no test exercising it with a real detector-produced payload, and I did not check production data.
   The SAST/container/cloud-posture/exposure/Vercel claim is verified end to end from code.
4. **The "sweep last night" on sample data in compliance / exposure / ATT&CK totals.** No commit,
   branch or PR mentions it; the nearest artifacts are pending tasks #159 and #33. The *underlying
   defect* is confirmed directly from code (§1.3.6) and this ADR asserts it on that basis alone.
5. **Several literature figures I chose not to lean on**: interleaving's "10×–100× sensitivity", CUPED's
   "~50% variance reduction", and Meta SapFix's "48% correctly repaired" (verified *absent* from Meta's
   primary post). The mechanisms are cited; the numbers are not.
6. **Agent-type count.** 14 agent modules carry `@register_agent` under
   `components/agents/infrastructure/adapters/langchain/agents/`. I counted modules, not registrations;
   a module registering more than one type would raise the figure.
7. **Whether `update_ai_config`'s missing authz is mitigated by middleware.** I read the code path and
   found no check in the view, the action, or the adapter. I did not exercise it at runtime — deliberately,
   since doing so would mean writing to another tenant's configuration.
8. **No LLM calls were made and no data was mutated** in producing this ADR. Cost incurred: none beyond
   local file reads and web research.

---

## 6. Consequences

**If accepted:**

- The confidence statistic in this codebase becomes one thing, in one place, used by SAST fixes and
  agent measurement alike — instead of `fix_confidence.py` plus a second, weaker copy grown for a
  dashboard.
- Two live defects get named, dated and owned: a cross-tenant write on the AI-config endpoint, and an
  inverted outcome signal in Remediation Memory that also blocks ADR 0018.
- Most of Henry's ask (1) resolves to scheduling a task and rendering a label that is already
  computed — which is a better answer than a build plan.
- Ask (2) is honestly scoped: agent-level grading becomes meaningful only in Phase 3, for agents whose
  work produces a checkable outcome, and it is not something to promise Isaac.

**If rejected or deferred:** Phase 0 should be lifted out and shipped anyway. Neither item is
contingent on the dashboard.

**Risks:**
- **The panel is built and nobody looks at it.** William's *"not a wall of findings"* applies. Mitigated
  by D11's split — the operator gets a label at the point of decision, not a page to visit.
- **Measured tiers rarely reach `proven`** at a single tenant's volume, so the panel reads perpetually
  `too_few`. That is honest, and it is the correct signal that we should be running the harness (D5)
  rather than waiting on production traffic — but it will feel unsatisfying, and the UI copy has to
  own it rather than hide it.
- **The switch-cost warning discourages switching**, which is the feature Henry asked for. That is the
  intended trade: a switch that silently revokes measured trust is worse than a switch that is
  slightly harder.
