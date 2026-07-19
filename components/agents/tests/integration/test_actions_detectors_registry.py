import pytest

from components.agents.infrastructure.adapters.actions.detectors import registry
from components.agents.domain.detectors.base import BaseDetector


@pytest.fixture(autouse=True)
def isolate_registry():
    original = dict(registry._DETECTOR_REGISTRY)  # pylint: disable=protected-access
    registry._DETECTOR_REGISTRY.clear()  # pylint: disable=protected-access
    try:
        yield
    finally:
        registry._DETECTOR_REGISTRY.clear()  # pylint: disable=protected-access
        registry._DETECTOR_REGISTRY.update(original)  # pylint: disable=protected-access


class _DummyDetector(BaseDetector):
    slug = "dummy"
    name = "Dummy Detector"

    def execute(self, context):  # pragma: no cover - interface satisfied for type checking
        return []


def test_register_and_create_returns_configured_instance():
    registry.register(_DummyDetector)

    detector = registry.create("dummy", config={"threshold": 0.8})

    assert isinstance(detector, _DummyDetector)
    assert detector.config == {"threshold": 0.8}


def test_register_requires_slug():
    class NoSlugDetector(BaseDetector):
        pass

    with pytest.raises(ValueError):
        registry.register(NoSlugDetector)


def test_create_unknown_slug_raises_key_error():
    with pytest.raises(KeyError):
        registry.create("missing-detector")


def test_all_detectors_and_list_slugs_reflect_registration_order():
    class FirstDetector(BaseDetector):
        slug = "first"

    class SecondDetector(BaseDetector):
        slug = "second"

    registry.register(FirstDetector)
    registry.register(SecondDetector)

    slugs = list(registry.list_slugs())
    detectors = list(registry.all_detectors())

    assert slugs == ["first", "second"]
    assert detectors == [FirstDetector, SecondDetector]
