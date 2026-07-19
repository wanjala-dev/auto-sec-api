"""Port for User-Agent string parsing used by session enrichment.

Framework-free. The concrete adapter (the ``user-agents`` library) lives
in infrastructure; the application layer only sees this interface and the
``DeviceInfo`` value carrier.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

# Canonical device_type values persisted on UserSession.device_type.
DEVICE_TYPE_DESKTOP = "desktop"
DEVICE_TYPE_MOBILE = "mobile"
DEVICE_TYPE_TABLET = "tablet"
DEVICE_TYPE_BOT = "bot"
DEVICE_TYPE_OTHER = "other"


@dataclass(frozen=True)
class DeviceInfo:
    """Parsed device/browser/OS facts from a User-Agent string."""

    device_type: str  # desktop|mobile|tablet|bot|other
    browser: str
    browser_version: str
    os: str
    os_version: str


class UserAgentParserPort(ABC):
    """Secondary/driven port for parsing a raw User-Agent header."""

    @abstractmethod
    def parse(self, user_agent: str) -> DeviceInfo:
        """Parse ``user_agent`` into a :class:`DeviceInfo`.

        MUST tolerate empty/garbage input — unparseable strings map to
        ``device_type="other"`` with blank component fields.
        """
