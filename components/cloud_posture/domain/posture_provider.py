"""PostureProvider — the provider axis of the cloud-posture pillar (ADR 0021 D1).

The pillar's engine (Prowler) supports many providers; today we run two: ``aws`` and
``vercel``. The provider is a **first-class value in the scan/ingest contract** — the
argv word, the finding/scan ``source`` string, the target validator (the injection
gate), the credential envelope → engine env mapping, and the fingerprint's identity
key all come from the ONE registry entry here. This makes the "just change the word
aws to vercel" shortcut structurally unwritable: a Vercel finding can no longer be
minted with an ``aws:``-namespaced URN, which would silently corrupt dedupe, graph
joins, and attack-path correlation on the CNAPP spine (ADR 0004 D4).

**Source-string asymmetry, decided deliberately (ADR 0021 D1):** AWS KEEPS
``cloud_posture.prowler`` unchanged; Vercel gets ``cloud_posture.prowler.vercel``.
Renaming the AWS source to ``…prowler.aws`` would look tidier, but the SSOT's finding
identity is ``(workspace, source, fingerprint)`` — a rename would orphan every
existing AWS finding and re-mint them as new (broken lifecycle, duplicate cards).
Byte-for-byte preservation beats symmetry. Do NOT "fix" this later.

Deliberately NOT in the shared kernel: which argv word / validator / env vars an
engine needs is pillar mechanics, not cross-context vocabulary (``AssetUrn`` already
takes the provider as a free string).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from components.cloud_posture.domain.entities.posture_finding_entity import NormalizedPostureFinding
from components.cloud_posture.domain.scan_targets import (
    validate_aws_scan_target,
    validate_vercel_scan_target,
)


class UnknownPostureProviderError(ValueError):
    """The requested posture provider is not registered (fail closed)."""


@dataclass(frozen=True)
class PostureProvider:
    """One posture provider — the value object threaded through scanner → ingest → URN.

    ``token`` is both the engine argv word (``prowler {token} …``) and the URN
    namespace (``AssetUrn.canonical(token, ref)``); ``source`` is the
    ``NormalizedFinding`` / ``ScanCompleted`` / ``ScanJobSpec`` source string.
    """

    token: str
    source: str
    # (identifier, params) -> (validated identifier, extra CLI flags). The injection
    # gate: only strictly-validated tokens may reach the interpolated scan command.
    validate_target: Callable[[str, Mapping], tuple[str, str]]
    # (credential envelope, validated identifier) -> the engine's secret env vars.
    credential_env: Callable[[Mapping | None, str], dict[str, str]]
    # OCSF-parsed finding -> the fingerprint's account-shaped middle key
    # (AWS: the account id; Vercel: the team id — both ride OCSF cloud.account.uid).
    identity_key: Callable[[NormalizedPostureFinding], str]
    # Provider-specific extra attribute keys for the normalized finding ({} for AWS —
    # its attribute dict is locked byte-for-byte by the golden-master test).
    extra_attributes: Callable[[NormalizedPostureFinding], dict[str, str]]
    # Engine container memory override (a k8s quantity string), or None for the
    # backend default. Only AWS needs the bump: Prowler accumulates a whole
    # account's findings in-memory across regions; a Vercel team (26 checks x
    # projects) fits the 2Gi default comfortably (ADR 0021 D3).
    memory_limit: str | None = None


# ── AWS ──────────────────────────────────────────────────────────────────────


def _aws_validate_target(identifier: str, params: Mapping) -> tuple[str, str]:
    account, regions = validate_aws_scan_target(identifier, params.get("regions"))
    region_flag = f"--region {' '.join(regions)}" if regions else ""
    return account, region_flag


def _aws_credential_env(credentials: Mapping | None, _identifier: str) -> dict[str, str]:
    if not credentials:
        return {}
    out: dict[str, str] = {}
    if credentials.get("AccessKeyId"):
        out["AWS_ACCESS_KEY_ID"] = credentials["AccessKeyId"]
    if credentials.get("SecretAccessKey"):
        out["AWS_SECRET_ACCESS_KEY"] = credentials["SecretAccessKey"]
    if credentials.get("SessionToken"):
        out["AWS_SESSION_TOKEN"] = credentials["SessionToken"]
    return out


# ── Vercel ───────────────────────────────────────────────────────────────────


def _vercel_validate_target(identifier: str, _params: Mapping) -> tuple[str, str]:
    # The team never enters argv (it rides the VERCEL_TEAM env var) — no extra flags.
    return validate_vercel_scan_target(identifier), ""


def _vercel_credential_env(credentials: Mapping | None, identifier: str) -> dict[str, str]:
    """Vercel bearer token + the ALWAYS-pinned team (ADR 0021 D3 consent rule).

    ``VERCEL_TEAM`` is set unconditionally from the validated identifier: without it
    Prowler auto-discovers and scans EVERY team the token's user belongs to — a
    consent violation. A missing token fails fast and loud rather than letting the
    engine burn a Job to discover it.
    """
    token = (credentials or {}).get("token") or ""
    if not token:
        raise ValueError("a Vercel scan requires a token credential")
    return {"VERCEL_TOKEN": token, "VERCEL_TEAM": identifier}


def _vercel_extra_attributes(finding: NormalizedPostureFinding) -> dict[str, str]:
    # The team id is the AWS account-id analog (OCSF cloud.account.uid — verified
    # against the pinned engine's 5.36.0 output mapping). Carried under its honest
    # name so the board card / HUD never have to know the OCSF aliasing.
    return {"team_id": finding.account_id}


# ── Registry ─────────────────────────────────────────────────────────────────

AWS_POSTURE_PROVIDER = PostureProvider(
    token="aws",
    source="cloud_posture.prowler",  # unchanged — see the asymmetry note in the module docstring
    validate_target=_aws_validate_target,
    credential_env=_aws_credential_env,
    identity_key=lambda finding: finding.account_id,
    extra_attributes=lambda finding: {},
    memory_limit="4Gi",  # 2Gi default OOMKills a full account scan → 0 findings, silent
)

VERCEL_POSTURE_PROVIDER = PostureProvider(
    token="vercel",
    source="cloud_posture.prowler.vercel",
    validate_target=_vercel_validate_target,
    credential_env=_vercel_credential_env,
    identity_key=lambda finding: finding.account_id,  # = the team id (OCSF cloud.account.uid)
    extra_attributes=_vercel_extra_attributes,
    memory_limit=None,  # a team estate fits the backend's 2Gi default (ADR 0021 D3)
)

_PROVIDERS: dict[str, PostureProvider] = {
    provider.token: provider for provider in (AWS_POSTURE_PROVIDER, VERCEL_POSTURE_PROVIDER)
}


def resolve_posture_provider(token: str | None) -> PostureProvider:
    """Resolve a provider by token; ``None``/blank defaults to AWS (the pillar's
    first provider — every pre-ADR-0021 caller carries no provider param). An
    unknown token fails closed."""
    cleaned = (token or "").strip().lower()
    if not cleaned:
        return AWS_POSTURE_PROVIDER
    try:
        return _PROVIDERS[cleaned]
    except KeyError as exc:
        raise UnknownPostureProviderError(f"no posture provider registered for {token!r}") from exc
