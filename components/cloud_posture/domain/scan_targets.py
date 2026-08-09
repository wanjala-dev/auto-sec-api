"""Validate a posture scan target before it reaches the scan command (ADR 0021 D1/D3).

Security gate — the provider-keyed sibling of ``image_reference.py``. One validator per
posture provider; the ``PostureProvider`` registry dispatches to the right one, so no
unvalidated token ever reaches the interpolated scan command (or the engine's env).

AWS: the regions are interpolated into the Prowler scan command, so they MUST be strictly
validated — only real AWS region tokens, nothing that could break out of the argument. The
account id never enters the command (Prowler scans whatever the assumed credentials belong
to; the id is only a label on the ingested findings), but it is validated too as defense in
depth. (Moved verbatim from ``aws_scan_target.py`` in ADR 0021 P0a.)

Vercel: the team is passed via the ``VERCEL_TEAM`` env var (never argv) and later
interpolated into API URLs by verify(), so it is held to the same strictness — only a
well-formed team id (``team_…``) or a conservative slug is admitted. A blank team is
REJECTED: an unpinned token makes Prowler auto-discover and scan every team the token's
user belongs to, which violates the per-team consent model (ADR 0021 D3).
"""

from __future__ import annotations

import re

# 12-digit AWS account id.
_ACCOUNT_RE = re.compile(r"^\d{12}$")
# AWS region tokens: us-east-1, ap-southeast-2, us-gov-west-1, eu-central-1, … (2+ segments + N).
_REGION_RE = re.compile(r"^[a-z]{2}(?:-[a-z]+)+-\d{1,2}$")
# Vercel team id ("team_" + opaque token) or a conservative team slug (ADR 0021 D3).
_VERCEL_TEAM_ID_RE = re.compile(r"^team_[A-Za-z0-9]{1,64}$")
_VERCEL_TEAM_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


class InvalidAwsScanTargetError(ValueError):
    """The AWS account id or one of the regions is malformed."""


class InvalidVercelScanTargetError(ValueError):
    """The Vercel team id/slug is missing or malformed."""


def validate_aws_scan_target(account_id: str | None, regions) -> tuple[str, list[str]]:
    """Return ``(account_id, [regions])`` if every part is a well-formed AWS token, else raise.

    Empty account id / empty regions are allowed (Prowler defaults to the creds' account and all
    enabled regions). Any region that isn't a strict AWS region token is rejected — that is what
    makes interpolating it into the scan command safe.
    """
    account = (account_id or "").strip()
    if account and not _ACCOUNT_RE.match(account):
        raise InvalidAwsScanTargetError(f"invalid AWS account id: {account!r}")

    validated: list[str] = []
    for region in regions or []:
        token = str(region).strip()
        if not _REGION_RE.match(token):
            raise InvalidAwsScanTargetError(f"invalid AWS region: {region!r}")
        validated.append(token)
    return account, validated


def validate_vercel_scan_target(team: str | None) -> str:
    """Return the team id/slug if well-formed, else raise.

    Unlike AWS, an EMPTY team is invalid: Prowler's no-team default auto-discovers and
    scans every team the token's user belongs to — a consent violation in our model
    (the connection names ONE team; we scan exactly it — ADR 0021 D3).
    """
    token = (team or "").strip()
    if not token:
        raise InvalidVercelScanTargetError(
            "a Vercel scan requires a team id or slug — scanning without a pinned team is not allowed"
        )
    if _VERCEL_TEAM_ID_RE.match(token) or _VERCEL_TEAM_SLUG_RE.match(token):
        return token
    raise InvalidVercelScanTargetError(f"invalid Vercel team id/slug: {team!r}")
