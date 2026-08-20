"""Fitness function: one place mints a session, and it stamps the ``sid``.

``SessionAwareJWTAuthentication`` (#427) fails closed — an access token with no
``sid`` claim, or a ``sid`` with no live ``UserSession`` row, is rejected. That
turns every alternative mint path into a trap rather than a shortcut: a bare
``RefreshToken.for_user(user)`` still produces a structurally valid,
correctly-signed pair, so it reviews clean and tests green right up until a real
client presents it and gets a 401 it cannot explain.

Three call sites had already grown that way and each was found by hand, one
incident at a time: ``VerifyEmailUseCase``, the invite-accept adapter (both
#427), and ``JoinRegisterController``, which was only ever harmless because it
500'd on an unrelated ``ImportError`` first. This test is the check that finds
the fourth.

Identity's token adapters are the sole permitted minters — that is where the
``sid`` claim is stamped, and where the deliberately powerless scoped classes
live. Everything else goes through the identity token port and registers a
``UserSession`` alongside the mint; see
``components/team/infrastructure/adapters/invite_token_adapter.py`` for the
shape to copy.

Writing it as a rule rather than a fourth manual review is the whole point: the
first three were each found only after they had shipped.

The rule covers production code only. Tests legitimately mint bare tokens to
prove the fail-closed behaviour itself.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SCANNED_ROOTS = ("components", "infrastructure", "api")

#: Identity's token adapters are the only place a SimpleJWT token is minted:
#: ``user_utils.issue_tokens`` is where the ``sid`` claim is stamped, and
#: ``jwt_token_adapter`` is the ``TokenPort`` implementation behind it (plus the
#: scoped, deliberately powerless ``EmailVerificationToken`` /
#: ``OtpChallengeToken``). Everything else asks the port.
TOKEN_ADAPTER_DIR = Path("components/identity/infrastructure/adapters")

#: KNOWN, UNFIXED, and deliberately listed rather than silently tolerated.
#:
#: ``infrastructure/api/mcp/views.py::_get_auto_token`` mints a bare
#: ``AccessToken.for_user`` for the MCP proxy's service account. Since #427 that
#: token authenticates nothing — it carries no ``sid``, so every call it signs
#: gets a 401 it cannot explain. It is dormant, not live: the path is gated on
#: ``MCP_AUTO_TOKEN_USER_EMAIL``, which defaults to "" and is set nowhere in the
#: repo or in auto-sec-infra. Fixing it is a design question this list is not the
#: place to answer — a service account needs either a registered session or a
#: token class that is not an access token — so it is named here so the next
#: person meets it on purpose. Do not add entries to make a failure go away.
KNOWN_UNREGISTERED_MINTERS = {
    Path("infrastructure/api/mcp/views.py"),
}


def _production_python_files() -> list[Path]:
    files: list[Path] = []
    for root_name in SCANNED_ROOTS:
        for path in sorted((ROOT / root_name).rglob("*.py")):
            parts = path.relative_to(ROOT).parts
            if "tests" in parts or "migrations" in parts:
                continue
            files.append(path)
    return files


def _calls_token_for_user(path: Path) -> bool:
    """True when the module actually CALLS ``<something>.for_user(...)``.

    Parsed rather than grepped so the prose in a docstring explaining why not to
    do this does not itself trip the rule.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "for_user":
            return True
    return False


def test_only_identitys_token_adapters_mint_a_jwt():
    offenders = []
    for path in _production_python_files():
        relative = path.relative_to(ROOT)
        if TOKEN_ADAPTER_DIR in relative.parents:
            continue
        if relative in KNOWN_UNREGISTERED_MINTERS:
            continue
        if _calls_token_for_user(path):
            offenders.append(str(relative))

    assert offenders == [], (
        "these modules mint a SimpleJWT token directly. A token minted outside "
        "identity's token adapters carries no `sid` claim and registers no "
        "UserSession, so SessionAwareJWTAuthentication rejects it on the next "
        "request and no revocation surface can ever reach it. Issue through "
        "IdentityProvider.build_token_adapter().issue_tokens(...) and register "
        "the session (see team/infrastructure/adapters/invite_token_adapter.py): "
        f"{offenders}"
    )


def test_the_known_offender_list_stays_honest():
    """An entry that no longer offends is a stale exemption — delete it."""
    stale = [str(relative) for relative in KNOWN_UNREGISTERED_MINTERS if not _calls_token_for_user(ROOT / relative)]

    assert stale == [], f"these exemptions are no longer needed and must be removed: {stale}"


def test_no_production_module_puts_a_session_token_in_a_link():
    """#418: a ``?token=`` URL built where session tokens are minted.

    The confirmation link was an ``AccessToken`` — the same credential
    ``/identity/login/`` hands out — mailed in plaintext and then resident in an
    inbox. Emailed links carry single-purpose scoped tokens
    (``issue_email_verification_token``, ``issue_preauth_token``); a module that
    both calls ``issue_tokens`` and formats a ``?token=`` URL is that defect
    reappearing.
    """
    offenders = []
    for path in _production_python_files():
        source = path.read_text()
        if "?token=" in source and "issue_tokens(" in source:
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == [], (
        "these modules build a `?token=` URL alongside a session-token mint — a "
        "link is not a session; mint a scoped single-purpose token instead "
        f"(see identity/infrastructure/adapters/email_verification_token.py): {offenders}"
    )
