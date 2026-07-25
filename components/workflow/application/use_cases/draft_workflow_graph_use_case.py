"""Draft a workflow graph from a natural-language prompt (AI Assist — Slice 1).

Turns *"when a critical finding lands, alert the SOC and run AI triage"* into a
``{nodes, edges}`` graph the builder can load and publish. The model is
constrained to the real node/trigger catalog, and every draft is run through the
domain ``validate_graph`` publish gate — on failure the validator errors are fed
back to the model (bounded retries) so it self-corrects. The result therefore
never leaves this use case in an unpublishable shape without the caller being
told (``valid`` + ``errors``).

Human-in-the-loop by contract: this only DRAFTS. Nothing is persisted or fired;
the analyst reviews, edits on the canvas, and publishes.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from components.workflow.application.ports.workflow_draft_port import WorkflowDraftPort
from components.workflow.domain.constants import NODE_TYPES, TRIGGER_CATALOG
from components.workflow.domain.validators import validate_graph

logger = logging.getLogger(__name__)

_MAX_REPAIR_ATTEMPTS = 3

# The security-relevant node vocabulary we actively steer the model toward. The
# full NODE_TYPES tuple is still allowed (and listed) — this is guidance, not a
# hard filter — so the model prefers the autonomous SOC shapes.
_PREFERRED = ("start", "end", "message", "ai", "condition", "webhook", "wait", "task", "assign")


def _catalog_text() -> str:
    node_line = ", ".join(NODE_TYPES)
    triggers = "\n".join(f"  - {t.id} (source: {t.source_type}) — {t.label}" for t in TRIGGER_CATALOG)
    return (
        f"NODE TYPES (use the `type` field): {node_line}\n"
        f"Prefer these for SOC playbooks: {', '.join(_PREFERRED)}\n\n"
        f"START TRIGGERS (set start node config.triggerType to one of these):\n{triggers}\n"
    )


_SYSTEM_PROMPT = f"""You are a SOC automation architect for Auto-Sec. Convert the user's request into a \
security workflow graph. Respond with STRICT JSON only — no prose, no markdown fences.

Shape:
{{
  "name": "<short workflow name>",
  "goal": "security",
  "graph": {{
    "nodes": [{{"id": "start", "type": "start", "label": "...", "config": {{"triggerType": "finding_critical"}}}}],
    "edges": [{{"id": "e1", "from": "start", "to": "notify", "label": null}}]
  }}
}}

{_catalog_text()}

HARD RULES (the graph is rejected otherwise):
- Exactly ONE `start` node and at least ONE `end` node. Every path flows start -> ... -> end.
- The start node's config.triggerType MUST be one of the START TRIGGERS above (use finding_critical / \
finding_high / finding_raised for security goals).
- `message` nodes need config.channel ("in_app" | "email" | "slack") AND config.body (real copy).
- `ai` nodes need config.prompt (the instruction for the AI agent).
- `webhook` nodes need config.url (may be "") AND config.method ("POST" | "GET").
- `wait` nodes need config.delay_seconds (integer seconds).
- `condition` nodes need config.predicate like \
{{"match": "any", "conditions": [{{"field": "severity", "op": "eq", "value": "high"}}]}} AND EXACTLY TWO \
outgoing edges, one labelled "yes" and one labelled "no".
- CONNECT EVERY NODE: every non-end node has at least one outgoing edge; every non-start node has at \
least one incoming edge. List an edge for every connection — a node with no edge is a bug.
- Every node id is unique; every edge id is unique; edge from/to reference existing node ids.
- Keep it minimal and publishable. Use clear labels.

WORKED EXAMPLE (a valid severity-branch playbook — note the condition's two labelled edges and that \
every node is connected):
{{
  "name": "Finding -> SOAR on high/critical",
  "goal": "security",
  "graph": {{
    "nodes": [
      {{"id": "start", "type": "start", "label": "Finding raised", "config": {{"triggerType": "finding_raised"}}}},
      {{"id": "sev", "type": "condition", "label": "High or critical?", "config": {{"predicate": {{"match": "any", "conditions": [{{"field": "severity", "op": "eq", "value": "high"}}, {{"field": "severity", "op": "eq", "value": "critical"}}]}}}}}},
      {{"id": "soar", "type": "webhook", "label": "Forward to SOAR", "config": {{"url": "", "method": "POST"}}}},
      {{"id": "log", "type": "message", "label": "Log it", "config": {{"channel": "in_app", "body": "A lower-severity finding was logged."}}}},
      {{"id": "end", "type": "end", "label": "End", "config": {{}}}}
    ],
    "edges": [
      {{"id": "e1", "from": "start", "to": "sev", "label": null}},
      {{"id": "e2", "from": "sev", "to": "soar", "label": "yes"}},
      {{"id": "e3", "from": "sev", "to": "log", "label": "no"}},
      {{"id": "e4", "from": "soar", "to": "end", "label": null}},
      {{"id": "e5", "from": "log", "to": "end", "label": null}}
    ]
  }}
}}"""


class DraftWorkflowGraphUseCase:
    def __init__(self, draft_port: WorkflowDraftPort):
        self._draft = draft_port

    def is_available(self) -> bool:
        return self._draft.is_configured()

    def execute(self, *, prompt: str, workspace_id: str) -> dict[str, Any]:
        prompt = (prompt or "").strip()
        if not prompt:
            return {
                "graph": None,
                "valid": False,
                "errors": [{"code": "empty_prompt", "message": "Prompt is required."}],
            }

        messages: list[dict[str, str]] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        last: dict[str, Any] = {"graph": None, "valid": False, "errors": [], "name": "", "goal": "security"}

        for attempt in range(_MAX_REPAIR_ATTEMPTS + 1):
            try:
                raw = self._draft.complete(messages)
            except Exception:
                logger.exception("workflow_draft.completion_failed workspace_id=%s attempt=%s", workspace_id, attempt)
                return {
                    "graph": None,
                    "valid": False,
                    "errors": [{"code": "llm_error", "message": "The AI assistant could not be reached."}],
                }

            parsed = _parse_payload(raw)
            if parsed is None:
                messages.append({"role": "assistant", "content": raw})
                messages.append(
                    {
                        "role": "user",
                        "content": "That was not valid JSON. Reply with STRICT JSON only, matching the shape.",
                    }
                )
                continue

            graph = parsed.get("graph") or {}
            errors = validate_graph(graph)
            last = {
                "graph": graph,
                "valid": not errors,
                "errors": errors,
                "name": str(parsed.get("name") or "").strip(),
                "goal": parsed.get("goal") if parsed.get("goal") in ("security", "general") else "security",
            }
            logger.info(
                "workflow_draft.attempt workspace_id=%s attempt=%s valid=%s error_count=%s",
                workspace_id,
                attempt,
                last["valid"],
                len(errors),
            )
            if not errors:
                return last

            # Repair: hand the validator's own errors back to the model.
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "The graph failed validation with these errors — fix them and reply with STRICT JSON only:\n"
                        + json.dumps(errors, indent=2)
                    ),
                }
            )

        # Bounded retries exhausted: return the best (still-invalid) attempt so
        # the analyst can finish it on the canvas — never a silent bad publish.
        return last


_FENCE_RE = re.compile(r"^```(?:json)?|```$", re.MULTILINE)


def _parse_payload(raw: str) -> dict[str, Any] | None:
    """Best-effort extraction of the JSON object from the model text."""
    if not raw:
        return None
    text = _FENCE_RE.sub("", raw).strip()
    # Narrow to the outermost object if the model wrapped it in prose.
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        obj = json.loads(text[start : end + 1])
    except (ValueError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None
