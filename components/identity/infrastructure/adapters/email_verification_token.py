"""The email-confirmation token — deliberately NOT an access token.

Registration emails a confirmation link; ``VerifyEmailUseCase`` consumes the
token in it. This token used to be a plain
``rest_framework_simplejwt.tokens.AccessToken`` carrying the full
``ACCESS_TOKEN_LIFETIME`` (10 days in dev/local, 1 day in prod), which meant the
confirmation link WAS a login session: it authenticated every
``IsAuthenticated`` read and write in the product and the Channels WebSocket
handshake — on an account whose email was still unverified, i.e. an account
``LoginUseCase`` itself refuses ("Email is not verified"). The link was a side
door around the very gate it existed to close, and it travelled by plaintext
email through every relay and inbox on the way.

The fix is the structural one this codebase already proved on the login pre-auth
token (see ``otp_challenge_token.py``). SimpleJWT stamps ``token_type`` into
every token and ``Token.verify()`` rejects a token whose type doesn't match the
class decoding it; ``JWTAuthentication`` only decodes the classes listed in
``SIMPLE_JWT["AUTH_TOKEN_CLASSES"]`` — ``("...tokens.AccessToken",)`` in every
settings module here. Declaring a distinct ``token_type`` therefore makes this
token unusable as a credential **by construction**, everywhere, with no
allowlist to keep in sync.

Unlike the OTP challenge, nothing opts back IN: no authentication class accepts
this type. The only consumer is ``JWTTokenAdapter.decode_email_verification_token``,
which decodes it explicitly and checks the type — so a session token cannot
stand in for proof of inbox control either.

Do NOT give this class the ``access`` token type, and do not widen
``AUTH_TOKEN_CLASSES`` to include it — either change restores a full-privilege
credential to everyone's inbox.
"""

from __future__ import annotations

from datetime import timedelta

from rest_framework_simplejwt.tokens import Token

#: Wire-format value of the ``token_type`` claim. Anything that is not an access
#: token is rejected by the default authentication path.
EMAIL_VERIFICATION_TOKEN_TYPE = "email_verify"

#: A confirmation link sits in an inbox, so its lifetime is a real exposure
#: window — long enough that a user who reads mail tomorrow is not stranded
#: (``/identity/resend-verification/`` covers anyone slower), short enough that
#: the link is not a standing credential. Deliberately a constant here rather
#: than a read of ``ACCESS_TOKEN_LIFETIME``: coupling the two is what made the
#: emailed credential 10 days long.
EMAIL_VERIFICATION_TOKEN_LIFETIME = timedelta(hours=24)


class EmailVerificationToken(Token):
    """Single-purpose proof that the holder controls the account's inbox."""

    token_type = EMAIL_VERIFICATION_TOKEN_TYPE
    lifetime = EMAIL_VERIFICATION_TOKEN_LIFETIME
