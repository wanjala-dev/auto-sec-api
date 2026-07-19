"""
Infrastructure namespace – organised by **technical concern**.

Physical layout after the Explicit Architecture refactor:

    infrastructure/
        persistence/          # Django ORM apps (models, migrations, admin)
            users/
            workspaces/
            …
        __init__.py           # ← you are here

The ``_AliasFinder`` meta-path hook provides backward-compatible resolution so
that legacy import paths (``infrastructure.<context>.*``) continue to work by
transparently routing them to ``infrastructure.persistence.<context>.*``.

New code should always use the canonical ``infrastructure.persistence.`` prefix.
"""

from importlib.abc import Loader, MetaPathFinder
from importlib.util import spec_from_loader
import importlib
import sys
from pathlib import Path
from typing import Optional


class _AliasLoader(Loader):
    """Loader that returns the already-loaded target module."""

    def __init__(self, module):
        self.module = module

    def create_module(self, spec):
        return self.module

    def exec_module(self, module):
        return module


class _AliasFinder(MetaPathFinder):
    """Route ``infrastructure.<ctx>`` → ``infrastructure.persistence.<ctx>``.

    Resolution order
    ────────────────
    1. ``infrastructure.persistence.<ctx>.*`` — canonical path, physical files
       live under ``infrastructure/persistence/``.  Let the default finder
       handle them (return ``None``).

    2. ``infrastructure.<ctx>.*`` (legacy shorthand) — if the physical file
       exists under ``infrastructure/persistence/<ctx>/…``, rewrite to the
       canonical form and import it.

    3. Bare ``<ctx>.*`` (very old legacy) — if a matching directory exists
       inside ``infrastructure/persistence/``, rewrite to the canonical form.
    """

    _PREFIX = "infrastructure."
    _CANONICAL_PREFIX = "infrastructure.persistence."
    _PERSISTENCE_DIR = Path(__file__).resolve().parent / "persistence"

    # ── public API ───────────────────────────────────────────────────────
    def find_spec(self, fullname: str, path: Optional[list[str]] = None, target=None):
        # 1. Canonical path — let default finders handle it.
        if fullname.startswith(self._CANONICAL_PREFIX):
            return None

        # 2. Legacy shorthand: ``infrastructure.<ctx>.*``
        if fullname.startswith(self._PREFIX):
            suffix = fullname[len(self._PREFIX):]       # e.g. "users.models"
            return self._try_resolve(fullname, suffix)

        # 3. Very-old bare name: ``<ctx>.*``
        root = fullname.split(".", 1)[0]
        if (self._PERSISTENCE_DIR / root / "__init__.py").exists():
            return self._try_resolve(fullname, fullname)

        return None

    # ── helpers ───────────────────────────────────────────────────────────
    def _try_resolve(self, fullname: str, suffix: str):
        """Attempt to load ``infrastructure.persistence.<suffix>``."""
        rel = suffix.replace(".", "/")

        # Only resolve when a physical file actually exists under persistence/
        if not (
            (self._PERSISTENCE_DIR / f"{rel}.py").exists()
            or (self._PERSISTENCE_DIR / rel / "__init__.py").exists()
        ):
            return None

        canonical = f"infrastructure.persistence.{suffix}"

        try:
            module = importlib.import_module(canonical)
        except ModuleNotFoundError:
            return None

        # Cache under both the requested name and the canonical name so future
        # imports under either path return the same module object.
        sys.modules[fullname] = module
        sys.modules[canonical] = module

        # Patch parent package attribute for dotted access.
        parent_name, _, child_name = fullname.rpartition(".")
        if parent_name and child_name:
            parent_module = sys.modules.get(parent_name)
            if parent_module is not None:
                try:
                    setattr(parent_module, child_name, module)
                except Exception:
                    pass

        return spec_from_loader(fullname, _AliasLoader(module), origin="persistence-alias")


def _install_alias_finder():
    if not any(isinstance(finder, _AliasFinder) for finder in sys.meta_path):
        sys.meta_path.insert(0, _AliasFinder())


_install_alias_finder()
