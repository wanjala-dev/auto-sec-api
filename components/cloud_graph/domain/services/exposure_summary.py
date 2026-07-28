"""The cloud exposure / asset-inventory summary — the shape behind the HUD's
Attack-Surface and Asset-Inventory cards.

Pure value object + a builder. The numbers are all real counts (no fabricated
coverage %): asset inventory by exposure + type, and the attack surface = the
internet-exposed assets, how many of those carry an open critical/high finding
(correlated by ``asset_urn``, the cross-pillar key — architecture C4), and the
count of live toxic paths.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExposureSummary:
    total_assets: int
    public: int
    internal: int
    private: int
    by_type: tuple[tuple[str, int], ...]  # (resource_type, count), most first
    public_at_risk: int  # public assets with ≥1 open critical/high finding
    attack_paths: int  # live materialized toxic paths

    def to_dict(self) -> dict:
        return {
            "total_assets": self.total_assets,
            "exposure": {
                "public": self.public,
                "internal": self.internal,
                "private": self.private,
            },
            "by_type": [{"type": t, "count": c} for t, c in self.by_type],
            "attack_surface": {
                "public_assets": self.public,
                "public_at_risk": self.public_at_risk,
                "attack_paths": self.attack_paths,
            },
        }


def build(
    *,
    by_exposure: dict[str, int],
    by_type: list[tuple[str, int]],
    public_asset_urns: set[str],
    at_risk_asset_urns: set[str],
    attack_path_count: int,
) -> ExposureSummary:
    """Assemble the summary from the raw port reads. Correlation is a pure set
    intersection on ``asset_urn`` — the public assets that also carry an open
    critical/high finding are the ones that actually matter."""
    return ExposureSummary(
        total_assets=sum(by_exposure.values()),
        public=by_exposure.get("public", 0),
        internal=by_exposure.get("internal", 0),
        private=by_exposure.get("private", 0),
        by_type=tuple(by_type),
        public_at_risk=len(public_asset_urns & at_risk_asset_urns),
        attack_paths=attack_path_count,
    )
