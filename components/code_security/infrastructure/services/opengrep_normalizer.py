"""Parse Opengrep SARIF → the shared ``NormalizedFinding`` shape (ADR 0019 D2/D4).

Opengrep emits standard SARIF 2.1.0 (``--sarif``): results carry the code location
(path + line span + matched snippet) and the engine's line-drift-tolerant result
fingerprint (``fingerprints["matchBasedId/v1"]`` — the property GitHub's SARIF
``partialFingerprints`` exist for, R7). SAST specifics ride in ``attributes`` so a
code finding travels the same pipeline into the findings SSOT as a CVE or a CSPM
misconfiguration.

Identity (D4): ``fingerprint = repo | rule_id | path | <engine match id>`` — LINE
NUMBERS NEVER ENTER THE FINGERPRINT (edits above a finding must not mint a "new"
finding). When the engine fingerprint is absent, the fallback is a content hash of
the matched snippet (a ``primaryLocationLineHash``-style stand-in).

Severity: the rule's ``security-severity`` (CVSS-like 0–10, GitHub convention)
when present, else the SARIF level. The same number feeds ``attributes.cvss_base``
so contextual-risk scoring (ADR 0013) gets a real numeric prior; SAST findings
carry no CVE, so the EPSS/KEV signals correctly stay absent.
"""

from __future__ import annotations

import hashlib
import json
import logging

from components.shared_kernel.application.ports.scanner_port import ScanResult
from components.shared_kernel.domain.security import AssetUrn, NormalizedFinding, Severity

logger = logging.getLogger(__name__)

_ENGINE = "opengrep"
SOURCE = "code_security.opengrep"

# SARIF level → shared Severity (used when a rule carries no security-severity).
_LEVEL_SEVERITY = {
    "error": Severity.HIGH,
    "warning": Severity.MEDIUM,
    "note": Severity.LOW,
    "none": Severity.INFORMATIONAL,
}

# The matched-region snippet is stored minimal + capped (ADR 0019 D8).
_SNIPPET_MAX_CHARS = 2000

# Rules whose match IS the secret (hardcoded-credential class) must not replicate
# it into the DB/board/projections — the snippet is stored masked (D8). P1 ships
# no secret rules (OQ5), but the guard is in place so a future pack can't leak.
_SECRET_TAG_MARKERS = ("secret", "hardcoded-credential", "cwe-798")
_MASKED_SNIPPET = "•••• (masked secret-bearing match)"


def opengrep_sarif_to_scan_result(raw: str | dict, *, repo: str, commit_sha: str) -> ScanResult:
    """Parse Opengrep SARIF (string or dict) → a ``ScanResult`` (pure: no DB, no engine).

    Malformed/empty input yields an empty result rather than raising (the adapter
    already fail-louds on a non-zero engine exit; by the time SARIF reaches here the
    engine reported success).
    """
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw) if raw.strip() else {}
        except ValueError:
            logger.warning("opengrep_parse: non-JSON SARIF for repo=%s", repo)
            return _empty("")
    if not isinstance(data, dict):
        return _empty("")

    runs = data.get("runs") or []
    run = runs[0] if runs and isinstance(runs[0], dict) else {}
    driver = ((run.get("tool") or {}).get("driver")) or {}
    engine_version = str(driver.get("semanticVersion") or "")
    rule_index = _index_rules(driver.get("rules") or [])

    asset_urn = AssetUrn.canonical("vcs", f"github:{repo}").value
    findings: list[NormalizedFinding] = []
    for result in run.get("results") or []:
        if not isinstance(result, dict):
            continue
        finding = _normalize_result(result, rule_index, repo=repo, commit_sha=commit_sha, asset_urn=asset_urn)
        if finding is not None:
            findings.append(finding)

    return ScanResult(
        findings=tuple(findings),
        engine=_ENGINE,
        engine_version=engine_version or _ENGINE,
        total_checks=len(findings),
        passed_count=0,
        failed_count=len(findings),
    )


