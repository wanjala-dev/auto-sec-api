"""Board-floor (minimum severity) resolution for AI-finding cards.

The board floor (ADR 0019 D4 layer 2) decides which raised findings become
Kanban cards at all: a finding below its source's floor stays SSOT-only (the
HUD findings panel) and never lands on the board's intake lane. Historically only
``code_security`` and ``vercel_posture`` carried a floor — hardcoded in the
handler's ``_SOURCE_BOARD`` mapping — so every other source flooded the board
with low-severity cards (QA report 2026-08-16, F9/§g5). This service makes the
floor configurable for EVERY source via ``settings.AI_BOARD_MIN_SEVERITY``
while preserving the mapping's baked-in defaults.

Lives in infrastructure because it reads Django settings — the application
layer stays framework-free and calls in through the handler's late import,
mirroring how the handler already reaches ``agents_board_service``.
"""

from __future__ import annotations

import logging

from django.conf import settings

from components.shared_kernel.domain.security import Severity

logger = logging.getLogger(__name__)

_VALID_SEVERITIES = {severity.value for severity in Severity}


def resolve_board_floor(source: str, default_floor: str | None) -> str | None:
    """Return the minimum severity name a *source*'s findings must meet to card.

    Precedence:
    1. a per-source entry in ``settings.AI_BOARD_MIN_SEVERITY`` (operator
       override — can tighten OR relax a baked-in floor);
    2. ``default_floor`` — the source's baked-in ``_SOURCE_BOARD`` floor
       (code_security / vercel_posture ship "high" per their ADRs);
    3. the config's ``"default"`` entry — the one-knob flood cap for every
       source that has no floor of its own.

    An unknown severity name is IGNORED with a warning and resolution falls
    through to the next rung — a config typo must never silently hide (or
    flood) the board.
    """
    config = getattr(settings, "AI_BOARD_MIN_SEVERITY", None) or {}
    if not isinstance(config, dict):
        config = {}

    for floor, origin in (
        (config.get(source), "settings"),
        (default_floor, "source mapping"),
        (config.get("default"), "settings default"),
    ):
        if not floor:
            continue
        if floor not in _VALID_SEVERITIES:
            logger.warning(
                "ai_board_floor_unknown_severity source=%s floor=%s origin=%s — ignoring",
                source,
                floor,
                origin,
            )
            continue
        return floor
    return None
