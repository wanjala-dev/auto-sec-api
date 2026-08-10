"""Throttle rates must be governed by settings, and prod rates must not drift.

THE DRIFT THIS EXISTS TO STOP
-----------------------------
``SimpleRateThrottle.__init__`` does::

    if not getattr(self, 'rate', None):
        self.rate = self.get_rate()      # <- reads DEFAULT_THROTTLE_RATES

so a ``rate`` class attribute **wins** and the settings lookup never runs. Every
identity throttle used to declare both a ``scope`` and a ``rate``, which made
``DEFAULT_THROTTLE_RATES`` authoritative-looking dead config: anyone tuning a
rate edited a setting that could not possibly take effect, and ``local.py``'s
dev-relief block — with a comment explaining exactly which caps it relaxes for
the QA E2E suite — relieved nothing for its entire existence.

That is a config-honesty hazard rather than an exploit, and it is precisely the
kind that produces a *false sense of control* in a security product: the number
an operator reads is not the number in force.

Three properties are asserted here:

1. **No identity throttle declares its own rate.** The moment one does, the
   settings entry beneath it goes dead again, silently.
2. **Effective production rates are frozen** against an explicit baseline —
   the exact values that were in force before they moved into settings. This is
   what makes "prod rates are unchanged" a checked claim rather than a promise,
   and it makes any future loosening a deliberate, reviewed edit to this file.
3. **local.py's dev-relief block references real scopes**, and every override
   is genuinely looser than the base rate. A typo'd scope name is the other way
   that block can silently do nothing.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest
from django.conf import settings
from rest_framework.throttling import SimpleRateThrottle

from components.identity.api import throttles as identity_throttles

pytestmark = pytest.mark.arch

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_SETTINGS = REPO_ROOT / "api" / "settings" / "local.py"

# The rates in force in PRODUCTION. Every `auth_*` / `otp_*` entry below was
# previously hardcoded on its throttle class; the values are copied verbatim,
# so moving them into settings changed nothing operationally.
#
# Changing a number here is a deliberate security decision. LOOSENING one needs
# a reason in the PR body; tightening is always safe to review.
EXPECTED_PRODUCTION_RATES = {
    # Identity-keyed (bounds an attack on ONE account — never a per-host limit)
    "auth_login": "10/min",
    "auth_password_reset_request": "5/hour",
    "auth_password_reset_confirm": "10/hour",
    "auth_email_verify": "15/hour",
    "auth_resend_verification": "3/hour",
    "auth_magic_link_request": "5/hour",
    "auth_magic_link_verify": "10/hour",
    # Per-principal (auth-gated endpoints)
    "otp_verify": "10/min",
    "otp_static_verify": "5/min",
    # Per-IP ceilings — the anti-spraying / anti-mail-bomb layer
    "auth_login_ip": "60/min",
    "auth_login_ip_sustained": "600/hour",
    "auth_email_send_ip": "40/hour",
    "auth_token_verify_ip": "60/hour",
    "auth_resend_verification_ip": "10/hour",
}


def _identity_throttle_classes():
    """Every concrete throttle class defined in identity's throttles module."""
    return [
        obj
        for _, obj in inspect.getmembers(identity_throttles, inspect.isclass)
        if issubclass(obj, SimpleRateThrottle)
        and obj.__module__ == identity_throttles.__name__
        and getattr(obj, "scope", None) is not None
    ]


IDENTITY_THROTTLES = sorted(_identity_throttle_classes(), key=lambda cls: cls.__name__)


def test_every_identity_throttle_was_discovered():
    """Guard the guard — a bad import would make the assertions below vacuous."""
    assert len(IDENTITY_THROTTLES) == len(EXPECTED_PRODUCTION_RATES), (
        f"Discovered {len(IDENTITY_THROTTLES)} identity throttles but "
        f"{len(EXPECTED_PRODUCTION_RATES)} baseline rates are declared. A new throttle needs its "
        "production rate recorded in EXPECTED_PRODUCTION_RATES (and in DEFAULT_THROTTLE_RATES); "
        "a removed one needs its entry deleted."
    )


