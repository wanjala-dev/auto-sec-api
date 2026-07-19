"""Contract: every @register_agent name must have a DEFAULT_AGENT_TYPES entry.

Caught 2026-06-09 on prod: PR #277 registered ``user_agent`` in the
LangChain ``AgentRegistry`` and the planner.system.yaml v5 prompt routed
to it, but ``DEFAULT_AGENT_TYPES`` was never updated. The deep-run
executor's ``AgentService._get_agent_type`` consults the
``AgentType`` Django catalogue (seeded from ``DEFAULT_AGENT_TYPES``), so
it raised ``Unsupported agent type: user_agent`` and dropped the planner's
task on the floor. The smoke chat for "Find Henry Wanjala" returned
"deep agent finished without producing a response."

This test pins the two registries together so a missing catalogue row
fails CI instead of silently breaking a production chat.
"""
from __future__ import annotations

from components.agents.application.config.agent_defaults import DEFAULT_AGENT_TYPES
from components.agents.infrastructure.adapters.langchain.agents import discover_agents
from components.agents.infrastructure.adapters.langchain.base import AgentRegistry


def _registered_classes_to_names() -> dict[type, set[str]]:
    """Group every registered name by the class it points at.

    ``AgentRegistry`` stores every alias as a distinct key pointing at the
    same class. The deep-run executor only needs ONE of those names to
    appear in ``DEFAULT_AGENT_TYPES`` (matched against ``slug`` or
    ``aliases``) for dispatch to succeed, so the contract is: for each
    registered class, at least one of its names must be catalogued.
    """
    discover_agents()
    grouped: dict[type, set[str]] = {}
    for name, cls in AgentRegistry._agents.items():  # type: ignore[attr-defined]
        grouped.setdefault(cls, set()).add(name)
    return grouped


def _catalogued_names() -> set[str]:
    """Every name (slug + every alias) the AgentType catalog knows."""
    names: set[str] = set()
    for entry in DEFAULT_AGENT_TYPES:
        names.add(str(entry["slug"]))
        for alias in entry.get("aliases", []) or []:
            names.add(str(alias))
    return names


def test_every_registered_agent_class_is_in_default_catalog():
    grouped = _registered_classes_to_names()
    catalogued = _catalogued_names()

    missing: list[tuple[str, list[str]]] = []
    for cls, names in grouped.items():
        if not (names & catalogued):
            missing.append((cls.__name__, sorted(names)))

    assert not missing, (
        "Every @register_agent class must have a DEFAULT_AGENT_TYPES entry — "
        "the deep-run executor looks agent_type up in the AgentType Django "
        "catalogue seeded from DEFAULT_AGENT_TYPES. Missing entries cause "
        "the executor to raise 'Unsupported agent type' and drop the "
        "planner's task on the floor. Missing classes "
        f"(name -> registered names): {missing}"
    )


def test_no_orphan_catalog_entries():
    grouped = _registered_classes_to_names()
    registered_names: set[str] = set()
    for names in grouped.values():
        registered_names |= names
    catalogued = _catalogued_names()

    orphans = catalogued - registered_names
    assert not orphans, (
        "Every DEFAULT_AGENT_TYPES slug + alias must correspond to a name "
        "the LangChain @register_agent decorator registered. Orphan entries "
        f"make the planner route to nothing. Orphan names: {sorted(orphans)}"
    )


def test_catalog_class_paths_resolve():
    """Every class_path in DEFAULT_AGENT_TYPES must import successfully."""
    import importlib

    failures: list[tuple[str, str]] = []
    for entry in DEFAULT_AGENT_TYPES:
        module_path, _, class_name = entry["class_path"].rpartition(".")
        try:
            module = importlib.import_module(module_path)
            getattr(module, class_name)
        except (ImportError, AttributeError) as exc:
            failures.append((entry["slug"], f"{type(exc).__name__}: {exc}"))

    assert not failures, (
        "Every class_path in DEFAULT_AGENT_TYPES must resolve. "
        f"Failures: {failures}"
    )
