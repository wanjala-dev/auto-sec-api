"""Value object: a workspace's brand seed colour(s).

Neutrals and state colours are NOT part of the seed — only the primary (and an
optional secondary) accent drive the resolved palette. Framework-free.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from components.workspace.domain.errors import InvalidBrandSeedError

_HEX_RE = re.compile(r"^#?(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})$")


@dataclass(frozen=True)
class BrandSeed:
    primary: str
    secondary: str | None = None

    def __post_init__(self) -> None:
        if not self.primary or not _HEX_RE.match(self.primary.strip()):
            raise InvalidBrandSeedError(f"primary brand seed must be a hex colour: {self.primary!r}")
        if self.secondary not in (None, "") and not _HEX_RE.match(self.secondary.strip()):
            raise InvalidBrandSeedError(f"secondary brand seed must be a hex colour: {self.secondary!r}")
