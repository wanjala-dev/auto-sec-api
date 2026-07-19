"""Input DTOs for the sign-off decision endpoints.

Frozen dataclasses that parse the (small) request bodies for approve /
request-changes / reject, so the controller stays a thin translate-and-delegate
layer.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ApproveRequest:
    override_reason: str | None = None

    @classmethod
    def from_request(cls, data: dict) -> "ApproveRequest":
        reason = data.get("override_reason")
        return cls(override_reason=str(reason) if reason else None)


@dataclass(frozen=True)
class ReviewDecisionRequest:
    """Shared shape for request-changes / reject (codes + free-text note)."""

    codes: tuple[str, ...] = ()
    note: str = ""

    @classmethod
    def from_request(cls, data: dict) -> "ReviewDecisionRequest":
        return cls(
            codes=tuple(data.get("codes") or ()),
            note=str(data.get("note") or ""),
        )
