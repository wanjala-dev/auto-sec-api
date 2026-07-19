"""Unit tests: session enrichment + self-serve session use cases (T2-S2/S3).

Pure application-layer tests through in-memory fakes — no DB, no Django.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

import pytest

from components.identity.application.ports.geoip_port import GeoIPPort, GeoLocation
from components.identity.application.ports.session_registry_port import SessionRegistryPort
from components.identity.application.ports.user_agent_parser_port import DeviceInfo, UserAgentParserPort
from components.identity.application.use_cases.enrich_session_use_case import EnrichSessionUseCase
from components.identity.application.use_cases.list_my_sessions_use_case import ListMySessionsUseCase
from components.identity.application.use_cases.revoke_other_sessions_use_case import RevokeOtherSessionsUseCase
from components.identity.application.use_cases.revoke_session_use_case import RevokeSessionUseCase
from components.identity.domain.errors import MissingSessionClaimError, SessionNotFoundError
from components.identity.domain.value_objects.auth_tokens import RequestContext
from components.identity.domain.value_objects.session_records import UserSessionRecord

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
_CONTEXT = RequestContext(ip_address="203.0.113.9", user_agent="pytest/1.0")

_DEVICE = DeviceInfo(
    device_type="desktop",
    browser="Chrome",
    browser_version="126.0",
    os="Mac OS X",
    os_version="10.15",
)


def _record(**overrides) -> UserSessionRecord:
    defaults = dict(  # noqa: C408 — kwargs shape mirrors the record constructor
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        refresh_jti="jti-" + uuid.uuid4().hex[:8],
        login_method="password",
        ip_address="203.0.113.9",
        user_agent="pytest-browser/1.0",
        device_type="",
        browser="",
        browser_version="",
        os="",
        os_version="",
        geo_city="",
        geo_country="",
        geo_country_code="",
        enriched_at=None,
        created_at=_NOW - timedelta(hours=1),
        last_seen_at=_NOW - timedelta(minutes=5),
        expires_at=_NOW + timedelta(days=30),
        revoked_at=None,
        revoked_reason="",
    )
    defaults.update(overrides)
    return UserSessionRecord(**defaults)


# ── Fakes ────────────────────────────────────────────────────────────


@dataclass
class FakeSessionRegistry(SessionRegistryPort):
    records: list[UserSessionRecord] = field(default_factory=list)
    enrichments: list[dict] = field(default_factory=list)
    revoked: list[tuple[str, str]] = field(default_factory=list)
    revoked_all: list[dict] = field(default_factory=list)

    def create_session(self, *, user_id, refresh_jti, expires_at, context, login_method):
        raise AssertionError("not used here")

    def touch(self, *, refresh_jti, min_interval_seconds=300):
        raise AssertionError("not used here")

    def revoke(self, *, refresh_jti, reason):
        self.revoked.append((refresh_jti, reason))
        self.records = [
            replace(r, revoked_at=_NOW, revoked_reason=reason) if r.refresh_jti == refresh_jti else r
            for r in self.records
        ]

    def revoke_all_for_user(self, *, user_id, reason, except_jti=None):
        victims = [
            r for r in self.records if r.user_id == user_id and r.revoked_at is None and r.refresh_jti != except_jti
        ]
        self.revoked_all.append({"user_id": user_id, "reason": reason, "except_jti": except_jti})
        self.records = [replace(r, revoked_at=_NOW, revoked_reason=reason) if r in victims else r for r in self.records]
        return len(victims)

    def get(self, *, session_id):
        return next((r for r in self.records if r.id == session_id), None)

    def get_for_user(self, *, user_id, session_id):
        return next((r for r in self.records if r.id == session_id and r.user_id == user_id), None)

    def list_for_user(self, *, user_id, limit=100):
        mine = [r for r in self.records if r.user_id == user_id]
        return sorted(mine, key=lambda r: r.last_seen_at, reverse=True)[:limit]

    def list_active_jtis_for_user(self, *, user_id, except_jti=None):
        return [
            r.refresh_jti
            for r in self.records
            if r.user_id == user_id and r.revoked_at is None and r.expires_at > _NOW and r.refresh_jti != except_jti
        ]

    def apply_enrichment(self, *, session_id, device, geo, enriched_at):
        if not any(r.id == session_id for r in self.records):
            return False
        self.enrichments.append({"session_id": session_id, "device": device, "geo": geo, "enriched_at": enriched_at})
        return True


class FakeUAParser(UserAgentParserPort):
    def __init__(self):
        self.seen: list[str] = []

    def parse(self, user_agent):
        self.seen.append(user_agent)
        return _DEVICE


class FakeGeoIP(GeoIPPort):
    def __init__(self, result: GeoLocation | None):
        self.result = result
        self.seen: list[str] = []

    def lookup(self, ip):
        self.seen.append(ip)
        return self.result


class FakeTokenRevocation:
    def __init__(self):
        self.jtis: list[str] = []

    def revoke_all_tokens(self, *, user_id):
        raise AssertionError("not used here")

    def revoke_token(self, *, token_string):
        raise AssertionError("not used here")

    def revoke_by_jti(self, *, jti):
        self.jtis.append(jti)
        return True


class FakeAudit:
    def __init__(self):
        self.events: list[dict] = []

    def record_event(self, **kwargs):
        self.events.append(kwargs)


# ── EnrichSessionUseCase ─────────────────────────────────────────────


class TestEnrichSessionUseCase:
    def _build(self, registry, geo=GeoLocation(city="Nairobi", country="Kenya", country_code="KE")):
        parser = FakeUAParser()
        geoip = FakeGeoIP(geo)
        return EnrichSessionUseCase(session_registry=registry, user_agent_parser=parser, geoip=geoip), parser, geoip

    def test_maps_device_and_geo_onto_session(self):
        record = _record()
        registry = FakeSessionRegistry(records=[record])
        use_case, parser, geoip = self._build(registry)

        assert use_case.execute(record.id) == "enriched"
        assert parser.seen == [record.user_agent]
        assert geoip.seen == [record.ip_address]
        (applied,) = registry.enrichments
        assert applied["device"] == _DEVICE
        assert applied["geo"] == GeoLocation(city="Nairobi", country="Kenya", country_code="KE")
        assert applied["enriched_at"] is not None

    def test_skips_geo_lookup_when_session_has_no_ip(self):
        record = _record(ip_address=None)
        registry = FakeSessionRegistry(records=[record])
        use_case, _parser, geoip = self._build(registry)

        assert use_case.execute(record.id) == "enriched"
        assert geoip.seen == []
        assert registry.enrichments[0]["geo"] is None

    def test_none_geo_result_still_enriches_device_facts(self):
        record = _record()
        registry = FakeSessionRegistry(records=[record])
        use_case, _parser, _geoip = self._build(registry, geo=None)

        assert use_case.execute(record.id) == "enriched"
        assert registry.enrichments[0]["geo"] is None
        assert registry.enrichments[0]["device"] == _DEVICE

    def test_missing_session_is_a_quiet_no_op(self):
        use_case, parser, _geoip = self._build(FakeSessionRegistry())
        assert use_case.execute(uuid.uuid4()) == "session_missing"
        assert parser.seen == []


# ── ListMySessionsUseCase ────────────────────────────────────────────


class TestListMySessionsUseCase:
    def test_marks_current_and_active_flags(self):
        user_id = uuid.uuid4()
        current = _record(user_id=user_id, refresh_jti="current-jti")
        revoked = _record(user_id=user_id, revoked_at=_NOW, revoked_reason="logout")
        expired = _record(user_id=user_id, expires_at=_NOW - timedelta(days=1))
        registry = FakeSessionRegistry(records=[current, revoked, expired])

        views = ListMySessionsUseCase(session_registry=registry).execute(user_id=user_id, current_sid="current-jti")

        by_id = {v.id: v for v in views}
        assert by_id[current.id].is_current is True
        assert by_id[current.id].is_active is True
        assert by_id[revoked.id].is_active is False
        assert by_id[expired.id].is_active is False
        assert sum(v.is_current for v in views) == 1

    def test_none_sid_marks_nothing_current(self):
        user_id = uuid.uuid4()
        registry = FakeSessionRegistry(records=[_record(user_id=user_id)])
        views = ListMySessionsUseCase(session_registry=registry).execute(user_id=user_id, current_sid=None)
        assert [v.is_current for v in views] == [False]


# ── RevokeSessionUseCase ─────────────────────────────────────────────


class TestRevokeSessionUseCase:
    def _build(self, registry):
        revocation = FakeTokenRevocation()
        audit = FakeAudit()
        use_case = RevokeSessionUseCase(session_registry=registry, token_revocation=revocation, audit_port=audit)
        return use_case, revocation, audit

    def test_revokes_blacklists_and_audits(self):
        record = _record()
        registry = FakeSessionRegistry(records=[record])
        use_case, revocation, audit = self._build(registry)

        assert use_case.execute(user_id=record.user_id, session_id=record.id, email="a@b.c", context=_CONTEXT) is True
        assert revocation.jtis == [record.refresh_jti]
        assert registry.revoked == [(record.refresh_jti, "user_revoked")]
        (event,) = audit.events
        assert event["event_code"] == "auth.session_revoked"
        assert event["metadata"]["session_jti"] == record.refresh_jti

    def test_unknown_or_foreign_session_raises_not_found(self):
        record = _record()
        use_case, _rev, _audit = self._build(FakeSessionRegistry(records=[record]))
        with pytest.raises(SessionNotFoundError):
            use_case.execute(user_id=uuid.uuid4(), session_id=record.id, email="a@b.c", context=_CONTEXT)

    def test_already_revoked_is_idempotent_no_op(self):
        record = _record(revoked_at=_NOW, revoked_reason="logout")
        registry = FakeSessionRegistry(records=[record])
        use_case, revocation, audit = self._build(registry)

        assert use_case.execute(user_id=record.user_id, session_id=record.id, email="a@b.c", context=_CONTEXT) is False
        assert revocation.jtis == []
        assert audit.events == []


# ── RevokeOtherSessionsUseCase ───────────────────────────────────────


class TestRevokeOtherSessionsUseCase:
    def test_revokes_everything_except_current(self):
        user_id = uuid.uuid4()
        current = _record(user_id=user_id, refresh_jti="current-jti")
        other_a = _record(user_id=user_id)
        other_b = _record(user_id=user_id)
        registry = FakeSessionRegistry(records=[current, other_a, other_b])
        revocation = FakeTokenRevocation()
        audit = FakeAudit()

        revoked = RevokeOtherSessionsUseCase(
            session_registry=registry, token_revocation=revocation, audit_port=audit
        ).execute(user_id=user_id, current_sid="current-jti", email="a@b.c", context=_CONTEXT)

        assert revoked == 2
        assert set(revocation.jtis) == {other_a.refresh_jti, other_b.refresh_jti}
        assert registry.revoked_all == [{"user_id": user_id, "reason": "user_revoked", "except_jti": "current-jti"}]
        (event,) = audit.events
        assert event["metadata"] == {"scope": "others", "revoked_count": 2, "session_jti": "current-jti"}

    def test_missing_sid_refuses(self):
        use_case = RevokeOtherSessionsUseCase(
            session_registry=FakeSessionRegistry(),
            token_revocation=FakeTokenRevocation(),
            audit_port=FakeAudit(),
        )
        with pytest.raises(MissingSessionClaimError):
            use_case.execute(user_id=uuid.uuid4(), current_sid=None, email="a@b.c", context=_CONTEXT)
