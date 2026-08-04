"""Tag slug normalization — the ONE implementation every entry point uses (ADR 0015 D3).

Rules (grounded in R5 Datadog / R6 Kubernetes / R9 Jira / R14 Sentry):

1. Input: a raw string, optionally ``namespace:value`` (the first ``:`` splits;
   any further ``:`` is invalid).
2. The display ``name`` is the value part: trimmed, internal whitespace runs
   collapsed to a single space, control characters stripped, Unicode
   NFC-normalized. Original casing is preserved for display.
3. The ``slug`` is the lowercase-ASCII identity: spaces → ``-``, restricted to
   ``[a-z0-9]`` with ``- _ .`` separators, must start and end alphanumeric
   (the K8s rule). Namespaced form: ``namespace:value-slug``.
4. ``namespace``: lowercase, ``[a-z][a-z0-9_-]*``, ≤ 32 chars, must start with a
   letter (the Datadog rule). Empty for flat tags.
5. Dedup is case-insensitive by construction — ``macOS`` and ``macos`` normalize
   to the same slug and are one tag (the Jira failure mode, designed out).
6. Empty-after-normalization ⇒ ``InvalidTagError``.

Implemented as parse-then-validate (the single-char degenerate case is legal),
with the full-slug regex as the final gate.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from components.tagging.domain.constants import (
    MAX_NAME_LENGTH,
    MAX_NAMESPACE_LENGTH,
    MAX_SLUG_LENGTH,
    MAX_VALUE_LENGTH,
)
from components.tagging.domain.errors import InvalidTagError

# The final validation gate for a full (optionally namespaced) slug.
SLUG_RE = re.compile(r"^(?:[a-z][a-z0-9_-]{0,31}:)?[a-z0-9](?:[a-z0-9_.-]{0,62}[a-z0-9])?$")
NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

_ALLOWED_VALUE_CHARS = re.compile(r"[^a-z0-9_.\-]")


@dataclass(frozen=True)
class ParsedTag:
    """The normalized identity of one tag input: display name (value part, original
    casing), namespace ("" = flat), and the full slug (``namespace:value`` or
    ``value``) — the (workspace, slug) uniqueness key."""

    namespace: str
    name: str
    slug: str


def _clean_display(raw: str) -> str:
    """Trim, collapse whitespace runs, strip control characters, NFC-normalize."""
    text = unicodedata.normalize("NFC", raw)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cc")
    return " ".join(text.split())


def _slugify_value(name: str) -> str:
    """Lowercase-ASCII slug of a display name: spaces → ``-``, restrict to the
    allowed charset. Start/end validation happens in the caller's final gate."""
    ascii_text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = ascii_text.lower().replace(" ", "-")
    return _ALLOWED_VALUE_CHARS.sub("", slug)


def _normalize_namespace(raw_namespace: str) -> str:
    namespace = _clean_display(raw_namespace).lower()
    if not namespace:
        raise InvalidTagError("Tag namespace is empty after normalization.")
    if len(namespace) > MAX_NAMESPACE_LENGTH:
        raise InvalidTagError(f"Tag namespace exceeds {MAX_NAMESPACE_LENGTH} characters.")
    if not NAMESPACE_RE.match(namespace):
        raise InvalidTagError(
            "Tag namespace must be lowercase, start with a letter, and use only letters, digits, '-' or '_'."
        )
    return namespace


def parse(raw: str, *, namespace: str = "") -> ParsedTag:
    """Normalize a raw tag input (``value`` or ``namespace:value``) into its
    identity. An explicit ``namespace`` argument may be supplied instead of the
    inline ``namespace:`` prefix — supplying both is invalid.

    Raises ``InvalidTagError`` on anything that does not normalize to a legal tag.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise InvalidTagError("Tag name is required.")

    inline_namespace = ""
    value_part = raw
    if ":" in raw:
        inline_namespace, value_part = raw.split(":", 1)
        if ":" in value_part:
            raise InvalidTagError("Tag may contain at most one ':' (namespace:value).")

    if inline_namespace and namespace:
        raise InvalidTagError("Provide the namespace inline OR as a field, not both.")

    resolved_namespace = ""
    raw_namespace = inline_namespace or namespace
    if raw_namespace:
        resolved_namespace = _normalize_namespace(raw_namespace)

    name = _clean_display(value_part)
    if not name:
        raise InvalidTagError("Tag name is empty after normalization.")
    if len(name) > MAX_NAME_LENGTH:
        raise InvalidTagError(f"Tag name exceeds {MAX_NAME_LENGTH} characters.")

    value_slug = _slugify_value(name)
    if not value_slug:
        raise InvalidTagError("Tag name has no slug-safe characters.")
    if len(value_slug) > MAX_VALUE_LENGTH:
        raise InvalidTagError(f"Tag slug value exceeds {MAX_VALUE_LENGTH} characters.")

    slug = f"{resolved_namespace}:{value_slug}" if resolved_namespace else value_slug
    if len(slug) > MAX_SLUG_LENGTH:
        raise InvalidTagError(f"Tag slug exceeds {MAX_SLUG_LENGTH} characters.")
    if not SLUG_RE.match(slug):
        raise InvalidTagError(
            "Tag slug must start and end alphanumeric and use only letters, digits, "
            "'-', '_' or '.' (optionally 'namespace:value')."
        )
    return ParsedTag(namespace=resolved_namespace, name=name, slug=slug)


def normalize_slug(raw: str) -> str:
    """Normalize a raw tag handle to its slug. Raises ``InvalidTagError``."""
    return parse(raw).slug


def try_normalize_slug(raw: str) -> str | None:
    """Lenient form for filter/resolve paths: an un-normalizable input is simply
    unknown (matches nothing / no-op) rather than an error."""
    try:
        return normalize_slug(raw)
    except InvalidTagError:
        return None


def validate_color(color: str) -> str:
    """'' or '#RRGGBB' (D3). Returns the value; raises ``InvalidTagError`` otherwise."""
    if color and not COLOR_RE.match(color):
        raise InvalidTagError("Tag color must be '' or '#RRGGBB'.")
    return color
