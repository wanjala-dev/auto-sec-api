"""Unit tests for ``resolve_board_floor`` precedence (no DB).

Precedence: per-source settings override → the source's baked-in
``_SOURCE_BOARD`` floor → the settings "default" knob. Unknown severity names
are ignored (with a warning) and fall through — a config typo must never
silently hide or flood the board.
"""

from __future__ import annotations

import logging

import pytest

from components.agents.infrastructure.services.board_floor import resolve_board_floor

pytestmark = [pytest.mark.unit]


def test_no_config_no_default_yields_no_floor(settings):
    settings.AI_BOARD_MIN_SEVERITY = {}
    assert resolve_board_floor("logwatch.error", None) is None


def test_baked_in_default_survives_empty_config(settings):
    settings.AI_BOARD_MIN_SEVERITY = {}
    assert resolve_board_floor("code_security.opengrep", "high") == "high"


def test_per_source_override_beats_baked_in_default(settings):
    """An operator can RELAX an ADR floor as well as tighten one."""
    settings.AI_BOARD_MIN_SEVERITY = {"code_security.opengrep": "informational"}
    assert resolve_board_floor("code_security.opengrep", "high") == "informational"


def test_baked_in_default_beats_the_global_knob(settings):
    """The "default" knob only fills sources that have no floor of their own."""
    settings.AI_BOARD_MIN_SEVERITY = {"default": "medium"}
    assert resolve_board_floor("code_security.opengrep", "high") == "high"


def test_global_knob_floors_floorless_sources(settings):
    settings.AI_BOARD_MIN_SEVERITY = {"default": "medium"}
    assert resolve_board_floor("logwatch.error", None) == "medium"


def test_unknown_severity_is_ignored_and_falls_through(settings, caplog):
    settings.AI_BOARD_MIN_SEVERITY = {"logwatch.error": "sev1", "default": "high"}
    with caplog.at_level(logging.WARNING, logger="components.agents.infrastructure.services.board_floor"):
        assert resolve_board_floor("logwatch.error", None) == "high"
    assert any("ai_board_floor_unknown_severity" in record.message for record in caplog.records)


def test_non_dict_config_is_ignored(settings):
    settings.AI_BOARD_MIN_SEVERITY = "high"  # a mis-set env survives as a no-op
    assert resolve_board_floor("logwatch.error", None) is None
