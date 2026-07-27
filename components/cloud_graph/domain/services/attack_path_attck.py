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


# Each traversed edge relation → the ATT&CK technique that hop represents. Structural
# relations (attached_to, in_subnet) carry no technique and are skipped in the flow.
_RELATION_TECHNIQUES: dict[str, str] = {
    "allows_ingress_from": _ENTRY,  # public inbound rule → Exploit Public-Facing App
    "routes_to_igw": _ENTRY,  # internet-routable path → exposure
    "can_assume": "T1078.004",  # assume a role via valid cloud creds → Priv-Esc
    "has_policy": "T1098.003",  # role carries additional/powerful cloud roles → Priv-Esc
    "reads_bucket": "T1530",  # read from cloud storage → Collection
}


def technique_for_relation(relation: str) -> MitreTechnique | None:
    """The ATT&CK technique a single traversed edge represents (or None if structural)."""
    tid = _RELATION_TECHNIQUES.get(relation)
    return technique(tid) if tid else None


def build_attack_flow(entry_label: str, legs) -> list[dict]:
    """The hop-by-hop ATT&CK attack-flow for a path — the render the HUD draws.

    Starts at the public entry (Initial Access), then one step per traversed leg that
    maps to a technique. ``legs`` is an iterable of objects with ``.relation`` +
    ``.dst_label``. Each step is a flat dict (technique fields + hop label/relation).
    """
    flow = [{"label": entry_label, "relation": None, **technique(_ENTRY).to_dict()}]
    for leg in legs:
        tech = technique_for_relation(leg.relation)
        if tech is not None:
            flow.append({"label": leg.dst_label, "relation": leg.relation, **tech.to_dict()})
    return flow
