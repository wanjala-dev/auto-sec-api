"""User-Agent parsing adapter implementing UserAgentParserPort.

Wraps the ``user-agents`` library (ua-parser under the hood). Mapping to
the canonical ``device_type`` values:

* ``is_bot``    → ``bot``   (checked first — bots often spoof device hints)
* ``is_mobile`` → ``mobile``
* ``is_tablet`` → ``tablet``
* ``is_pc``     → ``desktop``
* anything else → ``other`` (includes empty/garbage UA strings)
"""

from __future__ import annotations

from components.identity.application.ports.user_agent_parser_port import (
    DEVICE_TYPE_BOT,
    DEVICE_TYPE_DESKTOP,
    DEVICE_TYPE_MOBILE,
    DEVICE_TYPE_OTHER,
    DEVICE_TYPE_TABLET,
    DeviceInfo,
    UserAgentParserPort,
)

# Field width guards — must match the UserSession column definitions.
_MAX_BROWSER = 64
_MAX_VERSION = 32
_MAX_OS = 64


def map_user_agent(ua) -> DeviceInfo:
    """Map a parsed ``user_agents`` object to a DeviceInfo.

    Split out from the adapter so the mapping is unit-testable with a
    fake parsed object (no library invocation needed).
    """
    if ua.is_bot:
        device_type = DEVICE_TYPE_BOT
    elif ua.is_mobile:
        device_type = DEVICE_TYPE_MOBILE
    elif ua.is_tablet:
        device_type = DEVICE_TYPE_TABLET
    elif ua.is_pc:
        device_type = DEVICE_TYPE_DESKTOP
    else:
        device_type = DEVICE_TYPE_OTHER

    browser = (ua.browser.family or "").strip()
    os_family = (ua.os.family or "").strip()
    # ua-parser uses "Other" as its unknown marker — store blank instead.
    if browser.lower() == "other":
        browser = ""
    if os_family.lower() == "other":
        os_family = ""

    return DeviceInfo(
        device_type=device_type,
        browser=browser[:_MAX_BROWSER],
        browser_version=(ua.browser.version_string or "")[:_MAX_VERSION],
        os=os_family[:_MAX_OS],
        os_version=(ua.os.version_string or "")[:_MAX_VERSION],
    )


class UserAgentsParserAdapter(UserAgentParserPort):
    """Concrete parser backed by the ``user-agents`` library."""

    def parse(self, user_agent: str) -> DeviceInfo:
        import user_agents

        return map_user_agent(user_agents.parse(user_agent or ""))
