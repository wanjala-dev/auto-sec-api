"""Locust entrypoint. See `.claude/rules/load-testing.md` for the rules.

Run examples (use Make targets in normal flow — they set LOAD_PROFILE):

    LOAD_PROFILE=smoke  locust --headless -f tests/load/locustfile.py --host=http://localhost:8000
    LOAD_PROFILE=avg    locust --headless -f tests/load/locustfile.py --host=http://localhost:8000
    LOAD_PROFILE=stress locust --headless -f tests/load/locustfile.py --host=http://localhost:8000

Locust 2.x has no ``--shape`` flag — it auto-picks the LoadTestShape subclass
present in the locustfile's namespace. We honour ``LOAD_PROFILE`` by importing
only the corresponding shape, so exactly one is in scope.
"""
from __future__ import annotations

# Put the repo root first on sys.path so ``tests.load.*`` resolves to our
# directory rather than a ``tests`` package shipped by some site-packages
# library (Django plugins occasionally ship one, which would otherwise
# shadow our imports and produce a confusing ModuleNotFoundError).
import sys as _sys
from pathlib import Path as _Path

_REPO_ROOT = _Path(__file__).resolve().parents[2]
_repo_root_str = str(_REPO_ROOT)
if _repo_root_str in _sys.path:
    _sys.path.remove(_repo_root_str)
_sys.path.insert(0, _repo_root_str)

import os as _os

# Profile-aware user-class selection. Smoke uses a dedicated single-pass
# walker (coverage > load); any heavier profile uses the weighted per-context
# users + cross-context journey (realistic distribution under load).
_profile = _os.getenv("LOAD_PROFILE", "smoke").lower()

if _profile == "smoke":
    # noqa: F401 — register the walker with Locust's discovery.
    from tests.load.scenarios.smoke_walk import SmokeWalkUser  # noqa: F401
else:
    # noqa: F401 — these imports register HttpUser classes with Locust's discovery.
    from tests.load.scenarios.agents_scenarios import AgentsLoadUser  # noqa: F401
    from tests.load.scenarios.budgeting_scenarios import BudgetingLoadUser  # noqa: F401
    from tests.load.scenarios.health_scenarios import HealthLoadUser  # noqa: F401
    from tests.load.scenarios.identity_scenarios import IdentityLoadUser  # noqa: F401
    from tests.load.scenarios.sponsorship_scenarios import SponsorshipLoadUser  # noqa: F401
    from tests.load.scenarios.workspace_scenarios import WorkspaceLoadUser  # noqa: F401
    # Cross-context end-to-end journeys
    from tests.load.journeys.sponsor_browse_journey import SponsorBrowseJourneyUser  # noqa: F401

# Shape selection — exactly one shape class lands in this module's namespace,
# chosen by LOAD_PROFILE. Locust auto-picks the only LoadTestShape subclass
# it finds here.
from tests.load.shapes import PROFILE_TO_SHAPE as _PROFILE_TO_SHAPE

try:
    ActiveShape = _PROFILE_TO_SHAPE[_profile]
except KeyError as _exc:
    raise RuntimeError(
        f"Unknown LOAD_PROFILE={_profile!r}; valid: {sorted(_PROFILE_TO_SHAPE)}"
    ) from _exc
