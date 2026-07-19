"""File-backed prompt registry — Wave 3 of the prompt-evaluation plan.

Each prompt is a YAML file under ``data/`` with this shape:

.. code-block:: yaml

    id: planner.system
    description: >
      One-line purpose. Read by humans in PRs and by the
      ``replay_conversation`` admin tool.
    template_variables:
      - agent_catalog          # optional list of {var} placeholders the
                               # caller substitutes at render time.
    active: v2                 # which version ``get("planner.system",
                               # version="active")`` resolves to.
    versions:
      v1:
        created_at: 2026-05-08
        created_by: henry
        notes: |
          Why this version exists. One paragraph.
        template: |
          You are a planner that outputs only JSON.
          ...
      v2:
        ...

The registry is module-level cached — YAML is parsed once per process
and frozen. Tests that need a different layout monkeypatch the
``_DATA_DIR`` constant; production callers never override.

Public API:

* ``PromptRegistry.get(prompt_id, version="active") -> str`` —
  return the raw template (un-rendered, no variable substitution).
* ``PromptRegistry.render(prompt_id, version="active", **vars) -> str`` —
  apply ``str.format`` with the supplied variables.
* ``PromptRegistry.versions(prompt_id) -> list[str]`` — enumerate
  every version registered for the prompt, oldest first.
* ``PromptRegistry.active_version(prompt_id) -> str`` — read the
  ``active`` pointer.
* ``PromptRegistry.all_prompt_ids() -> list[str]`` — list every
  registered prompt, alphabetically sorted.

Validation rules enforced at load time:

* ``id`` matches the file stem.
* ``active`` is one of the listed ``versions``.
* Every version has ``template``, ``created_at``, ``created_by``.
* Every ``{placeholder}`` in every template appears in the
  ``template_variables`` list (and vice versa) — keeps the contract
  with callers explicit and surfaces typos at boot rather than at
  call time.
"""
from __future__ import annotations

import functools
import logging
import re
import string
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent / "data"

_PROMPT_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


class PromptRegistryError(Exception):
    """Base class for registry-level configuration errors."""


class PromptNotFoundError(PromptRegistryError):
    """The requested ``prompt_id`` is not registered."""


class PromptVersionNotFoundError(PromptRegistryError):
    """The requested ``version`` does not exist for this ``prompt_id``."""


class PromptRegistry:
    """File-backed registry of versioned prompt templates."""

    # ── Public API ─────────────────────────────────────────────────

    @staticmethod
    def get(prompt_id: str, version: str = "active") -> str:
        """Return the raw template for the (prompt_id, version) pair.

        ``version="active"`` resolves the file's ``active`` pointer.
        Use ``render`` if you need ``{placeholder}`` substitution.
        """
        prompt = _load(prompt_id)
        resolved = _resolve_version(prompt, version)
        return prompt["versions"][resolved]["template"]

    @staticmethod
    def render(prompt_id: str, version: str = "active", **variables: Any) -> str:
        """Return the template with ``{variable}`` substitutions applied.

        Templates declared without ``template_variables`` are static —
        callers should use ``get()`` for those. Calling ``render`` on a
        static template raises ``PromptRegistryError`` so a typo never
        silently no-ops.
        """
        template = PromptRegistry.get(prompt_id, version=version)
        prompt = _load(prompt_id)
        declared = set(prompt.get("template_variables") or [])
        supplied = set(variables.keys())
        if not declared:
            raise PromptRegistryError(
                f"render({prompt_id!r}) called on a static prompt — "
                "use get() instead. (No template_variables declared.)"
            )
        if declared != supplied:
            missing = sorted(declared - supplied)
            extra = sorted(supplied - declared)
            raise PromptRegistryError(
                f"render({prompt_id!r}) variables mismatch: "
                f"missing={missing} extra={extra}"
            )
        return template.format(**variables)

    @staticmethod
    def versions(prompt_id: str) -> list[str]:
        """Return every version of the prompt, oldest first."""
        prompt = _load(prompt_id)
        return list(prompt["versions"].keys())

    @staticmethod
    def active_version(prompt_id: str) -> str:
        """Return the version key the ``active`` pointer points at."""
        prompt = _load(prompt_id)
        return prompt["active"]

    @staticmethod
    def metadata(prompt_id: str, version: str = "active") -> dict[str, Any]:
        """Return the version's metadata block (no ``template`` key)."""
        prompt = _load(prompt_id)
        resolved = _resolve_version(prompt, version)
        entry = dict(prompt["versions"][resolved])
        entry.pop("template", None)
        entry["id"] = prompt_id
        entry["version"] = resolved
        return entry

    @staticmethod
    def all_prompt_ids() -> list[str]:
        """Return every registered prompt id, alphabetically sorted."""
        return sorted(_discover_prompt_ids())

    @staticmethod
    def clear_cache() -> None:
        """Drop the in-process YAML cache. Test-only escape hatch."""
        _load.cache_clear()
        _discover_prompt_ids.cache_clear()


