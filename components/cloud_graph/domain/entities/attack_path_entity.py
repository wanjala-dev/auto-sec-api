"""AttackPathEntity — an immutable, ranked toxic-combination path in the asset graph.

A materialised result of the attack-path correlation job (ADR 0005 §6 / ADR 0004 §6):
a public entry asset that reaches a crown-jewel sink through typed entitlement/reach
edges. Frozen + framework-free; the background job computes these, the store persists
them, the HUD reads them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from components.cloud_graph.domain.value_objects.attack_path import AttackPathCategory
from components.shared_kernel.domain.security import RiskBand, Severity


@dataclass(frozen=True)
class AttackPathLeg:
    """One hop in the path: a typed edge from one asset to the next."""

    src_id: UUID
    src_label: str
    relation: str  # AssetRelation.value
    dst_id: UUID
    dst_label: str


@dataclass(frozen=True)
class AttackPathEntity:
    id: UUID
    workspace_id: UUID
    category: AttackPathCategory
    severity: Severity
    risk_score: float  # 0–100 contextual risk
    entry_asset_id: UUID
    entry_asset_urn: str
    entry_label: str
    target_asset_id: UUID
    target_asset_urn: str
    target_label: str
    title: str
    explanation: str
    legs: tuple[AttackPathLeg, ...] = ()
    asset_urns: tuple[str, ...] = ()  # ordered node chain (entry → … → target)
    computed_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.entry_asset_id == self.target_asset_id:
            raise ValueError("AttackPathEntity entry and target must differ")
        if not self.legs:
            raise ValueError("AttackPathEntity must have at least one leg")

    @property
    def length(self) -> int:
        """Number of hops (edges) from entry to target."""
        return len(self.legs)

    @property
    def risk_band(self) -> RiskBand:
        return RiskBand.from_score(self.risk_score)
