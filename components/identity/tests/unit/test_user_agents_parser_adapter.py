"""Unit tests: User-Agent → DeviceInfo mapping (T2-S2).

``map_user_agent`` is exercised with fake parsed objects (no library
invocation), then the full adapter is smoke-tested against the real
``user-agents`` library for one well-known UA and the empty string.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from components.identity.application.ports.user_agent_parser_port import DeviceInfo
from components.identity.infrastructure.adapters.user_agents_parser_adapter import (
    UserAgentsParserAdapter,
    map_user_agent,
)

pytestmark = pytest.mark.unit


@dataclass
class _FakeNamed:
    family: str = ""
    version_string: str = ""


@dataclass
class _FakeUA:
    is_bot: bool = False
    is_mobile: bool = False
    is_tablet: bool = False
    is_pc: bool = False
    browser: _FakeNamed = None
    os: _FakeNamed = None

    def __post_init__(self):
        self.browser = self.browser or _FakeNamed()
        self.os = self.os or _FakeNamed()


class TestMapUserAgent:
    def test_desktop_mapping_with_versions(self):
        ua = _FakeUA(
            is_pc=True,
            browser=_FakeNamed("Chrome", "126.0.0"),
            os=_FakeNamed("Mac OS X", "10.15.7"),
        )
        info = map_user_agent(ua)
        assert info == DeviceInfo(
            device_type="desktop",
            browser="Chrome",
            browser_version="126.0.0",
            os="Mac OS X",
            os_version="10.15.7",
        )

    def test_mobile_tablet_and_bot_mapping(self):
        assert map_user_agent(_FakeUA(is_mobile=True)).device_type == "mobile"
        assert map_user_agent(_FakeUA(is_tablet=True)).device_type == "tablet"
        assert map_user_agent(_FakeUA(is_bot=True)).device_type == "bot"

    def test_bot_wins_over_device_flags(self):
        # Bots often spoof mobile hints — bot classification takes priority.
        ua = _FakeUA(is_bot=True, is_mobile=True, is_pc=True)
        assert map_user_agent(ua).device_type == "bot"

    def test_unknown_flags_map_to_other(self):
        assert map_user_agent(_FakeUA()).device_type == "other"

    def test_ua_parser_other_marker_becomes_blank(self):
        ua = _FakeUA(browser=_FakeNamed("Other", ""), os=_FakeNamed("Other", ""))
        info = map_user_agent(ua)
        assert info.browser == ""
        assert info.os == ""

    def test_values_are_truncated_to_column_widths(self):
        ua = _FakeUA(
            is_pc=True,
            browser=_FakeNamed("B" * 200, "9" * 200),
            os=_FakeNamed("O" * 200, "8" * 200),
        )
        info = map_user_agent(ua)
        assert len(info.browser) == 64
        assert len(info.browser_version) == 32
        assert len(info.os) == 64
        assert len(info.os_version) == 32


class TestAdapterWithRealLibrary:
    CHROME_MAC = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )

    def test_parses_well_known_desktop_ua(self):
        info = UserAgentsParserAdapter().parse(self.CHROME_MAC)
        assert info.device_type == "desktop"
        assert info.browser == "Chrome"
        assert info.os == "Mac OS X"
        assert info.browser_version.startswith("126")

    def test_empty_and_garbage_input_do_not_raise(self):
        adapter = UserAgentsParserAdapter()
        assert adapter.parse("").device_type == "other"
        assert adapter.parse(None).device_type == "other"
        garbage = adapter.parse("\x00\x01 totally-not-a-ua")
        assert garbage.device_type in {"other", "bot"}
