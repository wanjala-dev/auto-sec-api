"""Domain constants for the tag vocabulary (ADR 0015 D3/D4).

Limits are app-enforced (behind the port), not DB constraints — all writes flow
through the use cases/repository, and a limit is cheap to raise later.
"""

from __future__ import annotations

# Tag kinds. ``system`` tags are platform-writable only (the K8s reserved-prefix
# rule, ADR 0015 R6): user CRUD and the tag/untag endpoint reject
# create/rename/delete/apply-by-name of system tags.
KIND_USER = "user"
KIND_SYSTEM = "system"
VALID_KINDS: frozenset[str] = frozenset({KIND_USER, KIND_SYSTEM})

# Recognised namespaces (default HUD colours + later automation/routing — D4).
# Operators MAY create tags in these (asserting ``owner:payments`` is the point)…
RESERVED_NAMESPACES: tuple[str, ...] = ("owner", "team", "env", "service", "compliance", "risk")
# …except ``risk:``, which is held back for the platform from day one (D4/D9)
# so no user data squats on it.
SYSTEM_ONLY_NAMESPACES: tuple[str, ...] = ("risk",)

# Length limits (ADR 0015 D3 — grounded in R4/R5/R6/R8/R14).
MAX_NAME_LENGTH = 64
MAX_SLUG_LENGTH = 100
MAX_NAMESPACE_LENGTH = 32
MAX_VALUE_LENGTH = 64

# Count limits (ADR 0015 D3 — AWS's 50 tags/resource analogue; sprawl guard).
MAX_TAGS_PER_FINDING = 50
MAX_LIVE_TAGS_PER_WORKSPACE = 1000


def is_system_only_namespace(namespace: str) -> bool:
    """True when the namespace is platform-only (users may not create/apply in it)."""
    return namespace in SYSTEM_ONLY_NAMESPACES


def is_reserved_namespace(namespace: str) -> bool:
    """True when the namespace is on the recognised/reserved list (D4)."""
    return namespace in RESERVED_NAMESPACES
