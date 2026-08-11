"""The rubric flag must EXIST in settings, not merely be readable.

``rubric_middleware_enabled`` reads the flag with
``getattr(settings, "DEEP_RUBRIC_MIDDLEWARE_ENABLED", False)``. A defaulted
getattr cannot tell "configured off" from "never defined" — and until
2026-08-11 it was never defined in any settings module. The result: the whole
middleware path (grader, verifier tool, evaluation telemetry, the
``rubric_first_pass_fail_rate`` metric) was unreachable outside tests, while
reading in code and docs as though it were live. Nothing failed; it simply
never ran.

So these tests assert the *module attribute*, not the runtime lookup. A future
edit that deletes the line from base.py fails here instead of silently
reverting us to that state.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from components.agents.infrastructure.adapters.langchain.deep.rubric import (
    MAX_ITERATIONS_CAP,
    rubric_middleware_enabled,
)

pytestmark = pytest.mark.unit

_FLAG = "DEEP_RUBRIC_MIDDLEWARE_ENABLED"
_SETTINGS_DIR = Path(importlib.import_module("api.settings.base").__file__).parent


class TestTheFlagIsDefinedNotJustDefaulted:
    def test_base_settings_defines_it(self):
        base = importlib.import_module("api.settings.base")
        assert hasattr(base, _FLAG), (
            f"{_FLAG} is not defined in api/settings/base.py. rubric_middleware_enabled "
            "would fall back to its getattr default, making the entire RubricMiddleware "
            "path unreachable while every docstring claims otherwise."
        )

    def test_it_defaults_off_so_production_keeps_the_proven_fallback(self):
        base = importlib.import_module("api.settings.base")
        assert getattr(base, _FLAG) is False

    @pytest.mark.parametrize("overlay", ["local", "dev"])
    def test_the_measured_environments_turn_it_on(self, overlay):
        """The swap has to actually run somewhere, or it is never verified.

        Asserted against the overlay SOURCE rather than by importing it: local
        and dev read required deployment env (``os.environ["SECRET_KEY"]``) at
        import time, so importing them here would test the fixture's env, not
        the setting.
        """
        source = (_SETTINGS_DIR / f"{overlay}.py").read_text()
        assert f'{_FLAG} = os.environ.get("{_FLAG}", "true")' in source, (
            f"{overlay}.py should default the swap ON so it gets measured; base.py keeps production on the fallback."
        )


class TestGatePrecedence:
    def test_config_opt_in_wins_over_a_global_off(self, settings):
        settings.DEEP_RUBRIC_MIDDLEWARE_ENABLED = False
        assert rubric_middleware_enabled({"rubric_middleware": True}) is True

    def test_global_on_needs_no_per_agent_config(self, settings):
        settings.DEEP_RUBRIC_MIDDLEWARE_ENABLED = True
        assert rubric_middleware_enabled({}) is True
        assert rubric_middleware_enabled(None) is True

    def test_both_off_is_off(self, settings):
        settings.DEEP_RUBRIC_MIDDLEWARE_ENABLED = False
        assert rubric_middleware_enabled({}) is False


class TestTheLoopStaysBounded:
    def test_the_cap_is_two(self):
        """Huang et al.: re-run returns collapse after the first reflection
        (iter 1 ~60% of errors, iter 2 ~25%, iter 3 ~5%). The cap is a
        correctness property, not a tuning knob — raising it trades real cost
        for noise and reopens the over-correction risk."""
        assert MAX_ITERATIONS_CAP == 2
