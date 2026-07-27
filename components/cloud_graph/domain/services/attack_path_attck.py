"""Deterministic ATT&CK mapping for attack-path categories.

Maps cloud_graph's OWN toxic-combination taxonomy (``AttackPathCategory``) onto the
shared ATT&CK vocabulary — pillar-local semantics over shared words, so shared_kernel
never imports cloud_graph. Deterministic: the category already encodes the kill-chain
(a public entry is Initial Access; reaching an admin role is Privilege Escalation;
reaching a data store is Collection), so the technique set is a lookup, not a guess.
"""

from __future__ import annotations

from components.cloud_graph.domain.value_objects.attack_path import AttackPathCategory
from components.shared_kernel.domain.mitre import MitreTechnique, order_flow, technique

# Every path starts at a public-facing entry → Initial Access.
_ENTRY = "T1190"

_CATEGORY_TECHNIQUES: dict[AttackPathCategory, tuple[str, ...]] = {
    # Public compute that can assume a powerful role: exploit the public entry, then
    # use the valid cloud creds / additional cloud roles to escalate.
    AttackPathCategory.PUBLIC_COMPUTE_ADMIN: (_ENTRY, "T1078.004", "T1098.003"),
    # Public compute that reaches a sensitive data store: exploit the entry, then
    # collect data from cloud storage.
    AttackPathCategory.PUBLIC_DATA_EXPOSURE: (_ENTRY, "T1530"),
}


def techniques_for_category(category: AttackPathCategory) -> tuple[MitreTechnique, ...]:
    """The ATT&CK techniques for a path category, in kill-chain order."""
    ids = _CATEGORY_TECHNIQUES.get(category, (_ENTRY,))
    return order_flow(tuple(technique(tid) for tid in ids))