@pytest.mark.parametrize("throttle_class", IDENTITY_THROTTLES, ids=lambda cls: cls.__name__)
def test_throttle_does_not_hardcode_its_rate(throttle_class):
    assert "rate" not in throttle_class.__dict__, (
        f"{throttle_class.__name__} declares `rate` on the class. SimpleRateThrottle only consults "
        "DEFAULT_THROTTLE_RATES when `rate` is falsy, so this silently makes the settings entry for "
        f"scope '{throttle_class.scope}' dead config — and kills local.py's dev-relief for it too. "
        "Delete the attribute and put the value in api/settings/base.py."
    )


@pytest.mark.parametrize("throttle_class", IDENTITY_THROTTLES, ids=lambda cls: cls.__name__)
def test_throttle_resolves_its_expected_production_rate(throttle_class):
    """The effective rate — what the throttle actually enforces at runtime."""
    scope = throttle_class.scope
    assert scope in EXPECTED_PRODUCTION_RATES, (
        f"{throttle_class.__name__} uses scope '{scope}', which has no recorded production baseline. "
        "Add it to EXPECTED_PRODUCTION_RATES so the rate cannot drift unreviewed."
    )

    # Instantiating is the honest check: it runs the same get_rate() path the
    # request cycle runs, and raises ImproperlyConfigured if the scope is
    # missing from settings entirely.
    assert throttle_class().rate == EXPECTED_PRODUCTION_RATES[scope], (
        f"{throttle_class.__name__} (scope '{scope}') now enforces {throttle_class().rate}, but the "
        f"reviewed production baseline is {EXPECTED_PRODUCTION_RATES[scope]}. If this loosening is "
        "intended, say so in the PR and update EXPECTED_PRODUCTION_RATES."
    )


def _local_dev_relief_overrides() -> dict[str, str]:
    """Read local.py's DEFAULT_THROTTLE_RATES override without importing it.

    Importing ``api.settings.local`` needs DATABASE_URL and friends, so the
    block is read statically instead — enough to prove its keys are real.
    """
    tree = ast.parse(LOCAL_SETTINGS.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and key.value == "DEFAULT_THROTTLE_RATES":
                return {
                    entry.value: rate.value
                    for entry, rate in zip(value.keys, value.values)
                    if isinstance(entry, ast.Constant) and isinstance(rate, ast.Constant)
                }
    raise AssertionError("No DEFAULT_THROTTLE_RATES override found in api/settings/local.py")


def test_local_dev_relief_block_is_not_a_no_op():
    """The block exists so the QA E2E suite stops eating spurious 429s.

    It spent its whole life doing nothing (Finding C). Now that the class-level
    rates are gone it works — but only for scopes that actually exist, so a
    typo would put it right back to doing nothing, silently.
    """
    overrides = _local_dev_relief_overrides()
    assert overrides, "local.py's dev-relief block is empty"

    base_rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
    unknown = sorted(scope for scope in overrides if scope not in base_rates)
    assert not unknown, (
        f"local.py relaxes throttle scopes that do not exist: {unknown}. Nothing reads them, so the "
        "relief silently does not happen — the exact failure mode this block already had once."
    )


def test_local_dev_relief_actually_relaxes_rather_than_tightens():
    """Relief that tightens a cap would be worse than none — it would look like relief."""
    overrides = _local_dev_relief_overrides()
    base_rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]

    def _per_second(rate: str) -> float:
        # Compare throughput, not the raw numerator — "1000/min" and "600/hour"
        # are not comparable by count alone.
        num_requests, duration = SimpleRateThrottle.parse_rate(None, rate)
        return num_requests / duration

    tightened = []
    for scope, dev_rate in overrides.items():
        if _per_second(dev_rate) <= _per_second(base_rates[scope]):
            tightened.append(f"{scope}: dev={dev_rate} vs base={base_rates[scope]}")

    assert not tightened, "local.py's dev-relief block does not relieve these scopes: " + "; ".join(tightened)
