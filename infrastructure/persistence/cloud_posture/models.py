"""Cloud-posture persistence — RETIRED store (audit R2 / ADR 0004 C6).

The legacy per-pillar snapshot tables (``CloudPostureScan`` /
``CloudPostureFinding``) are deleted: scan history was data-migrated into
scanning's generic ``ScanRun`` (migration ``0002``) and findings have lived in
the unified Finding SSOT since the Phase 3b dual-write. The HUD posture card
reads ``ScanRun`` + the SSOT via
``components/cloud_posture/infrastructure/services/posture_summary.py``.

The Django app remains (it owns the deletion migration history); no models
live here. Do NOT add a per-pillar result table — pillar-specific richness
rides each SSOT ``Finding``'s ``attributes`` (ADR 0004 C6).
"""

from __future__ import annotations
