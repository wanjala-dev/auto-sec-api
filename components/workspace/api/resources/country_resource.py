"""Resource DTO for country entities."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CountryResource:
    """Output DTO for country detail endpoints.

    Represents a country available for workspace assignment.
    """
    name: str | None = None


@dataclass(frozen=True)
class CountryCollectionResource:
    """Output DTO for country list endpoints.

    Represents a collection of countries.
    """
    items: list[CountryResource] | None = None
    count: int = 0
