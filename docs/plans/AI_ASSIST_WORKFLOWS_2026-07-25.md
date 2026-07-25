# AI Assist for Workflows — design + Slice 1 scope

**Status:** proposed · **Date:** 2026-07-25
**Goal:** bring the AI-assist experience we already have for writing/templates to the
**workflow builder** — so a non-expert on-call analyst can build a real SOC playbook in
plain English, grounded in their actual findings, in minutes instead of hours.
**Audience:** design partners / on-call SOC users. Ties the deep-agent arm *into* the
product surface (we dogfood our own agents).

Grounded in market + SOAR research (citations in §7) and the code that already exists
(`components/workflow`, `components/agents`, `components/content` AI-draft pattern).

---

## 1. First principles

1. **AI proposes, human disposes (Level-1 AI-assist).** The industry-safe posture for
   AI in security automation is analyst-in-the-loop: the AI *suggests* a workflow; the
   human reviews, edits on the canvas, and publishes. Nothing the AI emits ever
   auto-fires. This is also the writing-assist contract we already ship.
2. **Every AI output is validated before it touches the canvas.** The backend already
   owns the publish gate — `components/workflow/domain/validators.py::validate_graph`
   (exactly-one-start, ≥1 end, branch nodes need ≥2 *labelled* edges, message nodes need
   channel+body, etc.). The author agent runs its draft through `validate_graph` and
   **self-corrects on errors** before returning. So the AI *cannot* hand back an
   unpublishable graph.
