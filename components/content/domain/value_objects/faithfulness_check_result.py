"""Content-owned value object for a send-time faithfulness check.

Mirrors the agents ``FaithfulnessReport`` but keeps the content context
decoupled from the agents domain type — the content faithfulness port
returns this VO, and the infrastructure adapter maps the agents report
into it. No framework imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FaithfulnessCheckResult:
    """Outcome of checking rendered copy against a grounding corpus.

    Attributes:
        ok: ``True`` when every numeric token in the copy is supported by
            the grounding corpus. Proper-noun mismatches are advisory and
            do NOT flip ``ok``.
        unsupported_numbers: readable numeric tokens present in the copy
            but absent from the grounding corpus (e.g. ``"$50,000"``).
        unsupported_names: multi-word proper-noun phrases present in the
            copy but absent from the corpus — advisory only.
        checked: total distinct facts checked (numbers + names).
    """

    ok: bool
    unsupported_numbers: tuple[str, ...] = field(default_factory=tuple)
    unsupported_names: tuple[str, ...] = field(default_factory=tuple)
    checked: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "unsupported_numbers": list(self.unsupported_numbers),
            "unsupported_names": list(self.unsupported_names),
            "checked": self.checked,
        }
