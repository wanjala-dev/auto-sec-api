"""Table-driven unit tests for the ONE slug normalization implementation (ADR 0015 D3)."""

from __future__ import annotations

import pytest

from components.tagging.domain.constants import (
    RESERVED_NAMESPACES,
    SYSTEM_ONLY_NAMESPACES,
    is_reserved_namespace,
    is_system_only_namespace,
)
from components.tagging.domain.errors import InvalidTagError
from components.tagging.domain.value_objects.tag_slug import (
    normalize_slug,
    parse,
    try_normalize_slug,
    validate_color,
)

pytestmark = [pytest.mark.unit]


class TestParseValid:
    @pytest.mark.parametrize(
        ("raw", "namespace", "name", "slug"),
        [
            # Flat tags
            ("needs-review", "", "needs-review", "needs-review"),
            ("Needs Review", "", "Needs Review", "needs-review"),
            ("  needs   review  ", "", "needs review", "needs-review"),  # whitespace collapsed
            ("macOS", "", "macOS", "macos"),  # display keeps casing; slug folds
            ("MACOS", "", "MACOS", "macos"),  # case-insensitive dedup by construction (R9)
            ("a", "", "a", "a"),  # single-char degenerate case is legal
            ("v1.2.3", "", "v1.2.3", "v1.2.3"),  # dots allowed inside
            ("snake_case", "", "snake_case", "snake_case"),
            # Namespaced tags — first ':' splits
            ("env:prod", "env", "prod", "env:prod"),
            ("Env: Prod", "env", "Prod", "env:prod"),  # namespace lowercased, value trimmed
            ("owner:Payments Team", "owner", "Payments Team", "owner:payments-team"),
            # Unicode → NFKD-folded ASCII slug
            ("café", "", "café", "cafe"),
        ],
    )
    def test_parse(self, raw, namespace, name, slug):
        parsed = parse(raw)
        assert parsed.namespace == namespace
        assert parsed.name == name
        assert parsed.slug == slug

    def test_explicit_namespace_argument(self):
        parsed = parse("Prod", namespace="env")
        assert parsed.slug == "env:prod"
        assert parsed.namespace == "env"

    def test_control_characters_are_stripped(self):
        parsed = parse("bad\x00tag\x07")
        assert parsed.name == "badtag"
        assert parsed.slug == "badtag"

    def test_disallowed_punctuation_is_dropped(self):
        assert parse("needs review!").slug == "needs-review"


class TestParseInvalid:
    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "   ",
            ":",
            "a::b",  # more than one ':'
            "env:prod:extra",
            "9env:prod",  # namespace must start with a letter
            "-env:prod",
            "€€€",  # nothing slug-safe survives
            "x" * 65,  # name > 64
            "env:" + "x" * 65,  # value > 64
            ("n" * 33) + ":val",  # namespace > 32
        ],
    )
    def test_invalid_inputs_raise(self, raw):
        with pytest.raises(InvalidTagError):
            parse(raw)

    def test_inline_and_explicit_namespace_conflict(self):
        with pytest.raises(InvalidTagError):
            parse("env:prod", namespace="team")

    def test_non_string_raises(self):
        with pytest.raises(InvalidTagError):
            parse(None)  # type: ignore[arg-type]

    def test_leading_separator_after_slugging_is_invalid(self):
        # Slug must start alphanumeric (the K8s rule, R6).
        with pytest.raises(InvalidTagError):
            parse("---")


class TestHelpers:
    def test_normalize_slug(self):
        assert normalize_slug("Env: Prod") == "env:prod"

    def test_try_normalize_slug_is_lenient(self):
        assert try_normalize_slug("Env: Prod") == "env:prod"
        assert try_normalize_slug("a::b") is None
        assert try_normalize_slug("") is None

    def test_validate_color(self):
        assert validate_color("") == ""
        assert validate_color("#2EDBE8") == "#2EDBE8"
        for bad in ("2EDBE8", "#12345", "#12345G", "red"):
            with pytest.raises(InvalidTagError):
                validate_color(bad)

    def test_reserved_and_system_namespaces(self):
        assert set(SYSTEM_ONLY_NAMESPACES) <= set(RESERVED_NAMESPACES)
        assert is_system_only_namespace("risk")
        assert not is_system_only_namespace("owner")
        assert is_reserved_namespace("env")
        assert not is_reserved_namespace("custom")
