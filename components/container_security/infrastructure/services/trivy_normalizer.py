"""Parse Trivy JSON → the shared ``NormalizedFinding`` shape (ADR 0006 D4).

Trivy does NOT emit OCSF (Prowler does), so this maps its native ``Results[].
Vulnerabilities[]`` directly. SCA specifics (CVE id, package, installed/fixed version)
ride in ``attributes`` — the OCSF "unmapped" bag — so a container CVE and a CSPM
misconfiguration are comparable and travel the same pipeline into the findings SSOT.
"""

from __future__ import annotations

import json
import logging

from components.shared_kernel.application.ports.scanner_port import ScanResult
from components.shared_kernel.domain.security import AssetUrn, NormalizedFinding, Severity

logger = logging.getLogger(__name__)

_ENGINE = "trivy"

# Trivy severities → shared Severity. UNKNOWN maps to INFORMATIONAL (no manufactured urgency).
_SEVERITY = {
    "UNKNOWN": Severity.INFORMATIONAL,
    "LOW": Severity.LOW,
    "MEDIUM": Severity.MEDIUM,
    "HIGH": Severity.HIGH,
    "CRITICAL": Severity.CRITICAL,
}


def trivy_json_to_scan_result(raw: str | dict, *, image_ref: str, engine_version: str = "") -> ScanResult:
    """Parse Trivy image-scan JSON (string or dict) → a ``ScanResult`` (pure: no DB, no engine).

    ``findings`` are one ``NormalizedFinding`` per vulnerability; counts describe the run.
    Malformed/empty input yields an empty result rather than raising (a bad scan records
    zero findings, it doesn't crash the pipeline).
    """
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw) if raw.strip() else {}
        except ValueError:
            logger.warning("trivy_parse: non-JSON output for image=%s", image_ref)
            return _empty(engine_version)
    if not isinstance(data, dict):
        return _empty(engine_version)

    asset_urn = AssetUrn.canonical("oci", image_ref).value
    findings: list[NormalizedFinding] = []
    for result in data.get("Results") or []:
        if not isinstance(result, dict):
            continue
        target = str(result.get("Target") or "")
        pkg_class = str(result.get("Class") or "")
        pkg_type = str(result.get("Type") or "")
        for vuln in result.get("Vulnerabilities") or []:
            if not isinstance(vuln, dict):
                continue
            vuln_id = str(vuln.get("VulnerabilityID") or "").strip()
            pkg = str(vuln.get("PkgName") or "").strip()
            if not vuln_id or not pkg:
                continue
            installed = str(vuln.get("InstalledVersion") or "")
            fixed = str(vuln.get("FixedVersion") or "")
            severity = _SEVERITY.get(str(vuln.get("Severity") or "").upper(), Severity.INFORMATIONAL)
            attributes = {
                "vulnerability_id": vuln_id,
                "pkg_name": pkg,
                "installed_version": installed,
                "fixed_version": fixed,
                "target": target,
                "class": pkg_class,
                "type": pkg_type,
                "primary_url": vuln.get("PrimaryURL") or "",
            }
            # Capture the numeric CVSS base so contextual-risk scoring (ADR 0013) can use
            # the real impact score, not just the qualitative severity band. Trivy carries
            # a per-vendor ``CVSS`` map; prefer NVD, prefer v3 over v2.
            cvss_base = _extract_cvss_base(vuln.get("CVSS"))
            if cvss_base is not None:
                attributes["cvss_base"] = cvss_base
            findings.append(
                NormalizedFinding(
                    source="container_security.trivy",
                    fingerprint=f"{vuln_id}|{image_ref}|{pkg}|{installed}",
                    asset_urn=asset_urn,
                    severity=severity,
                    title=(vuln.get("Title") or f"{vuln_id} in {pkg}")[:512],
                    description=vuln.get("Description") or "",
                    remediation=(f"Upgrade {pkg} to {fixed}" if fixed else "No fixed version available"),
                    attributes=attributes,
                )
            )

    return ScanResult(
        findings=tuple(findings),
        engine=_ENGINE,
        engine_version=engine_version or _ENGINE,
        total_checks=len(findings),
        passed_count=0,
        failed_count=len(findings),
    )


def _extract_cvss_base(cvss) -> float | None:
    """Best numeric CVSS base from Trivy's per-vendor ``CVSS`` map.

    Trivy attaches ``{"nvd": {"V3Score": 9.8, "V2Score": 10.0}, "redhat": {...}}``. We
    prefer NVD, and v3 over v2; falling back to any vendor's score. Returns None when no
    numeric score is present (the scorer then degrades to the severity-derived prior).
    """
    if not isinstance(cvss, dict) or not cvss:
        return None
    vendors = list(cvss.values())
    # Preference order: NVD v3 → NVD v2 → any v3 → any v2.
    nvd = cvss.get("nvd") if isinstance(cvss.get("nvd"), dict) else None
    for source, key in ((nvd, "V3Score"), (nvd, "V2Score")):
        score = _as_float(source.get(key)) if isinstance(source, dict) else None
        if score is not None:
            return score
    for key in ("V3Score", "V2Score"):
        for vendor in vendors:
            score = _as_float(vendor.get(key)) if isinstance(vendor, dict) else None
            if score is not None:
                return score
    return None


def _as_float(value) -> float | None:
    if value is None:
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return score if 0.0 <= score <= 10.0 else None


def _empty(engine_version: str) -> ScanResult:
    return ScanResult(findings=(), engine=_ENGINE, engine_version=engine_version or _ENGINE)
