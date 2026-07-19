"""Resolve the platform's own AWS account id (settings/env — never hardcoded).

This is the ONLY principal a customer's audit role trusts, so an unset or
malformed value must fail loudly: a role trusting a wrong/nonexistent
account is a silent onboarding break.
"""

from __future__ import annotations

import os


def resolve_vendor_account_id() -> str:
    from django.conf import settings

    acct = getattr(settings, "AUTOSEC_VENDOR_AWS_ACCOUNT_ID", "") or os.environ.get("AUTOSEC_VENDOR_AWS_ACCOUNT_ID", "")
    if not (acct.isdigit() and len(acct) == 12):
        # NEVER emit a placeholder into a customer trust policy.
        raise RuntimeError(
            "AUTOSEC_VENDOR_AWS_ACCOUNT_ID is not configured — set the "
            "platform's AWS account id before generating onboarding templates."
        )
    return acct
