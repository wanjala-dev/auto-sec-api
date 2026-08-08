"""The curated Opengrep ruleset loader (ADR 0019 D1/D4 — the funnel's floor).

Loads the license-audited rule packs declared in ``rules/packs.yaml``, merges them
into ONE rules document, and returns it as YAML text for the scan Job (mounted via
env — the Job writes it to a file and passes ``-f``; repo-side rule/config files are
NEVER honored, D6). The manifest is authoritative: a pack file not listed there is
not loaded, so an unaudited pack can't ride along.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_RULES_DIR = Path(__file__).resolve().parents[2] / "rules"
_MANIFEST = _RULES_DIR / "packs.yaml"


class RulesetError(RuntimeError):
    """The curated ruleset is missing or malformed — fail loud, never scan ruleless."""


@lru_cache(maxsize=1)
def load_ruleset_yaml() -> str:
    """Merge every manifest-listed pack into one ``rules:`` YAML document (cached)."""
    rules = _load_rules()
    return yaml.safe_dump({"rules": rules}, sort_keys=False)


@lru_cache(maxsize=1)
def ruleset_rule_ids() -> tuple[str, ...]:
    """The merged ruleset's rule ids (stable order) — for snapshots/diagnostics."""
    return tuple(rule["id"] for rule in _load_rules())


def _load_rules() -> list[dict]:
    if not _MANIFEST.exists():
        raise RulesetError(f"Ruleset manifest missing: {_MANIFEST}")
    manifest = yaml.safe_load(_MANIFEST.read_text()) or {}
    packs = manifest.get("packs") or []
    if not packs:
        raise RulesetError("Ruleset manifest lists no packs")

    merged: list[dict] = []
    seen: set[str] = set()
    for pack in packs:
        pack_id = str(pack.get("id") or "")
        pack_file = _RULES_DIR / str(pack.get("file") or "")
        if not pack_id or not pack_file.is_file():
            raise RulesetError(f"Pack {pack_id!r} missing or its file not found: {pack_file}")
        document = yaml.safe_load(pack_file.read_text()) or {}
        rules = document.get("rules") or []
        if not rules:
            raise RulesetError(f"Pack {pack_id!r} contains no rules")
        for rule in rules:
            rule_id = str(rule.get("id") or "")
            if not rule_id:
                raise RulesetError(f"Pack {pack_id!r} has a rule without an id")
            if rule_id in seen:
                raise RulesetError(f"Duplicate rule id across packs: {rule_id}")
            seen.add(rule_id)
            merged.append(rule)

    logger.info("code_security_ruleset_loaded packs=%d rules=%d", len(packs), len(merged))
    return merged
