"""Framework-free extraction of code-like identifiers from evidence text.

Single source of truth for the "salient token" heuristic used by grounded
verification: CamelCase identifiers (``ImportError``, ``AiEmbeddingsProvider``),
dotted paths (``components.knowledge.x``), and longer snake_case names
(``refresh_recommendable_items``) are the checkable anchors a log error's
evidence offers. Both the agents-context grounded verifier
(``finding_verifier``) and the integrations-context patch advisor
(``log_patch_advisor_service``) ground their outputs against these tokens —
the heuristic lives HERE (shared kernel) so neither context imports the
other's infrastructure.
"""

from __future__ import annotations

import re

# Generic filler that carries no grounding on its own.
BOILERPLATE_TOKENS = frozenset(
    {
        "investigate",
        "further",
        "check",
        "logs",
        "monitor",
        "monitoring",
        "system",
        "ensure",
        "proper",
        "review",
        "additional",
        "metrics",
        "inconsistencies",
        "errors",
        "error",
        "issue",
        "issues",
        "problem",
        "resources",
        "necessary",
        "perform",
        "operation",
        "data",
        "being",
        "cause",
        "may",
        "the",
        "and",
        "for",
        "that",
        "this",
        "with",
        "from",
        "which",
        "have",
        "will",
        "should",
    }
)

# CamelCase identifiers (ImportError, AiEmbeddingsProvider), dotted paths
# (components.knowledge.x), and longer snake_case (refresh_recommendable_items).
CAMEL_RE = re.compile(r"\b[A-Z][a-z]+(?:[A-Z][a-z0-9]+)+\b")
DOTTED_RE = re.compile(r"\b[a-zA-Z_]\w*(?:\.\w+){2,}\b")
SNAKE_RE = re.compile(r"\b[a-z]+_[a-z_]{3,}\b")


def salient_tokens(text: str) -> set[str]:
    """Code-like identifiers from a finding's ground truth (message/evidence)."""
    tokens: set[str] = set()
    for rx in (CAMEL_RE, DOTTED_RE, SNAKE_RE):
        tokens.update(rx.findall(text or ""))
    # Drop pure-filler snake tokens (e.g. "log_level" isn't an identity anchor).
    return {t for t in tokens if t.lower() not in BOILERPLATE_TOKENS}
