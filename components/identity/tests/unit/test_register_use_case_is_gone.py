"""``RegisterUserUseCase`` is deleted, and the one verification-link minter stays one.

The use case built the email-confirmation link out of a plain access token::

    token_pair = self._tokens.issue_tokens(user.id, ..., include_refresh=False)
    verification_url = f"{command.confirmation_base_url}?token={token_pair.access}"

That is precisely the defect #418 fixed on the live path — a confirmation link
that was a full-privilege session, ten days long on dev/local, travelling by
plaintext email and then sitting in an inbox.

It had no caller. ``RegisterView`` creates the user through ``RegisterSerializer``
and then calls ``IdentityService.queue_verification_email``, which runs
``SendVerificationEmailUseCase`` — the same three steps, done correctly, minting
through ``TokenPort.issue_email_verification_token``. So the choice was between
converting a second copy nothing exercises and removing it. It was removed: an
unexercised scoped-token conversion is a pattern nobody would have noticed
rotting, and this repo keeps one canonical way per concern.

``include_refresh=False`` was its parting gift too — it was the last production
call site of the flag that mints an access token with no ``sid``, the credential
``SessionAwareJWTAuthentication`` now correctly refuses.
"""

from __future__ import annotations

import importlib

import pytest


class TestRegisterUseCaseIsDeleted:
    @pytest.mark.parametrize(
        "module_path",
        [
            "components.identity.application.use_cases.register_user_use_case",
            "components.identity.application.commands.register_command",
        ],
    )
    def test_module_is_gone(self, module_path):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(module_path)

    def test_provider_no_longer_builds_it(self):
        from components.identity.application.providers.identity_provider import (
            IdentityProvider,
        )

        assert not hasattr(IdentityProvider, "build_register_user_use_case")

    def test_service_no_longer_exposes_it(self):
        from components.identity.application.service import IdentityService

        assert not hasattr(IdentityService, "register_user")


class TestVerificationLinksAreMintedScoped:
    """Whatever remains must use the scoped token, not a session credential."""

    def test_send_verification_email_use_case_mints_the_scoped_token(self):
        import inspect

        from components.identity.application.use_cases.send_verification_email_use_case import (
            SendVerificationEmailUseCase,
        )

        source = inspect.getsource(SendVerificationEmailUseCase.execute)
        assert "issue_email_verification_token" in source
        assert "issue_tokens" not in source
