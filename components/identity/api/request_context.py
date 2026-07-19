"""Request → RequestContext extraction for the identity controllers.

Single place that knows how to pull the client IP and user agent out of a
Django/DRF request. Behind nginx + CloudFront, ``X-Forwarded-For`` is a
comma-separated hop list — the ORIGINAL client is the FIRST entry. The old
inline constructions stored the whole raw header, which both corrupted the
value (not a single IP) and broke ``GenericIPAddressField`` persistence.
"""

from __future__ import annotations

from components.identity.domain.value_objects.auth_tokens import RequestContext


def extract_client_ip(request) -> str | None:
    """First X-Forwarded-For hop, falling back to REMOTE_ADDR."""
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR") or ""
    first_hop = forwarded_for.split(",")[0].strip()
    if first_hop:
        return first_hop
    return request.META.get("REMOTE_ADDR") or None


def build_request_context(request) -> RequestContext:
    """Build the audit/session RequestContext for this request."""
    return RequestContext(
        ip_address=extract_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "") or "",
    )
