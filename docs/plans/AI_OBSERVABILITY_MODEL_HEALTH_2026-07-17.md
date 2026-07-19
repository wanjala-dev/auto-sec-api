# AI Observability / Model Health — dashboard + endpoint

Status: **PLAN / not started** · Owner: Henry · Created: 2026-07-17

## Context — why this exists

autosec puts AI agents in the middle of a security operation. No enterprise SOC will trust that
without being able to **see what the AI is doing and how good it is** — accuracy, whether operators
are up/down-voting it, cost, latency, error rate, and whether it's improving over time. "How do I
view this? How do I see what the AI is doing? How accurate is it?" is a *buying-gate* question, and
a strong demo beat ("here's the model's live quality").

The good news: this was already being designed on the Wanjala side (deep agents + Langfuse), so the
**raw signals came over** — we don't start from zero. What's missing is (a) **one aggregation
endpoint** that rolls the signals into a high-level "AI Health" view, and (b) a **dedicated HUD
panel** for it (a prompt-quality panel breadcrumb already exists).

## What we already have (breadcrumbs — verified in the fork)

| Signal | Where | Gives us |
|---|---|---|
| **Langfuse tracing** | `components/agents/.../tracing/langfuse.py` + `tracing_port.py`, `LANGFUSE_*` settings | per-run **latency, cost, tokens**, full trace tree |
| **Prompt-eval scores** | `infrastructure/evaluation/prompt_evaluator.py`, `/ai/prompt-eval/reports/`, `eval_example` store | **accuracy/quality** (avg score, per-case, trend vs previous run) |
| **Feedback votes** | `ai.conversations.models.AgentResponseFeedback` (thumbs up/down, unique per message+user) | operator **vote ratio** |
| **Run history + health** | `AgentExecutionViewSet` (`/ai/agents/executions/`), `HealthViewSet` (`/ai/health/`) | **run success/failure rate** |
| **Model in use** | `ai_config` endpoint (`llm_provider` + `model_name` per workspace) | which **model** each org runs |
| **Findings** | `AIFindingsViewSet` (`/ai/findings/`) | agent output surfaced as Kanban tasks |
| **HUD panel breadcrumb** | frontend `components/V2/HudPromptQualityPanel.jsx` — already reads `/ai/prompt-eval/reports/` (headline "X reports, avg Y/10", per-case scores, trend arrow) | the seed of the dashboard, already on the HUD |

(The dashboard's `/ai/prompt-eval/reports/` call currently returns **401** — it reaches the backend
via `REACT_APP_API_BASE_URL=http://localhost:8020`, it just needs an authenticated operator.)

## What to build

### 1. Aggregation endpoint — `GET /ai/model-health/`
A single read query (CQRS query + use case in `components/agents/application/queries/`) that rolls up,
per workspace (and optionally per agent / per model), over a window (default 7d):
- **Model**: provider + model_name in use.
- **Quality/accuracy**: latest prompt-eval avg score + trend (from the eval reports), pass rate.
- **Feedback**: 👍/👎 counts + ratio (from `AgentResponseFeedback`).
- **Reliability**: run success rate, error rate (from executions).
- **Cost/latency/tokens**: p50/p95 latency, total + per-run cost, token volume (from Langfuse via the
  tracing port — add a `fetch_metrics(window)` method to `TracingPort`, implemented by the Langfuse
  adapter; a Null adapter returns zeros so it degrades gracefully when Langfuse is off).
- **Per-agent breakdown**: same metrics grouped by agent type (which specialist is hot / weak).

Read-only, `IsAuthenticated`, workspace-scoped. Cache with a short TTL (metrics don't need to be
real-time). This is the "AI trust" contract the frontend + enterprise buyers consume.

### 2. HUD "AI Health" panel
Extend the existing `HudPromptQualityPanel` into a fuller **AI Health** panel (or a sibling panel)
that reads `/ai/model-health/`: headline model + quality score + trend, a votes gauge (👍/👎), latency
& cost sparklines, run success rate, and a per-agent mini-table. Keep V2 HUD styling
(HudPanel/HudText). It's a draggable panel like the others; also a candidate for a hex-ring node
("MODEL HEALTH").

### 3. Langfuse deep-link
From the panel, a "traces" action deep-links to the Langfuse UI (self-hosted, `LANGFUSE_BASE_URL`)
filtered to the workspace — for the operator/engineer who wants the full trace tree. No need to
rebuild Langfuse; embed/link it.

## The "agent scientist" loop (why this compounds)

The same signals feed continuous improvement: prompt-eval scores + feedback votes tell us which
prompts/agents are weak → tune the system prompt → re-run the eval harness (`eval_example` store) →
score → ship the better prompt. The AI Health panel is the *read* side; the prompt-eval harness is
the *write* side. For the POC we want **one agent (triage) with one strong, eval-validated prompt**,
and the panel showing its score climbing.

## Auth reality (shared with all data-backed panels)

The observability endpoints require a JWT. The autosec frontend currently renders the HUD without a
login. Before any panel shows real data we need an authenticated operator — either wire the V2 login
(`V2AuthShell` is in the closure) so the operator logs in → token → panels populate, or seed a demo
operator + token for the demo. Track this as a shared dependency (it also unblocks the integrations
alert feed).

## Phasing

- **Slice 1:** `GET /ai/model-health/` aggregation (eval score + feedback ratio + run success; Langfuse
  metrics optional/null-safe) + light up the **existing** `HudPromptQualityPanel` against it.
- **Slice 2:** add Langfuse latency/cost/tokens via `TracingPort.fetch_metrics`; build the full **AI
  Health** panel (votes gauge, sparklines, per-agent table).
- **Slice 3:** Langfuse deep-link + quality-drop alerting (fire a finding/notification when avg score
  or success rate drops below a threshold — dogfoods our own alerting).

## Open questions

- Window + caching TTL defaults (7d / 60s?).
- Does Langfuse expose the metrics we want via its query API at the version we run, or do we compute
  latency/cost from our own execution records? (Prefer our own records as the source of truth; use
  Langfuse for the trace deep-dive.)
- Per-model vs per-agent vs per-workspace as the primary grouping in the headline.

## References

- Internal: `components/agents/.../tracing/langfuse.py` + `tracing_port.py`, `prompt_evaluator.py`,
  `AgentResponseFeedback`, `AgentExecutionViewSet`, `HudPromptQualityPanel.jsx`,
  `INTEGRATIONS_AWS_POC_2026-07-17.md` (shares the auth dependency + the alert feed).
- External: 2026 agentic-SOC guidance stresses observability/oversight as the human's role — the AI
  Health view is how humans stay in the loop.
```
