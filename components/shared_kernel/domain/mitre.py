"""MITRE ATT&CK vocabulary — the shared, cross-pillar technique catalogue.

ATT&CK is a *framework mapping* (like CIS/PCI), so a finding's techniques ride in
the existing ``compliance`` bag as ``{"MITRE ATT&CK": ["T1190", ...]}`` — no new
finding contract, no migration. This module owns only the vocabulary: the tactics
(kill-chain phases, ordered) and a curated registry of the techniques autosec maps
to. Each pillar maps ITS own taxonomy (attack-path category, detector kind) onto
these — the innermost ring owns the words, the pillars own the semantics, so
shared_kernel never depends on a pillar.

Deterministic by construction: we only ever tag a technique from a fact we already
know (a public entry ⇒ T1190). An LLM may *explain* a technique, never *assign* one
— a hallucinated T-code is worse than none.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MitreTactic(str, Enum):
    """The ATT&CK tactics autosec surfaces, with a kill-chain ``order`` for sorting a
    path's techniques into an attack-flow (Initial Access → … → Impact)."""

    INITIAL_ACCESS = "initial_access"
    EXECUTION = "execution"
    PERSISTENCE = "persistence"
    PRIVILEGE_ESCALATION = "privilege_escalation"
    DEFENSE_EVASION = "defense_evasion"
    CREDENTIAL_ACCESS = "credential_access"
    DISCOVERY = "discovery"
    LATERAL_MOVEMENT = "lateral_movement"
    COLLECTION = "collection"
    EXFILTRATION = "exfiltration"
    IMPACT = "impact"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()

    @property
    def order(self) -> int:
        return _TACTIC_ORDER[self]


_TACTIC_ORDER: dict[MitreTactic, int] = {
    MitreTactic.INITIAL_ACCESS: 1,
    MitreTactic.EXECUTION: 2,
    MitreTactic.PERSISTENCE: 3,
    MitreTactic.PRIVILEGE_ESCALATION: 4,
    MitreTactic.DEFENSE_EVASION: 5,
    MitreTactic.CREDENTIAL_ACCESS: 6,
    MitreTactic.DISCOVERY: 7,
    MitreTactic.LATERAL_MOVEMENT: 8,
    MitreTactic.COLLECTION: 9,
    MitreTactic.EXFILTRATION: 10,
    MitreTactic.IMPACT: 11,
}


@dataclass(frozen=True)
class MitreTechnique:
    """One ATT&CK (sub)technique: the id (``T1190`` / ``T1078.004``), a human name, and
    the primary tactic it plays in autosec's attack-path semantics."""

    technique_id: str
    name: str
    tactic: MitreTactic

    @property
    def url(self) -> str:
        # Sub-techniques nest under the parent: T1078.004 → /techniques/T1078/004
        base, _, sub = self.technique_id.partition(".")
        path = f"{base}/{sub}" if sub else base
        return f"https://attack.mitre.org/techniques/{path}/"

    def to_dict(self) -> dict:
        return {
            "technique_id": self.technique_id,
            "name": self.name,
            "tactic": self.tactic.value,
            "tactic_label": self.tactic.label,
            "url": self.url,
        }


#: Curated catalogue — only the techniques autosec actually maps to. Grows as pillars
#: add mappings; every id a pillar references MUST live here (a hygiene test asserts it).
TECHNIQUES: dict[str, MitreTechnique] = {
    t.technique_id: t
    for t in (
        MitreTechnique("T1190", "Exploit Public-Facing Application", MitreTactic.INITIAL_ACCESS),
        MitreTechnique("T1078.004", "Valid Accounts: Cloud Accounts", MitreTactic.PRIVILEGE_ESCALATION),
        MitreTechnique("T1098.003", "Account Manipulation: Additional Cloud Roles", MitreTactic.PRIVILEGE_ESCALATION),
        MitreTechnique("T1530", "Data from Cloud Storage", MitreTactic.COLLECTION),
        MitreTechnique("T1580", "Cloud Infrastructure Discovery", MitreTactic.DISCOVERY),
    )
}


def technique(technique_id: str) -> MitreTechnique:
    """Resolve a technique id to its ``MitreTechnique`` (raises ``KeyError`` if the id is
    not in the catalogue — mappings must reference known techniques)."""
    return TECHNIQUES[technique_id]


def order_flow(techniques: tuple[MitreTechnique, ...]) -> tuple[MitreTechnique, ...]:
    """Sort techniques into kill-chain order (stable) — the attack-flow for a path."""
    return tuple(sorted(techniques, key=lambda t: t.tactic.order))
