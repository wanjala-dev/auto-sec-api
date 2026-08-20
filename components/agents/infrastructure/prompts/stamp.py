"""Resolve the prompt half of the configuration tuple (ADR 0032 D1).

THE UNIT OF MEASUREMENT IS ``(agent_type, prompt_version, model)``, not "the
model". When an agent regresses, four things could have changed — the model,
the system prompt, the tool set, the rubric — and attributing the regression to
"gpt-4o got worse" when the real cause was ``planner.system`` moving v11 → v12
is a credit-assignment failure, not a measurement.

We already version prompts (``PromptRegistry``, ``planner.system`` is at v12
with v1–v12 retained). What was missing is that **no run recorded which version
it used**: ``DeepRunLog`` carried ``model_used`` and the raw prompt TEXT, so two
runs on different prompt versions were distinguishable only by diffing blobs.
This module supplies the identity; ``DeepRunLog.prompt_id`` /
``DeepRunLog.prompt_version`` carry it.

Two conventions, one resolver:

* **Orchestration prompts** name themselves (``planner.system``).
* **Specialists** version their system-prompt addendum at
  ``<agent_slug>.system`` — the convention ``BaseAgent._registry_system_suffix``
  already implements. That id is computed HERE now, so the thing that renders
  the prompt and the thing that records which prompt was rendered cannot
  disagree about the id.

Everything degrades to ``""``. A prompt with no registry entry, a malformed
YAML, a registry that raises — none of it may warp a run. An unstamped row is
honest ("we don't know which version"); a crashed agent is not.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Suffix the specialist convention appends to an agent slug.
SPECIALIST_PROMPT_SUFFIX = ".system"


def specialist_prompt_id(agent_slug: str | None) -> str:
    """``"<slug>.system"`` for a specialist, or ``""`` when there is no slug."""
    slug = str(agent_slug or "").strip()
    return f"{slug}{SPECIALIST_PROMPT_SUFFIX}" if slug else ""


def is_registered(prompt_id: str) -> bool:
    """Is this prompt id known to the registry? Never raises."""
    if not prompt_id:
        return False
    try:
        from components.agents.infrastructure.prompts.registry import PromptRegistry

        return prompt_id in PromptRegistry.all_prompt_ids()
    except Exception:
        logger.warning("prompt registry lookup failed prompt_id=%s", prompt_id, exc_info=True)
        return False


def active_prompt_version(prompt_id: str) -> str:
    """The ``active`` version pointer for a prompt, or ``""``.

    ``""`` when the prompt is not registered OR the registry could not be read.
    Both mean the same thing for measurement — this run cannot be attributed to
    a prompt version — and neither is worth failing a run over.
    """
    if not is_registered(prompt_id):
        return ""
    try:
        from components.agents.infrastructure.prompts.registry import PromptRegistry

        return str(PromptRegistry.active_version(prompt_id) or "")
    except Exception:
        logger.warning("prompt version resolution failed prompt_id=%s", prompt_id, exc_info=True)
        return ""


def prompt_stamp(prompt_id: str) -> tuple[str, str]:
    """``(prompt_id, version)`` for the DeepRunLog columns, or ``("", "")``.

    The id is returned blank alongside a blank version on purpose: recording an
    id we could not resolve a version for would suggest the tuple is complete
    when it is not.
    """
    version = active_prompt_version(prompt_id)
    return (prompt_id, version) if version else ("", "")


def specialist_prompt_stamp(agent_slug: str | None) -> tuple[str, str]:
    """``(prompt_id, version)`` for a specialist agent's system addendum."""
    return prompt_stamp(specialist_prompt_id(agent_slug))
