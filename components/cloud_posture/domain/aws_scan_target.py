"""Validate an AWS scan target (account id + regions) before it reaches the scan command.

Security gate — the container-security sibling of ``image_reference.py``. The regions are
interpolated into the Prowler scan command, so they MUST be strictly validated: only real AWS
region tokens, nothing that could break out of the argument. The account id never enters the
command (Prowler scans whatever the assumed credentials belong to; the id is only a label on the
ingested findings), but it is validated too as defense in depth.
"""

from __future__ import annotations

import re

# 12-digit AWS account id.
_ACCOUNT_RE = re.compile(r"^\d{12}$")
# AWS region tokens: us-east-1, ap-southeast-2, us-gov-west-1, eu-central-1, … (2+ segments + N).
_REGION_RE = re.compile(r"^[a-z]{2}(?:-[a-z]+)+-\d{1,2}$")


class InvalidAwsScanTargetError(ValueError):
    """The AWS account id or one of the regions is malformed."""


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
