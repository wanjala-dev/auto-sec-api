"""Invited user registration adapter.

Extracted from ``components.team.infrastructure.adapters.team_invited_user_registration_adapter``.
Implements InvitedUserRegistrationPort.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.sites.shortcuts import get_current_site
from django.utils import timezone

from components.shared_platform.application.facades.core_utils_facade import send_email
from infrastructure.persistence.users.models import CustomUser
from infrastructure.persistence.workspaces.models import Workspace
from components.workspace.infrastructure.adapters.password_setup_url_builder import (
    build_password_setup_url,
)


class InvitedUserRegistrationAdapter:
    def register_or_get_invited_user(
        self,
        *,
        email: str,
        name: str,
        workspace_id,
        team_name: str,
        request=None,
        site_domain: str | None = None,
    ):
        user = CustomUser.objects.filter(email=email).first()
        if user:
            return user

        user = CustomUser.objects.create_user(username=name, email=email, password=None)
        user.is_verified = True
        user.is_onboard_complete = True
        user.auth_provider = "email"
        user.set_unusable_password()
        user.save(
            update_fields=[
                "is_verified",
                "is_onboard_complete",
                "auth_provider",
                "password",
                "updated_at",
            ]
        )

        current_site = get_current_site(request) if request is not None else (site_domain or "")
        site_full_name = current_site
        workspace_name = Workspace.objects.get(id=workspace_id).workspace_name
        password_setup_url = build_password_setup_url(
            user=user,
            request=request,
            site_domain=site_domain,
        )

        send_email(
            email,
            settings.EMAIL_HOST_USER or settings.DEFAULT_FROM_EMAIL,
            f"Welcome to {site_full_name}. Set your password",
            """Hello {},

    Welcome to {}! Thank you for your donation. Your account has been created, and you can finish setting it up by choosing a password at the link below:

    {}

    This link lets you securely set your own password—no temporary passwords to copy over.

    Thank you for joining our platform!

    Best regards,
    The {} Team
    """.format(name, site_full_name, password_setup_url, site_full_name),
            "team/team_register_invited_user.html",
            {
                "workspace_name": workspace_name,
                "name": name,
                "site_full_name": site_full_name,
                "team_name": team_name,
                "password_setup_url": password_setup_url,
                "current_year": timezone.now().year,
            },
        )

        return user