3. **Reuse, don't reinvent.** This is the writing `draft-with-ai` pattern
   (`components/content/api/ai_draft_controller.py::WritingDraftAskAiView`) pointed at a
   new output shape (a workflow graph), driven by the existing agents framework
   (`components/agents`), and rendered onto the React Flow + ELK builder we just shipped
   (frontend PR #30/#32). Little new surface area.
4. **Our moat is grounding.** Zapier/Make can only generate generic app-to-app
   automations. We can ground generation in *real security context* — findings on the
   SOC board, detectors, log sources, severities — via the agents + pgvector RAG. That's
   the differentiator; lean into it.

---

## 2. The feature (four slices, this doc scopes Slice 1)

| Slice | Name | What | Mirrors |
|------|------|------|---------|
| **1** | **Generate-from-prompt** | Prompt box in the builder → author agent returns a validated `{nodes, edges}` graph → preview → **Accept** loads it onto the canvas. | Zapier Copilot / Make "Maia" |
| 2 | Assist-a-node | Inspector "AI" button drafts a message body / AI-agent prompt / condition predicate for the selected node. | writing `draft-with-ai` per-field |
| 3 | Suggest-from-findings | Proactive + grounded: analyze recent findings/detectors and propose a playbook ("18 criticals, no triage automation — generate one?"). | our differentiator |
| 4 | Fix-and-explain | Pre-publish, AI explains validator failures in plain English and offers to fix ("this condition has an unlabelled branch"). | ties to the known validation-gap |

Slices 2–4 are follow-ups; **Slice 1 is the spike that proves the pipeline end-to-end.**

---

## 3. Slice 1 — Generate-from-prompt

### 3.1 User story
> As an on-call analyst, I open the workflow builder, type *"When a critical finding
> lands, alert the SOC in-app, run the AI triage agent, and if it's a brute-force
> forward it to our SOAR webhook,"* click **Generate**, and a valid, labelled DAG
> appears on the canvas that I can tweak and Publish.

### 3.2 Backend — one new use case + one endpoint

**New:** `components/workflow/application/use_cases/draft_workflow_graph_use_case.py`
- Input: `{ workspace_id, prompt, current_graph? }` (current_graph lets "add a step that…"
  edits work later; Slice 1 can ignore it).
- Calls the **agents** LLM path (reuse `components/agents/application/providers/ai_provider.py`
  / the `knowledge` LLM provider `ai_llm_provider.py`) with a **structured-output**
  instruction: emit `{ "nodes": [...], "edges": [...] }` using ONLY the tones in
  `components/workflow/domain/constants.py::NODE_TYPES` and the security triggers in
  `SOURCE_TYPES` (`finding_*`).
- **Validate-and-repair loop:** run `validate_graph(draft)`; if it returns errors, feed
  them back to the model (up to N=2 retries) and re-emit. Return the first graph that
  passes, plus the residual validator report (so the UI can warn if still imperfect).
- System prompt carries the **node/trigger catalog + the publish rules** (message needs
  channel+body; branch nodes need ≥2 labelled edges; one start, ≥1 end) so the model
  targets a publishable shape from the start.

**New endpoint:** `POST /workspaces/workflows/workflows/draft-with-ai/`
(add an `@action(detail=False, methods=["post"], url_path="draft-with-ai")` on
`WorkflowViewSet` in `components/workflow/api/controller.py`, next to the existing
`validate` action). Body `{ prompt }`; `resolve_workspace_id` scopes it (same as the rest
of the controller). Returns `{ graph, valid, errors, name?, goal? }`.

- **Gating:** Pro feature + the workflows feature flag, exactly like writing's AI draft
  (`RequiresFeatureFlag` + the entitlement check already used in the controller).
- **Async?** Slice 1 can be synchronous (one LLM call, a few seconds) behind a normal
  request; if p95 creeps past ~3s, move to the Celery + poll pattern the writing agent
  uses. Log at INFO with `workspace_id` + `run_id` (per `logging.md`).
- **Provenance:** reuse the agent-run provenance the writing draft records, so a
  generated workflow carries "drafted by AI from prompt: …" for the audit trail.

### 3.3 Frontend — an assist box in the builder

- Reuse the assist-thread UX from writing. Minimal Slice 1: a collapsible **"AI Assist"**
  strip in `HudWorkflowBuilder` header (chamfered, HUD-styled) with a prompt textarea +
  **Generate** button.
- New service methods: `workflowService.draftWorkflowWithAi({ workspace, prompt })` →
  `workflowApi` POST to the new endpoint.
- On success: show a short summary + **Accept** / **Discard**. **Accept** →
  `loadWorkflowIntoBuilder({ graph, name, goal })` (the exact hook the template path
  already uses) → ELK re-lays-out → user edits/publishes. If `valid === false`, render the
  validator warnings inline (a preview of Slice 4).
- Empty-canvas affordance: add an **"✨ Generate with AI"** option alongside "Blank
  canvas" in the template picker, so generation is discoverable at create time.

### 3.4 Data contract

```jsonc
// POST /workspaces/workflows/workflows/draft-with-ai/  { "prompt": "..." }
// 200:
{
  "graph": {
    "nodes": [
      {"id":"start","type":"start","label":"Critical finding raised","config":{"triggerType":"finding_critical"}},
      {"id":"notify","type":"message","label":"Alert the SOC","config":{"channel":"in_app","body":"..."}},
      {"id":"triage","type":"ai","label":"AI triage","config":{"prompt":"..."}},
      {"id":"severe","type":"condition","label":"Brute force?","config":{"predicate":{...}}},
      {"id":"soar","type":"webhook","label":"Forward to SOAR","config":{"url":"","method":"POST"}},
      {"id":"end","type":"end","label":"End","config":{}}
    ],
    "edges": [ /* labelled; branch edges carry yes/no */ ]
  },
  "valid": true,
  "errors": [],
  "name": "Critical finding → triage → SOAR",
  "goal": "security"
}
```

The `graph` shape is exactly what `loadWorkflowIntoBuilder` + `validate_graph` already
consume — no new mapping.

---

## 4. Why this is mostly reuse (surface-area budget)

| Need | Already exists | New |
|---|---|---|
| LLM call + provider | `components/agents` + `knowledge/ai_llm_provider` | prompt + structured-output schema |
| Graph validation | `validators.py::validate_graph` (+ `/validate` endpoint) | validate-and-repair loop |
| Draft-with-AI request/gating/provenance | `content/api/ai_draft_controller.py` | port to workflows |
| Load graph → canvas | `loadWorkflowIntoBuilder` (template path) | reuse verbatim |
| Builder canvas (React Flow + ELK, HUD) | frontend PR #30/#32 | an assist prompt strip |

Net-new: **one use case, one endpoint, one service method, one small UI strip.**

---

## 5. Risks & guardrails

- **Hallucinated node types / triggers** → constrained decoding to `NODE_TYPES` /
  `SOURCE_TYPES` + the validate-and-repair loop; reject and retry on unknown types.
- **Unpublishable graphs** → the repair loop targets `validate_graph`; worst case we
  return `valid:false` + errors and still let the analyst fix on the canvas (never a
  silent bad publish).
- **Cost / latency** → one call (plus ≤2 repair retries) per Generate; Pro-gated; move to
  async if p95 slips. No auto-generation on load.
- **Trust** → human-in-the-loop, provenance stamped, nothing auto-fires. Matches the
  Level-1 posture the market recommends (§7).

---

## 6. Acceptance criteria (Slice 1)

1. `POST …/draft-with-ai/` returns a `validate_graph`-passing graph for the 3 seeded
   security scenarios (critical-alert, high-triage, finding→SOAR) from a one-line prompt.
2. Builder: prompt → Generate → Accept renders the DAG on the canvas; Publish succeeds
   with no manual edits for at least the simple linear cases.
3. Pro + feature-flag gated; provenance recorded; 0 console errors; architecture tests
   green (controller stays thin, use case owns orchestration, no SDK import in the view).

---

## 7. Research citations

- Zapier Copilot / Make "Maia" — NL→automation is table stakes:
  https://medium.com/@automation.labs/zapier-vs-make-vs-n8n-in-2026-where-ai-agents-actually-fit-1edbbeff85f3 ,
  https://blog.n8n.io/best-ai-workflow-automation-tools/
- SOAR → agentic AI playbooks (generate/adapt IR workflows from alerts; Level-1
  AI-assist posture):
  https://underdefense.com/blog/incident-response-automation-2/ ,
  https://swimlane.com/blog/soar-playbooks/
- Microsoft Security Copilot + Sentinel — AI-automated triage / promptbooks:
  https://jeffreyappel.nl/automated-incident-triage-with-security-copilot-and-microsoft-sentinel-defender-xdr/

---

## 8. Out of scope (this doc)

Slices 2–4 (per-node assist, suggest-from-findings, fix-and-explain), streaming token UI,
multi-turn "edit my workflow" conversation, and RAG grounding on the workspace's finding
history — all natural follow-ons once Slice 1 proves the generate→validate→load pipeline.