# ── Loader internals ────────────────────────────────────────────────


def _resolve_version(prompt: dict[str, Any], version: str) -> str:
    if version == "active":
        return prompt["active"]
    if version not in prompt["versions"]:
        raise PromptVersionNotFoundError(
            f"version={version!r} not registered for prompt_id={prompt['id']!r}; "
            f"available={list(prompt['versions'].keys())}"
        )
    return version


@functools.cache
def _discover_prompt_ids() -> tuple[str, ...]:
    if not _DATA_DIR.exists():
        return ()
    return tuple(sorted(p.stem for p in _DATA_DIR.glob("*.yaml")))


@functools.cache
def _load(prompt_id: str) -> dict[str, Any]:
    """Load + validate one prompt file. Cached per-process."""
    path = _DATA_DIR / f"{prompt_id}.yaml"
    if not path.exists():
        raise PromptNotFoundError(
            f"prompt_id={prompt_id!r} not found; expected {path}"
        )
    raw = yaml.safe_load(path.read_text())
    _validate(prompt_id, raw, path)
    return raw


def _validate(prompt_id: str, prompt: dict[str, Any], path: Path) -> None:
    if not isinstance(prompt, dict):
        raise PromptRegistryError(f"{path}: top-level must be a mapping")

    file_id = prompt.get("id")
    if file_id != prompt_id:
        raise PromptRegistryError(
            f"{path}: id={file_id!r} does not match filename={prompt_id!r}"
        )
    if not _PROMPT_ID_RE.match(prompt_id):
        raise PromptRegistryError(
            f"{path}: id={prompt_id!r} must be lowercase dotted "
            f"(e.g. 'planner.system')"
        )

    versions = prompt.get("versions")
    if not isinstance(versions, dict) or not versions:
        raise PromptRegistryError(f"{path}: at least one version is required")

    active = prompt.get("active")
    if active not in versions:
        raise PromptRegistryError(
            f"{path}: active={active!r} is not one of versions "
            f"{list(versions.keys())}"
        )

    declared_vars = set(prompt.get("template_variables") or [])
    formatter = string.Formatter()
    for version, entry in versions.items():
        if not isinstance(entry, dict):
            raise PromptRegistryError(
                f"{path}: version={version!r} must be a mapping"
            )
        for required in ("template", "created_at", "created_by"):
            if required not in entry:
                raise PromptRegistryError(
                    f"{path}: version={version!r} missing required "
                    f"field {required!r}"
                )
        template = entry["template"]
        if not isinstance(template, str) or not template.strip():
            raise PromptRegistryError(
                f"{path}: version={version!r} template must be a "
                "non-empty string"
            )
        # Templates with declared variables are .format()-ready (and
        # must double any literal braces in their text). Templates
        # without declared variables are static raw strings — skip
        # placeholder parsing entirely so JSON examples containing
        # ``{"foo": ...}`` don't trip the formatter.
        if not declared_vars:
            continue
        try:
            seen_vars = {
                name for _, name, _, _ in formatter.parse(template) if name
            }
        except ValueError as exc:
            raise PromptRegistryError(
                f"{path}: version={version!r} template has unmatched braces; "
                f"double literal braces as '{{{{' / '}}}}' when "
                f"template_variables is declared. ({exc})"
            ) from exc
        if seen_vars != declared_vars:
            missing = sorted(declared_vars - seen_vars)
            extra = sorted(seen_vars - declared_vars)
            raise PromptRegistryError(
                f"{path}: version={version!r} template variables mismatch — "
                f"declared={sorted(declared_vars)} seen={sorted(seen_vars)} "
                f"missing_in_template={missing} undeclared={extra}"
            )
