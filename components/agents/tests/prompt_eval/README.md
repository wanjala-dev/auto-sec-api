# prompt_eval

The prompt-engineering + prompt-evaluation suite for the agents bounded
context. Mirrors the structure of
[`faura/midtier-scoring-fork/prompt_eval`](file:///Users/henrywanjala/faura/midtier-scoring-fork/prompt_eval/README.md)
and operationalises the Logseq Anthropic curriculum
(`~/Documents/journals/2026_04_24.md`, `~/Documents/journals/2026_05_05.md`,
`~/Documents/journals/2026_02_24.md` item 16).

## Layout

```
components/agents/tests/prompt_eval/
  README.md                          ← this file
  __init__.py
  hygiene.py                         ← reusable rule predicates (also used by pre-commit)
  test_prompt_hygiene.py             ← rule-based regression guardrail
  test_planner_quality.py            ← LLM-graded eval (env-gated)
  prompts/                           ← frozen baselines, checked in for diff comparison
    planner_system_v1.txt
    planner_project_v1.txt
    planner_task_v1.txt
    estimator_system_v1.txt
    estimator_repair_v1.txt
    grader_planner_judge_v1.txt
    _freeze.py                       ← one-off helper, re-runnable when bumping versions
  datasets/                          ← hand-authored golden cases per prompt
    planner_v1.json
  fixtures/                          ← per-case fixtures (workspace context, etc.)
  graders/
    code/                            ← deterministic graders (one per file)
      plan_shape.py
      agent_type_routing.py
      banned_words.py
      json_validity.py
      _types.py                      ← CodeGradeResult / AggregateCodeGrade / CodeGrader
    model/                           ← LLM-as-judge (multi-axis)
      planner_judge.py               ← single LLM call returning {tone, instruction_following, completeness, safety}
      _types.py                      ← AxisScore / ModelGradeResult / ModelGrader
  runners/                           ← entry points per prompt (future expansion)
  reports/                           ← gitignored — local HTML/JSON output
```

The reusable harness (`PromptEvaluator`) lives in
`components/agents/infrastructure/evaluation/prompt_evaluator.py` —
it's grader-agnostic infrastructure. The graders, datasets, frozen
prompts, and hygiene rules all live here, in the tests tree.

## The loop

The discipline: draft a prompt, run a frozen dataset through it, grade
the output, change the prompt, repeat. The dataset is built once and
frozen — only the prompt changes each loop, which keeps consecutive
runs comparable (it turns "this edit feels better" into "this edit
moved the score from 7.66 to 8.77, and one rule now fails").

```
1. Draft a prompt              →  edit the source module
        │                          ↓ snapshot to prompts/<name>_vN.txt
        ▼
2. Run hygiene tests           →  pytest test_prompt_hygiene.py
        │
        ▼
3. Run the dataset             →  PROMPT_EVAL_E2E=1 pytest test_planner_quality.py
        │                          ↓ writes HTML+JSON to docs/eval-reports/
        ▼
4. Read the report             →  per-axis scores, worst-case panels, code-grader reasons
        │
        ▼
5. Change ONE thing and repeat ──┐
        ▲                        │
        └────────────────────────┘
```

## Two enforcement layers

### Layer 1 — Hygiene (rule-based, deterministic, fast, gated)

`test_prompt_hygiene.py` enforces five rules from the curriculum
against six prompts (the five planner/estimator prompts + the judge
prompt itself). These rules catch surface-level regressions before any
LLM cost is incurred.

The rules live in `hygiene.py` so the same predicates are usable
from:
- The unit-test regression guardrail.
- The pre-commit hook (added to `.pre-commit-config.yaml` — runs only when one of the tracked prompts is edited).
- The EC2 deploy gate (runs as part of `components/agents/tests/`).
- A future `manage.py check_prompt_hygiene` CLI helper.

The rules:

1. **No ALL-CAPS urgency markers ≥4 chars.** `CRITICAL`, `MUST`,
   `NEVER`, `ALWAYS` cause overtriggering on modern frontier models.
   Whitelisted technical tokens (`JSON`, `URL`, `API`, …) are exempt;
   add new ones to `hygiene.ALL_CAPS_TECHNICAL_WHITELIST`.
2. **No anti-pattern phrasing.** `Do NOT`, `MUST NOT`, `HARD
   REQUIREMENT` cause the model to fixate on the forbidden behaviour.
   Rewrite as a positive instruction. The one carve-out: standalone
   `NOT` between two named agents (`task_agent, NOT workspace_agent`)
   is a routing disambiguator, not a fixation magnet.
3. **No fallback-route phrases.** `if in doubt`, `fallback to` cause
   the default path to overtrigger and fabricate. Replace with a
   clarifying-task pattern.
4. **Every routing rule has a `because:` clause.** Models generalise
   better from reasons than from raw rules. Enforced on the planner
   system prompt's per-specialist bullet routing rules.
5. **JSON-emitting prompts include a literal `{"..."` example.**
   Prose descriptions are less imitable than concrete examples.

### Layer 2 — Quality (LLM-graded, data-driven, opt-in)

`test_planner_quality.py` runs the dataset through the harness and
asserts the aggregate score is above a soft floor
(`PLANNER_QUALITY_FLOOR=5.0`). It is gated on `PROMPT_EVAL_E2E=1`
because every run costs real LLM tokens (~$0.10 per 15-case run).

Per the project's locked decision, score regressions are
**informational only** — they do not block PR merge or deploy. The
hygiene gate is the deploy guardrail; the quality eval is the dev
microscope.

## Adding a new prompt

When a new bounded context ships its own system prompt (e.g.
`sponsorship`, `grants`):

1. Author the prompt following the five hygiene rules. Use the
   existing prompts under `prompts/*.txt` as references — they are
   the canonical positive examples.
2. Add the prompt to `PROMPTS_UNDER_TEST` in `test_prompt_hygiene.py`.
3. Freeze the v1 snapshot under `prompts/<prompt_name>_v1.txt` by
   updating `prompts/_freeze.py`'s `EXTRACTS` list and running
   `python components/agents/tests/prompt_eval/prompts/_freeze.py`.
4. Add the prompt's source module path to the pre-commit hook's
   `files:` regex in `.pre-commit-config.yaml` so the hook re-runs
   when the prompt is edited.
5. If the new prompt warrants its own eval dataset, hand-author one at
   `datasets/<prompt_name>_v1.json` following the planner_v1 shape:

   ```json
   {
     "_meta": {"name": "<name>_v1", "description": "...", "schema_version": 1, "case_count": N},
     "cases": [
       {"id": "...", "category": "...", "scenario": "...", "goal": "...", "criteria": "..."},
       ...
     ]
   }
   ```

   Add corresponding code/model graders under `graders/` and a
   `test_<name>_quality.py` runner alongside `test_planner_quality.py`.

## Adding a new dataset case

Cases stress one rule per case. A good dataset balances:

- **Tripwires** — cases the prompt SHOULD route correctly but
  historically failed (e.g. `routing-assign-followup` for the
  2026-05-08 cascade).
- **Positive controls** — cases the prompt should handle naturally so
  the dataset catches over-correction (e.g. a high-risk wildfire case
  in CA when the tripwire is a wildfire mention in Ohio).

See `faura/midtier-scoring-fork/prompt_eval/README.md` § "Pick cases
that each stress one rule" for the worked external example.

## Adding a new code grader

1. Create `graders/code/<name>.py` exposing
   `grade(plan, case) -> CodeGradeResult`.
2. Append it to `DEFAULT_CODE_GRADERS` in `graders/code/__init__.py`.
3. Add a dataset case that exercises the grader's failure mode.

The aggregator (`grade_with_code`) runs every grader and averages
their scores. A code-grader hard fail (score=0) tanks the case's
combined score on its own — by design (a syntactically broken plan
must not be scored "good" by a model grader masking it).

## Adding a new model-grader axis

The judge returns all axes in ONE LLM call per case (matching
faura's pattern — cheap, low-variance, per-axis trend lines). To add
an axis:

1. Edit `graders/model/planner_judge.py::GRADER_SYSTEM_PROMPT` to add
   the new axis to the schema (`tone`, `instruction_following`,
   `completeness`, `safety`, `<new_axis>`).
2. Add the rubric paragraph explaining what the axis measures and a
   `because:` clause justifying its presence.
3. Add the axis to `_DEFAULT_AXES` so `_parse_axes` picks it out.
4. Update the example output in the prompt to include the new axis.
5. Re-freeze `prompts/grader_planner_judge_v1.txt` by running
   `prompts/_freeze.py`.
6. Re-run `test_prompt_hygiene.py` — the judge prompt itself is
   hygiene-tested.

## Running the suite

### Local — fast feedback

```bash
# Hygiene only (sub-second, no LLM cost)
pytest components/agents/tests/prompt_eval/test_prompt_hygiene.py -x -q

# Full eval — costs ~$0.10 in LLM tokens
PROMPT_EVAL_E2E=1 pytest components/agents/tests/prompt_eval/test_planner_quality.py -x

# Smaller sample for iteration
PROMPT_EVAL_E2E=1 PROMPT_EVAL_SAMPLES=3 pytest components/agents/tests/prompt_eval/test_planner_quality.py -x
```

### Management command — full reports

```bash
# Inside Docker:
docker exec compose-web-1 python manage.py run_planner_eval --dataset planner_v1

# Output: docs/eval-reports/planner-<timestamp>.html + .json
```

### Inspecting recent planner calls

```bash
docker exec compose-web-1 python manage.py inspect_recent_planner_calls --limit 5
```

Pretty-prints the last N `DeepRunLog` rows with system_prompt,
user_prompt, llm_response, model, tokens, latency, cost. The
developer's microscope — read the actual prompt that produced a wrong
answer before guessing what's broken.

## Iteration discipline

The single most important rule from the curriculum: **change one thing
at a time and watch the score move.**

1. Run the eval. Note the average score and the per-axis scores.
2. Make ONE targeted edit. Aim at the weakest axis.
3. Run the eval again. Compare.
4. Score up → keep the edit, freeze v2 under `prompts/<name>_v2.txt`.
5. Score down → revert. Try a different edit.
6. If per-axis scores diverge (e.g. `instruction_following` drops
   while `completeness` stays flat), the edit broke one axis —
   narrow the change.

Two simultaneous edits make the delta un-attributable. Ship them
separately.

## Where the rules came from

- `~/Documents/journals/2026_04_24.md` — Anthropic prompt curriculum
  (5-step workflow at lines 535–663).
- `~/Documents/journals/2026_05_05.md` — RAG, tools, and the
  3-grader taxonomy + `PromptEvaluator` class shape.
- `~/Documents/journals/2026_02_24.md` item 16 — the five Claude
  Opus 4.6 rules that generalise across modern frontier models.
- `~/.claude/plans/atomic-gathering-fox.md` — the 4-wave plan that
  organised the rollout. Waves 1–2 shipped; Waves 3–4 designed.
- `/Users/henrywanjala/faura/midtier-scoring-fork/prompt_eval/README.md`
  — the worked external example (Gemini real-estate-summary prompt,
  5 code graders + 4 model-grader axes, 8 hand-authored cases).

## What this suite does NOT do

- **Auto-generate datasets.** Curriculum-flagged as a Wave-5+ luxury.
  Hand-author or capture from `DeepRunLog`.
- **Block deploy on quality regression.** Per the locked decision —
  scores are informational. The hygiene layer (Layer 1) is the deploy
  guardrail.
- **Replay tool.** Wave 3 of the plan — `replay_conversation
  --conversation-id=<uuid> --prompt=planner.system@v2`. Not yet
  shipped.
- **Prompt registry.** Wave 3 — prompts are still module-level
  constants. The frozen `.txt` snapshots are the archival form until
  the registry lands.
- **Feedback bridge.** Wave 4 — `AgentResponseFeedback` thumbs-down
  rows are NOT auto-promoted into the dataset. Manual promotion only.
