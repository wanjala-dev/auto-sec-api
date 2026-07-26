"""Indicator of compromise — an immutable, validated IOC value object."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from enum import Enum

_HASH_RE = re.compile(r"^(?:[A-Fa-f0-9]{32}|[A-Fa-f0-9]{40}|[A-Fa-f0-9]{64})$")
# Deliberately conservative host match — a dotted, space-free, slash-free token.
_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9_](-?[A-Za-z0-9_])*\.)+[A-Za-z]{2,}$")


class IndicatorKind(str, Enum):
    IP = "ip"
    DOMAIN = "domain"
    URL = "url"
    FILE_HASH = "file_hash"


@dataclass(frozen=True)
class Indicator:
    kind: IndicatorKind
    value: str

    def __post_init__(self) -> None:
        cleaned = (self.value or "").strip()
        if not cleaned:
            raise ValueError("Indicator value cannot be empty")
        object.__setattr__(self, "value", cleaned)

    @classmethod
    def detect(cls, raw: str) -> Indicator | None:
        """Best-effort classify a raw string into an IOC (ip / hash / url / domain).

        Returns None when the string isn't a recognizable indicator, so a caller can
        fail cleanly instead of enriching garbage.
        """
        s = (raw or "").strip().strip('"').strip("'")
        if not s:
            return None
        try:
            ipaddress.ip_address(s)
            return cls(IndicatorKind.IP, s)
        except ValueError:
            pass
        if _HASH_RE.match(s):
            return cls(IndicatorKind.FILE_HASH, s.lower())
        if s.lower().startswith(("http://", "https://")):
            return cls(IndicatorKind.URL, s)
        if _DOMAIN_RE.match(s):
            return cls(IndicatorKind.DOMAIN, s.lower())
        return None