def _normalize_result(result: dict, rule_index: dict, *, repo: str, commit_sha: str, asset_urn: str):
    rule_id = str(result.get("ruleId") or "").strip()
    if not rule_id:
        return None
    location = _first_location(result)
    if location is None:
        return None
    path, start_line, end_line, snippet = location

    rule_meta = rule_index.get(rule_id, {})
    severity_score = rule_meta.get("security_severity")
    severity = _severity(severity_score, rule_meta.get("level"))
    message = str(((result.get("message") or {}).get("text")) or rule_id).strip()

    secret_class = _is_secret_rule(rule_meta.get("tags") or ())
    stored_snippet = _MASKED_SNIPPET if secret_class else (snippet or "")[:_SNIPPET_MAX_CHARS]

    attributes = {
        "repo": repo,
        "commit_sha": commit_sha,
        "path": path,
        "start_line": start_line,
        "end_line": end_line,
        "rule_id": rule_id,
        "rule_source": "autosec-p1-core" if rule_id.startswith("autosec.") else "unknown",
        "cwe": [t for t in rule_meta.get("tags") or () if t.upper().startswith("CWE-")],
        "confidence": "high" if "HIGH CONFIDENCE" in (rule_meta.get("tags") or ()) else "medium",
        "language": _language_from_rule_id(rule_id),
        "snippet": stored_snippet,
    }
    if severity_score is not None:
        # The rule's CVSS-like score feeds contextual-risk (ADR 0013) as the numeric
        # prior — SAST has no CVE, so EPSS/KEV correctly degrade to absent.
        attributes["cvss_base"] = severity_score

    return NormalizedFinding(
        source=SOURCE,
        fingerprint=_fingerprint(result, repo=repo, rule_id=rule_id, path=path, snippet=snippet),
        asset_urn=asset_urn,
        severity=severity,
        title=message[:512],
        description=f"{message}\n\nRule: {rule_id}\nLocation: {path}:{start_line}",
        remediation=f"Review {path}:{start_line} and apply the rule guidance ({rule_id}).",
        attributes=attributes,
    )


# The SSOT's identity column is 255 chars; the composed fingerprint must always fit.
_FINGERPRINT_MAX = 255


def _fingerprint(result: dict, *, repo: str, rule_id: str, path: str, snippet: str) -> str:
    """Line-stable identity (D4): engine match id first, snippet content hash fallback.

    The engine's 128-hex match id is compacted to a 16-hex digest (+ its occurrence
    suffix, so two identical matches in one file stay distinct); a pathological path
    length degrades to a path digest — the fingerprint ALWAYS fits the SSOT's
    255-char identity column, and line numbers never enter it.
    """
    fingerprints = result.get("fingerprints") or {}
    match_id = ""
    if isinstance(fingerprints, dict):
        match_id = str(fingerprints.get("matchBasedId/v1") or "").strip()
        if not match_id:  # any other engine-provided fingerprint, deterministically chosen
            for key in sorted(fingerprints):
                value = str(fingerprints[key] or "").strip()
                if value:
                    match_id = value
                    break
    if match_id:
        base, _, occurrence = match_id.partition("_")
        short = _digest(base, 16) + (f"_{occurrence}" if occurrence else "")
    else:
        content = " ".join((snippet or "").split())  # whitespace-normalized matched region
        short = "s" + _digest(content, 16)

    candidate = f"{repo}|{rule_id}|{path}|{short}"
    if len(candidate) <= _FINGERPRINT_MAX:
        return candidate
    return f"{repo}|{rule_id}|p{_digest(path, 16)}|{short}"[:_FINGERPRINT_MAX]


def _digest(value: str, length: int) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def _first_location(result: dict):
    for loc in result.get("locations") or []:
        physical = (loc or {}).get("physicalLocation") or {}
        path = str(((physical.get("artifactLocation") or {}).get("uri")) or "").strip()
        if not path:
            continue
        region = physical.get("region") or {}
        start_line = int(region.get("startLine") or 0)
        end_line = int(region.get("endLine") or start_line)
        snippet = str(((region.get("snippet") or {}).get("text")) or "")
        return path, start_line, end_line, snippet
    return None


def _index_rules(rules: list) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for rule in rules:
        if not isinstance(rule, dict) or not rule.get("id"):
            continue
        properties = rule.get("properties") or {}
        index[str(rule["id"])] = {
            "level": str(((rule.get("defaultConfiguration") or {}).get("level")) or ""),
            "security_severity": _as_score(properties.get("security-severity")),
            "tags": tuple(str(t) for t in properties.get("tags") or ()),
        }
    return index


def _severity(score: float | None, level: str | None) -> Severity:
    if score is not None:
        if score >= 9.0:
            return Severity.CRITICAL
        if score >= 7.0:
            return Severity.HIGH
        if score >= 4.0:
            return Severity.MEDIUM
        if score > 0.0:
            return Severity.LOW
        return Severity.INFORMATIONAL
    return _LEVEL_SEVERITY.get((level or "").lower(), Severity.MEDIUM)


def _is_secret_rule(tags: tuple[str, ...]) -> bool:
    lowered = [t.lower() for t in tags]
    return any(marker in tag for tag in lowered for marker in _SECRET_TAG_MARKERS)


def _language_from_rule_id(rule_id: str) -> str:
    parts = rule_id.split(".")
    return parts[1] if len(parts) >= 3 else ""


def _as_score(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return score if 0.0 <= score <= 10.0 else None


def _empty(engine_version: str) -> ScanResult:
    return ScanResult(findings=(), engine=_ENGINE, engine_version=engine_version or _ENGINE)
