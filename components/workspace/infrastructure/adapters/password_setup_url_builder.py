from __future__ import annotations

from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.contrib.sites.shortcuts import get_current_site
from django.utils.encoding import smart_bytes
from django.utils.http import urlsafe_base64_encode

from components.shared_platform.application.facades.core_utils_facade import resolve_frontend_base_url


def build_password_setup_url(*, user, request=None, site_domain: str | None = None) -> str:
    uidb64 = urlsafe_base64_encode(smart_bytes(user.id))
    token = PasswordResetTokenGenerator().make_token(user)
    current_site = get_current_site(request) if request is not None else None
    resolved_site_domain = site_domain
    if resolved_site_domain is None:
        resolved_site_domain = getattr(current_site, "domain", str(current_site)) if current_site else ""
    base = resolve_frontend_base_url(site_domain=resolved_site_domain, request=request)
    relative_path = f"/PasswordResetConfirm/{uidb64}/{token}/"
    return f"{base}{relative_path}"
