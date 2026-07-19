from __future__ import annotations

import pytest

from components.sign_off.application.providers.sign_off_registry_provider import SignOffRegistry
from components.sign_off.domain.errors import UnregisteredArtifactError
from components.sign_off.tests.unit.fakes import FakeSignOffAdapter

pytestmark = pytest.mark.unit


def test_register_and_resolve():
    registry = SignOffRegistry()
    adapter = FakeSignOffAdapter("newsletter")
    registry.register(adapter)
    assert registry.get_adapter("newsletter") is adapter
    assert registry.supported_types() == ("newsletter",)


def test_unregistered_artifact_raises():
    registry = SignOffRegistry()
    with pytest.raises(UnregisteredArtifactError):
        registry.get_adapter("financial_report")


def test_register_overwrites_same_type():
    registry = SignOffRegistry()
    first = FakeSignOffAdapter("blog")
    second = FakeSignOffAdapter("blog")
    registry.register(first)
    registry.register(second)
    assert registry.get_adapter("blog") is second
    assert registry.supported_types() == ("blog",)
