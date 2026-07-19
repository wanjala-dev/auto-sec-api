"""Resource DTO for workspace preference entities."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkspacePreferenceResource:
    """Output DTO for workspace preference endpoints.

    Represents workspace notification and financial report preferences.
    """
    id: int | None = None
    workspace: str | None = None
    settings: dict | None = None
    financial_report_frequency: str | None = None
    financial_report_interval_unit: str | None = None
    financial_report_interval_value: int | None = None
    donations: bool = False
    expenses: bool = False
    income: bool = False
    story: bool = False
    sources: bool = False
    team: bool = False
    budget: bool = False
    activities: bool = False
    gallery: bool = False
    comments: bool = False
    farming: bool = False
    sponsorship: bool = False
    payroll: bool = False
    fundraising: bool = False
    books_records: bool = False


@dataclass(frozen=True)
class WorkspacePreferenceCollectionResource:
    """Output DTO for workspace preference list endpoints.

    Represents a collection of workspace preferences.
    """
    items: list[WorkspacePreferenceResource] | None = None
    count: int = 0
