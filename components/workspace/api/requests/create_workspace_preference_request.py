"""Request DTO for workspace preference endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreateWorkspacePreferenceRequest:
    """Input DTO for POST /workspaces/preferences/ endpoint.

    Handles workspace preference creation with notification and financial report settings.
    """
    workspace: str
    settings: dict | None = None
    financial_report_frequency: str | None = None
    financial_report_interval_unit: str | None = None
    financial_report_interval_value: int | None = None
    donations: bool | None = None
    expenses: bool | None = None
    income: bool | None = None
    story: bool | None = None
    sources: bool | None = None
    team: bool | None = None
    budget: bool | None = None
    activities: bool | None = None
    gallery: bool | None = None
    comments: bool | None = None
    farming: bool | None = None
    sponsorship: bool | None = None
    payroll: bool | None = None
    fundraising: bool | None = None
    books_records: bool | None = None
