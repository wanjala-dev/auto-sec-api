"""Output DTO for the agent-telemetry ingest endpoint.

Counts only. The response deliberately echoes nothing that was observed — no
agent identity, no resource, no attribute value — so the endpoint can never be
used as a read-back oracle for another tenant's telemetry, and so a caller that
logs our response does not thereby log the customer's estate.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentTelemetryIngestResource:
    accepted: int
    duplicates: int
    rejected_not_allowlisted: int
    skipped: int
    actors_created: int
    resources_created: int
    skip_reasons: dict

    @classmethod
    def from_result(cls, result) -> AgentTelemetryIngestResource:
        return cls(
            accepted=result.accepted,
            duplicates=result.duplicates,
            rejected_not_allowlisted=result.rejected_not_allowlisted,
            skipped=result.skipped,
            actors_created=result.actors_created,
            resources_created=result.resources_created,
            skip_reasons=dict(result.skip_reasons or {}),
        )

    def to_dict(self) -> dict:
        return {
            "accepted": self.accepted,
            "duplicates": self.duplicates,
            "rejected_not_allowlisted": self.rejected_not_allowlisted,
            "skipped": self.skipped,
            "actors_created": self.actors_created,
            "resources_created": self.resources_created,
            "skip_reasons": self.skip_reasons,
        }
