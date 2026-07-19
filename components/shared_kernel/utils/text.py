"""Framework-free text helpers shared across bounded contexts.

These replace small Django helpers (``django.utils.text.slugify``) so
application and domain layers don't have to import Django.
"""

from __future__ import annotations

import re
import unicodedata


_SLUG_NON_WORD = re.compile(r"[^\w\s-]")
_SLUG_HYPHENATE = re.compile(r"[-\s]+")


def slugify(value: str, *, allow_unicode: bool = False) -> str:
    """Stdlib-only re-implementation of Django's ``slugify``.

    Lowercases, strips accents (unless ``allow_unicode``), and replaces
    runs of whitespace / hyphens with a single hyphen. Matches Django's
    output for the inputs the codebase generates today.
    """
    if allow_unicode:
        value = unicodedata.normalize("NFKC", value)
    else:
        value = (
            unicodedata.normalize("NFKD", value)
            .encode("ascii", "ignore")
            .decode("ascii")
        )
    value = _SLUG_NON_WORD.sub("", value).strip().lower()
    return _SLUG_HYPHENATE.sub("-", value)
