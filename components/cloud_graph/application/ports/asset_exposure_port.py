"""AssetExposurePort — the read seam that hands a finding's asset its exposure.

cloud_graph owns the real ``CloudAsset.exposure`` (public | internal | private), derived
from actual reachability (boto3) with a Prowler heuristic fallback. The contextual-risk
scorer (in the ``findings`` hub) needs that reachability as its amplifier term, correlated
by ``AssetUrn`` — the cross-pillar identity, not a cross-context FK (ADR 0004 C4). This
port is that read: given a batch of asset URNs, return each one's exposure. It is a
narrow, read-only cross-context query (C3) — the findings scorer depends on this port,
never on cloud_graph's models or repositories.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from uuid import UUID


class AssetExposurePort(ABC):
    @abstractmethod
    def exposure_by_urn(self, workspace_id: UUID, urns: Iterable[str]) -> dict[str, str]:
        """Map each known asset URN in ``urns`` to its exposure (public|internal|private).

        A URN with no matching (non-deleted) asset is simply absent from the result — the
        scorer treats absence as ``exposure_unknown`` (ADR 0013 resolved decision #3).
        Batched so a workspace-wide rescore reads exposure in one query, not N."""
