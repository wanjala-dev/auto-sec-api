# RAG Eval Harness

RAGAS-style evaluation of the agentic RAG pipeline. Measures whether retrieval/reranking/synthesis changes actually improve answer quality, instead of letting every change ride on vibes.

This is the **#13 — Eval harness for retrieval quality** item from `docs/plans/RAG_AUDIT_AND_ROADMAP.md`. It was parked until Tier 2 landed (the index needed real data first); Tier 2 is shipped, so this is now actionable.

## What it measures

Four RAGAS-style metrics, computed per eval prompt and aggregated across the run:

| Metric | What it answers | How it's scored |
|---|---|---|
| **Faithfulness** | Is every claim in the answer supported by the retrieved context? | LLM extracts claims from answer, judges each one against retrieved chunks. Score = supported_claims / total_claims. |
| **Answer Relevancy** | Does the answer address the question? | LLM-as-judge scores 1-5 on how directly the answer addresses the question. Score = (rating - 1) / 4. |
| **Context Precision** | Of the chunks retrieved, what fraction are actually relevant? | LLM judges each chunk's relevance to the question against the ground-truth `expected_sections`. Score = relevant_chunks / retrieved_chunks. |
| **Context Recall** | Of the chunks that SHOULD have been retrieved, what fraction were? | Compares retrieved chunk `metadata.section` against `expected_sections` from the eval set. Score = matched_sections / expected_sections. |

All four scores are floats in [0, 1]. A perfect RAG run is 1.0 across the board. Today's baseline is what we're measuring this PR.

## Why we built it in-house

RAGAS the library exists. We did not use it because:
- It pins to a single LLM provider (OpenAI default); our stack uses the `AILlmProvider` port abstraction (Rule 5.4 of `.claude/rules/architecture-manifesto.md`).
- It pulls in `transformers` + `datasets` as transitive deps — significant install weight for a research tool.
- Reading its metric implementations is the only way to understand them anyway; reimplementing the formulas takes ~50 lines per metric.

Our metrics follow the RAGAS formulas from [Es et al., 2023](https://arxiv.org/abs/2309.15217). Cited in each metric module.

## Two-phase architecture

The harness is split into **collect** and **score** so you can:
- Re-score the same run with different judge prompts (cheap — judge LLM calls are cached).
- A/B two runs from before and after a code change.
- Inspect what the pipeline actually retrieved without re-running it.

```
collect:  eval_set.yaml + live RAG pipeline  →  reports/run-<ts>.json
score:    reports/run-<ts>.json + judge LLM  →  reports/scored-<ts>.json + scored-<ts>.html
```

## Runbook

### Prerequisites

```bash
# Local stack up (so prefetch + chat path can hit the live system)
make up

# Zaylan demo workspace seeded
docker exec compose-web-1 python manage.py create_workspace --config /app/infrastructure/persistence/management_commands/management/commands/workspace_configs/zaylan/config.json
docker exec compose-web-1 python manage.py seed_marketing_demo --workspace-uuid <zaylan-uuid> --i-am-sure

# Env vars for the judge LLM (default: same provider the chat uses)
cp tests/eval/rag/env.eval.sample tests/eval/rag/.env.eval
# Edit .env.eval with your judge model + workspace UUID
```

### Run

```bash
# Run end-to-end (collect + score) against local Zaylan
make eval-rag

# Run against the deployed demo (CAUTION: real LLM cost)
make eval-rag-demo

# Just collect (cheap — no judge LLM calls)
make eval-rag-collect

# Score an existing collected run
make eval-rag-score RUN_FILE=tests/eval/rag/reports/run-20260610-103000.json
```

Reports land in `tests/eval/rag/reports/` (gitignored). Open the HTML in a browser for side-by-side comparison; the JSON is the canonical artifact for diffing.

### Costs

- **Collect** runs each prompt through the full chat pipeline → ~30 chat calls = ~$0.15 with current model defaults.
- **Score** runs ~4 judge calls per prompt → ~120 judge calls = ~$0.30 per eval.
- **Total per eval run**: ~$0.45. Cached judge calls (per `(prompt_id, answer_hash)`) make re-scoring near-free.

### What this is NOT

- **Not a CI gate.** This runs on-demand; the cost + the LLM nondeterminism make it unsuitable for blocking PRs. Run it on RAG changes.
- **Not a retrieval-only eval.** It exercises the full chat path so retrieval + planner routing + synthesis all contribute to the scores. If you want pure retrieval, swap the runner to call `_prefetch_retrieved_context` directly.
- **Not a unit test.** Metric correctness is asserted via unit tests in `components/knowledge/tests/unit/test_eval_metrics.py`; this harness exercises end-to-end behavior of the deployed system.

## Failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| `Workspace not found` during collect | Zaylan not seeded on the target stack | Run `create_workspace --config zaylan/config.json` per the prerequisites |
| `Context Recall` is 0 for every entry | Reindex didn't fire; embedding index has no `members` chunk for Zaylan | `docker exec compose-web-1 python manage.py shell -c "from infrastructure.persistence.workspaces.models import Workspace; ws=Workspace.objects.get(workspace_name='Zaylan'); ws.save()"` then wait 30s |
| Judge LLM returns garbage | Judge model is too small / wrong temperature | Edit `.env.eval` — judge defaults to `gpt-4o-mini` with temperature 0; weaker models hallucinate ratings |
| Scores wildly different run-to-run | Judge LLM nondeterminism (temperature > 0) | Pin temperature 0 in `.env.eval` and clear `reports/.judge_cache.json` |

## Directory layout

```
tests/eval/
    __init__.py
    rag/
        __init__.py
        README.md              # this file
        config.py              # pydantic-settings (target, judge model, paths)
        eval_set.yaml          # 30 hand-authored prompts with ground truth
        judge_prompts.yaml     # LLM-as-judge prompts (versioned)
        runner.py              # collect: run eval_set through the live pipeline
        scorer.py              # score: judge a collected run against ground truth
        report.py              # JSON + HTML output
        metrics/
            __init__.py
            faithfulness.py
            answer_relevancy.py
            context_precision.py
            context_recall.py
        reports/               # gitignored — JSON + HTML output
        .env.eval.sample       # checked-in template for env vars
        .gitignore             # reports/
```

## References

- [Es, S., et al. (2023). *RAGAS: Automated Evaluation of Retrieval Augmented Generation*](https://arxiv.org/abs/2309.15217) — Faithfulness, Answer Relevancy, Context Precision/Recall formulas.
- [Anthropic Cookbook — LLM-as-judge patterns](https://github.com/anthropics/anthropic-cookbook) — judge prompt structure for the four metrics.
- `docs/plans/RAG_AUDIT_AND_ROADMAP.md` — broader RAG roadmap; this is #13.
- `.claude/rules/load-testing.md` — directory placement convention (top-level `tests/`, mirrors `tests/load/`).
