"""Use case: enrich a login session with parsed device + geo facts.

Framework-free — depends only on ports. Driven by the Celery task
``identity.enrich_user_session`` (a thin worker adapter).

Idempotent: re-running overwrites the parsed fields and bumps
``enriched_at``. Geo lookup is skipped when the session has no IP, and a
``None`` geo result simply leaves the geo columns blank.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from components.identity.application.ports.geoip_port import GeoIPPort
from components.identity.application.ports.session_registry_port import SessionRegistryPort
from components.identity.application.ports.user_agent_parser_port import UserAgentParserPort


class EnrichSessionUseCase:
    """Parse a session's stored user agent + IP into structured columns."""

    def __init__(
        self,
        *,
        session_registry: SessionRegistryPort,
        user_agent_parser: UserAgentParserPort,
        geoip: GeoIPPort,
    ) -> None:
        self._sessions = session_registry
        self._ua_parser = user_agent_parser
        self._geoip = geoip

    def execute(self, session_id: UUID) -> str:
        """Returns a status string for task-level logging:
        ``enriched`` | ``session_missing`` | ``session_gone``.
        """
        record = self._sessions.get(session_id=session_id)
        if record is None:
            return "session_missing"

        device = self._ua_parser.parse(record.user_agent)
        geo = self._geoip.lookup(record.ip_address) if record.ip_address else None

        applied = self._sessions.apply_enrichment(
            session_id=session_id,
            device=device,
            geo=geo,
            enriched_at=datetime.now(UTC),
        )
        return "enriched" if applied else "session_gone"
