"""The detector registry must contain every detector that exists.

Detectors self-register at import time, so for a long while the registry held
whatever a hand-maintained import list in ``detector_cycle`` happened to name.
It omitted ``tasks`` and ``projects`` — 7 detector classes that could never be
created by slug, because ``registry.create()`` raises KeyError for anything
unregistered and ``_build_detectors`` catches that KeyError per entry. A cycle
configured with one of them quietly ran the others and logged a line nobody
read.

Two invariants, deliberately separate, because conflating them is what made
the fix dangerous:

* COMPLETENESS — every detector class that exists is registered and
  addressable. This is what was broken.
* DEFAULT ACTIVATION — what runs unattended on the scheduled cycle. Making the
  registry complete must NOT change this: it would switch 7 project-management
  detectors on for every customer as a side effect of a registration fix.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from components.agents.application.services import detector_cycle
from components.agents.infrastructure.adapters.actions import detectors as detectors_pkg
from components.agents.infrastructure.adapters.actions.detectors import registry

pytestmark = [pytest.mark.integration]


def _detector_slugs_on_disk() -> dict[str, str]:
    """``{slug: module_name}`` for every detector class, read WITHOUT importing.

    This is parsed with ``ast`` rather than imported, and that is the whole
    point. Detectors register as a side effect of import, so a helper that
    imported each module in order to enumerate it would REGISTER everything it
    found and then assert, truthfully but uselessly, that everything was
    registered. The first draft of this file did exactly that and passed
    against the unfixed code.

    Reading the source keeps the observation independent of the thing being
    observed.
    """
    found: dict[str, str] = {}
    package_dir = Path(detectors_pkg.__path__[0])
    for path in sorted(package_dir.glob("*.py")):
        if path.stem in {"__init__", "registry"}:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            base_names = {b.id for b in node.bases if isinstance(b, ast.Name)}
            base_names |= {b.attr for b in node.bases if isinstance(b, ast.Attribute)}
            if "BaseDetector" not in base_names:
                continue
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "slug" for t in stmt.targets)
                    and isinstance(stmt.value, ast.Constant)
                    and isinstance(stmt.value.value, str)
                ):
                    found[stmt.value.value] = path.stem
    return found


class TestRegistryIsComplete:
    def test_every_detector_on_disk_is_registered(self):
        detector_cycle._get_detector_modules()  # trigger discovery

        on_disk = set(_detector_slugs_on_disk())
        registered = set(registry.list_slugs())

        missing = sorted(on_disk - registered)
        assert not missing, (
            f"detector classes that exist but cannot be created by slug: {missing}. "
            "A detector that is not registered is not 'disabled' — it is unreachable, "
            "and the KeyError it raises is swallowed per-entry."
        )

    def test_the_previously_missing_detectors_are_reachable(self):
        """The 7 that were unreachable, named explicitly.

        Listed by name rather than by count so this test says what regressed
        rather than merely that something did.
        """
        detector_cycle._get_detector_modules()
        registered = set(registry.list_slugs())

        previously_missing = {
            slug for slug, module in _detector_slugs_on_disk().items() if module in {"tasks", "projects"}
        }
        assert len(previously_missing) == 7, f"expected 7 task/project detectors, found {previously_missing}"
        assert previously_missing <= registered


class TestDefaultCycleIsUnchanged:
    """Registration makes a detector available; it must not make it run."""

    def test_scheduled_cycle_does_not_pick_up_task_or_project_detectors(self):
        built = detector_cycle._build_detectors(None)

        modules = {type(d).__module__.rsplit(".", 1)[-1] for d in built}
        assert "tasks" not in modules, "registering the task detectors must not switch them on for every workspace"
        assert "projects" not in modules

    def test_scheduled_cycle_still_runs_the_security_detectors(self):
        """The other direction: the fix must not silence what already ran."""
        built = detector_cycle._build_detectors(None)

        modules = {type(d).__module__.rsplit(".", 1)[-1] for d in built}
        assert "logwatch" in modules, "the security-relevant LogWatch detector must still run unattended"
        assert modules <= detector_cycle._DEFAULT_CYCLE_MODULES

    def test_a_previously_unreachable_detector_can_now_be_requested_by_slug(self):
        """Availability is the point — an automation can name one explicitly."""
        detector_cycle._get_detector_modules()
        task_slugs = sorted(slug for slug, module in _detector_slugs_on_disk().items() if module == "tasks")
        assert task_slugs, "expected task detectors on disk"

        built = detector_cycle._build_detectors([task_slugs[0]])

        assert len(built) == 1
        assert built[0].slug == task_slugs[0]
