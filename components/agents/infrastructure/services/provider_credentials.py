"""Can this deployment actually CALL a given model provider?

``AIModel.is_available`` is a platform-admin policy flag: "this model is part
of the catalogue we offer." Its docstring has always said *"only models that
the platform has API keys for should be marked is_available=True"* — but
nothing ever checked, so the flag was free to disagree with reality, and did:

- every one of the 13 seeded models sat ``is_available=False`` including
  ``gpt-4o-mini``, the model actually serving this deployment's runs, because
  ``seed_ai_models`` only sets the flag behind an opt-in ``--available``;
- and had that flag been passed, all 13 would have been marked available,
  including Anthropic, Azure and Ollama models for which this deployment holds
  no credential at all. The picker would have offered them and the run would
  have failed at call time — the user finding out, in production, that a
  choice the product presented was never possible.

So availability is now the AND of two independent facts:

    offered = is_available (policy: we choose to list it)
              AND has_credential(provider) (capability: we can call it)

The capability half is measured here, from the same environment variables the
LLM factories read at call time. Mirroring their source is the point: a
credential check that consults a different source of truth than the caller is
just a second thing to drift.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# Provider slug -> the env vars its factory reads. A tuple of tuples: the
# provider is usable when EVERY var in ANY ONE tuple is set. Azure needs both a
# key and an endpoint, so a key alone must not count.
_CREDENTIAL_REQUIREMENTS: dict[str, tuple[tuple[str, ...], ...]] = {
    "openai": (("OPENAI_API_KEY",),),
    "anthropic": (("ANTHROPIC_API_KEY",),),
    "azure": (("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_API_BASE"),),
    # Self-hosted: no API key, but it must be reachable somewhere. Absent a
    # configured host there is nothing to call.
    "ollama": (("OLLAMA_BASE_URL",), ("OLLAMA_HOST",)),
}


def _is_set(name: str) -> bool:
    value = os.environ.get(name)
    return bool(value and value.strip())


def has_credential(provider_slug: str) -> bool:
    """True when this deployment holds what it needs to call ``provider_slug``.

    An unknown provider returns False — fail closed. A provider we do not know
    how to authenticate is one we cannot promise, and silently treating it as
    usable is how the catalogue started lying in the first place.
    """
    requirements = _CREDENTIAL_REQUIREMENTS.get((provider_slug or "").lower())
    if not requirements:
        logger.warning(
            "ai_provider_credentials_unknown_provider slug=%s — treated as unusable",
            provider_slug,
        )
        return False
    return any(all(_is_set(var) for var in alternative) for alternative in requirements)


def credentialed_provider_slugs() -> set[str]:
    """Every provider slug this deployment can currently call."""
    return {slug for slug in _CREDENTIAL_REQUIREMENTS if has_credential(slug)}


def missing_requirement_summary(provider_slug: str) -> str:
    """Human-readable note on WHY a provider is unusable, for the API payload.

    Names the variable rather than the value — this string is rendered to
    workspace admins, and a credential must never reach a response body.
    """
    requirements = _CREDENTIAL_REQUIREMENTS.get((provider_slug or "").lower())
    if not requirements:
        return "No credential mapping is defined for this provider."
    alternatives = [" + ".join(alt) for alt in requirements]
    return "Not configured for this deployment — set " + " or ".join(alternatives) + "."


__all__ = [
    "credentialed_provider_slugs",
    "has_credential",
    "missing_requirement_summary",
]
