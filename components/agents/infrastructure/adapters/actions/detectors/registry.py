"""Detector registry for Orchestrator automations."""

from __future__ import annotations

from typing import Dict, Iterable, Optional, Type

from components.agents.domain.detectors.base import BaseDetector

_DETECTOR_REGISTRY: Dict[str, Type[BaseDetector]] = {}


def register(detector: Type[BaseDetector]) -> Type[BaseDetector]:
    """Register a detector class."""
    slug = getattr(detector, "slug", None)
    if not slug or slug == BaseDetector.slug:
        raise ValueError("Detector must define a unique slug")
    _DETECTOR_REGISTRY[slug] = detector
    return detector


def get(slug: str) -> Optional[Type[BaseDetector]]:
    return _DETECTOR_REGISTRY.get(slug)


def create(slug: str, *, config: Optional[dict] = None) -> BaseDetector:
    detector_cls = get(slug)
    if not detector_cls:
        raise KeyError(f"Detector '{slug}' is not registered")
    return detector_cls(config=config)


def all_detectors() -> Iterable[Type[BaseDetector]]:
    return _DETECTOR_REGISTRY.values()


def list_slugs() -> Iterable[str]:
    return _DETECTOR_REGISTRY.keys()


__all__ = [
    "register",
    "get",
    "create",
    "all_detectors",
    "list_slugs",
]
