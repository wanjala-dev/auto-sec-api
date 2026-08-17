"""GitHub App authentication for the VCS integration (ADR 0010 D6 / Phase B).

The driven-side trust surface for app-mode connections. Four concerns, one module:

* **App JWT** — a 10-minute RS256 JWT minted from ``GITHUB_APP_ID`` +
  ``GITHUB_APP_PRIVATE_KEY`` (per GitHub's documented claims: ``iat`` backdated
  60s for clock drift, ``exp`` at the 10-minute maximum). Minted on demand and
  NEVER cached — it is a signing artifact, not a credential worth keeping.
* **Installation tokens** — the JWT is exchanged via
  ``POST /app/installations/{installation_id}/access_tokens`` for a 1-hour
  installation token, cached per installation for ~55 minutes (Django cache).
  A revoked/uninstalled installation surfaces as the typed
  :class:`GitHubAppInstallationRevokedError` so the connection layer can act
  (mark the row, never retry blindly).
* **Install-state signing** — the ``state`` param carried through GitHub's
  install redirect. ``django.signing`` over ``{workspace_id, user_id}`` with a
  dedicated salt + 15-minute max age; the SETUP endpoint trusts NOTHING else
  for workspace resolution (mass-assignment guard).
* **Webhook signature** — constant-time HMAC-SHA256 verification of
  ``X-Hub-Signature-256`` against ``GITHUB_APP_WEBHOOK_SECRET``.

Secrets discipline: the private key and webhook secret arrive via settings/env,
are read inside ``@sensitive_variables``-guarded functions, and never appear in
logs, errors, cache values, or exception state.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from urllib.parse import quote

import jwt as pyjwt
import requests
from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.views.decorators.debug import sensitive_variables

from components.integrations.application.ports.vcs_port import VcsApiError

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.github.com"
_TIMEOUT_SECONDS = 20
_API_VERSION = "2022-11-28"

#: Per GitHub docs: backdate ``iat`` 60s to protect against clock drift.
_JWT_IAT_DRIFT_SECONDS = 60
#: Per GitHub docs: ``exp`` may be at most 10 minutes in the future.
_JWT_TTL_SECONDS = 600

#: Installation tokens live 1 hour; cache for ~55 minutes so a token handed to
#: a caller always has >=5 minutes of life left. The JWT is never cached.
_INSTALLATION_TOKEN_TTL_SECONDS = 55 * 60
_TOKEN_CACHE_KEY = "integrations:github_app:installation_token:v1:{app_id}:{installation_id}"

#: Signed install-state: dedicated salt + short max age. The state is the ONLY
#: source of the workspace binding on the setup redirect.
_STATE_SALT = "integrations.github_app.install_state"
STATE_MAX_AGE_SECONDS = 15 * 60


class GitHubAppAuthError(VcsApiError):
    """GitHub App auth failed (config, network, or an unexpected API answer)."""


class GitHubAppNotConfiguredError(GitHubAppAuthError):
    """The deployment has no GitHub App credentials (settings are empty)."""


class GitHubAppInstallationRevokedError(GitHubAppAuthError):
    """The installation is gone or suspended — the customer revoked on GitHub.

    Raised on a 404 (uninstalled/deleted) or 403 (suspended) from the token
    exchange. The typed class is the contract the connection layer acts on:
    verify marks the row ERROR, the revocation-sync task disables it.
    """

    def __init__(self, message: str, *, installation_id: str, status_code: int | None = None, detail: str = ""):
        super().__init__(message, status_code=status_code, detail=detail)
        self.installation_id = installation_id


class InvalidInstallStateError(Exception):
    """The install ``state`` param failed validation. ``reason`` is
    ``"expired"`` (signature valid but past max age) or ``"invalid"``
    (missing/tampered/wrong shape) — the setup endpoint 4xxes on both."""

    def __init__(self, reason: str):
        super().__init__(f"GitHub App install state {reason}.")
        self.reason = reason


# ── App JWT ───────────────────────────────────────────────────────────────


def is_github_app_configured() -> bool:
    """True when the app id + private key are present (install/setup usable)."""
    return bool(
        str(getattr(settings, "GITHUB_APP_ID", "") or "").strip()
        and (getattr(settings, "GITHUB_APP_PRIVATE_KEY", "") or "").strip()
    )


@sensitive_variables("private_key")
def mint_app_jwt(now: int | None = None) -> str:
    """Mint the RS256 app JWT GitHub authenticates the *app* with.

    Claims per GitHub's docs: ``iat`` 60s in the past (clock drift), ``exp`` at
    the 10-minute maximum, ``iss`` = the app id / client id. Deliberately NOT
    cached — minting is cheap, and a cached signing artifact only widens the
    replay window for zero benefit.
    """
    app_id = str(getattr(settings, "GITHUB_APP_ID", "") or "").strip()
    private_key = (getattr(settings, "GITHUB_APP_PRIVATE_KEY", "") or "").strip()
    if not app_id or not private_key:
        raise GitHubAppNotConfiguredError(
            "GitHub App credentials are not configured (GITHUB_APP_ID / GITHUB_APP_PRIVATE_KEY).",
            status_code=None,
        )
    # A k8s secret often carries the PEM as one line with literal "\n" escapes;
    # normalize so PyJWT/cryptography can load it.
    if "\\n" in private_key and "\n" not in private_key:
        private_key = private_key.replace("\\n", "\n")

    issued_at = int(now if now is not None else time.time())
    payload = {
        "iat": issued_at - _JWT_IAT_DRIFT_SECONDS,
        "exp": issued_at + _JWT_TTL_SECONDS,
        "iss": app_id,
    }
    try:
        return pyjwt.encode(payload, private_key, algorithm="RS256")
    except Exception as exc:
        # A malformed key must surface as the typed config error, with no key
        # material in the message (PyJWT's own error text carries none).
        raise GitHubAppNotConfiguredError(
            "GITHUB_APP_PRIVATE_KEY could not be loaded as an RSA private key.",
            status_code=None,
        ) from exc


# ── Installation tokens ───────────────────────────────────────────────────


def _token_cache_key(installation_id: str) -> str:
    app_id = str(getattr(settings, "GITHUB_APP_ID", "") or "").strip()
    return _TOKEN_CACHE_KEY.format(app_id=app_id, installation_id=installation_id)


@sensitive_variables("app_jwt", "token")
def get_installation_token(installation_id: int | str, *, force_refresh: bool = False) -> str:
    """Return a live installation access token for ``installation_id``.

    Cache-first (per-installation key, ~55 min). On a miss: mint the app JWT,
    exchange it at ``POST /app/installations/{id}/access_tokens`` (the token
    lives 1 hour), cache the token — never the JWT. Raises
    :class:`GitHubAppInstallationRevokedError` when GitHub answers 404
    (uninstalled) or 403 (suspended), :class:`GitHubAppNotConfiguredError` when
    the app credentials are absent, :class:`GitHubAppAuthError` otherwise.
    """
    iid = str(installation_id or "").strip()
    if not iid:
        raise GitHubAppAuthError("An installation id is required to mint an installation token.", status_code=None)

    cache_key = _token_cache_key(iid)
    if not force_refresh:
        token = cache.get(cache_key)
        if token:
            return token

    app_jwt = mint_app_jwt()
    url = f"{_BASE_URL}/app/installations/{iid}/access_tokens"
    try:
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": _API_VERSION,
            },
            timeout=_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logger.exception("github_app_token_exchange_failed installation_id=%s", iid)
        raise GitHubAppAuthError(f"GitHub App token exchange failed for installation {iid}.", status_code=None) from exc

    if response.status_code in (403, 404):
        # 404 = the installation is gone (customer uninstalled the app);
        # 403 = the installation is suspended. Both mean "this consent was
        # revoked on GitHub" — the typed error lets the connection layer act.
        logger.warning("github_app_installation_revoked installation_id=%s status=%s", iid, response.status_code)
        raise GitHubAppInstallationRevokedError(
            f"GitHub App installation {iid} is revoked or suspended on GitHub.",
            installation_id=iid,
            status_code=response.status_code,
            detail=(response.text or "")[:300],
        )
    if response.status_code >= 300:
        logger.error("github_app_token_exchange_error installation_id=%s status=%s", iid, response.status_code)
        raise GitHubAppAuthError(
            f"GitHub App token exchange for installation {iid} returned {response.status_code}.",
            status_code=response.status_code,
            detail=(response.text or "")[:300],
        )

    token = str((response.json() or {}).get("token") or "")
    if not token:
        raise GitHubAppAuthError(f"GitHub returned no token for installation {iid}.", status_code=response.status_code)
    cache.set(cache_key, token, _INSTALLATION_TOKEN_TTL_SECONDS)
    return token


def invalidate_installation_token(installation_id: int | str) -> None:
    """Drop the cached token for an installation (revocation/repo-removal sync)."""
    iid = str(installation_id or "").strip()
    if iid:
        cache.delete(_token_cache_key(iid))


# ── Install-state signing ─────────────────────────────────────────────────


def sign_install_state(*, workspace_id: str, user_id: str) -> str:
    """Sign ``{workspace_id, user_id}`` into the install ``state`` param."""
    return signing.dumps({"workspace_id": str(workspace_id), "user_id": str(user_id)}, salt=_STATE_SALT)


def unsign_install_state(state: str, *, max_age: int = STATE_MAX_AGE_SECONDS) -> dict:
    """Validate + decode the install ``state``. Raises
    :class:`InvalidInstallStateError` (``expired`` / ``invalid``) — the setup
    endpoint maps both to a 4xx and binds nothing."""
    try:
        payload = signing.loads(state or "", salt=_STATE_SALT, max_age=max_age)
    except signing.SignatureExpired as exc:
        raise InvalidInstallStateError("expired") from exc
    except signing.BadSignature as exc:
        raise InvalidInstallStateError("invalid") from exc
    workspace_id = str((payload or {}).get("workspace_id") or "")
    user_id = str((payload or {}).get("user_id") or "")
    if not workspace_id or not user_id:
        raise InvalidInstallStateError("invalid")
    return {"workspace_id": workspace_id, "user_id": user_id}


def build_install_url(state: str) -> str:
    """The GitHub install URL for our app, carrying the signed state.

    GitHub passes ``state`` through the install flow back to the app's Setup
    URL together with ``installation_id`` + ``setup_action``.
    """
    slug = str(getattr(settings, "GITHUB_APP_SLUG", "") or "").strip()
    if not slug:
        raise GitHubAppNotConfiguredError(
            "GITHUB_APP_SLUG is not configured — register the app first.", status_code=None
        )
    return f"https://github.com/apps/{quote(slug)}/installations/new?state={quote(state or '')}"


# ── Webhook signature ─────────────────────────────────────────────────────


def is_webhook_secret_configured() -> bool:
    return bool((getattr(settings, "GITHUB_APP_WEBHOOK_SECRET", "") or "").strip())


@sensitive_variables("secret", "digest")
def verify_webhook_signature(raw_body: bytes, signature_header: str | None) -> bool:
    """Constant-time verification of ``X-Hub-Signature-256`` over the raw body.

    Fail closed: a missing secret, missing header, or non-``sha256=`` shape is
    ``False`` — the receiver 401s without ever parsing the body.
    """
    secret = (getattr(settings, "GITHUB_APP_WEBHOOK_SECRET", "") or "").strip()
    provided = (signature_header or "").strip()
    if not secret or not provided.startswith("sha256="):
        return False
    digest = hmac.new(secret.encode("utf-8"), raw_body or b"", hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={digest}", provided)
