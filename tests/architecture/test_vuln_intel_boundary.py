"""Architecture guardrails for the vuln_intel threat-intel module (ADR 0013 D2).

Two structural facts the ADR fixes:

1. **Feeds implement the ``VulnFeedPort`` seam** — each external feed is a driven
   adapter behind the port (mirroring ``ScannerPort`` / ``LogSourcePort``), so adding a
   feed is a new adapter, never a new pipeline (ADR 0013 D2 / ADR 0004 C5).
2. **vuln_intel enriches the Finding SSOT; it never writes findings** — the feeds are
   *reference/enrichment data, not findings*, so no vuln_intel code may touch the
   ``Finding`` ORM model (ADR 0004 C6). It correlates by CVE id via the read port only.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_feed_adapters_implement_vuln_feed_port():
    from components.vuln_intel.application.ports.vuln_feed_port import EpssFeedPort, KevFeedPort
    from components.vuln_intel.infrastructure.adapters.epss_feed_adapter import EpssFeedAdapter
    from components.vuln_intel.infrastructure.adapters.kev_feed_adapter import KevFeedAdapter

    assert issubclass(EpssFeedAdapter, EpssFeedPort)
    assert issubclass(KevFeedAdapter, KevFeedPort)


def _iter_python_files(*rel_dirs: str) -> list[Path]:
    files: list[Path] = []
    for rel in rel_dirs:
        base = ROOT / rel
        if base.exists():
            files.extend(f for f in base.rglob("*.py") if f.is_file())
    return sorted(files)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
    return mods


def test_vuln_intel_never_imports_the_finding_model():
    """vuln_intel enriches the SSOT; it must never write/read the Finding ORM (C6)."""
    offenders: list[str] = []
    for py in _iter_python_files("components/vuln_intel", "infrastructure/persistence/vuln_intel"):
        for mod in _imported_modules(py):
            if mod == "infrastructure.persistence.findings.models" or mod.startswith(
                "infrastructure.persistence.findings"
            ):
                offenders.append(str(py.relative_to(ROOT)))
    assert not offenders, (
        "vuln_intel must not touch the Finding ORM (feeds enrich the SSOT by CVE id, they "
        "do not write findings — ADR 0004 C6):\n  - " + "\n  - ".join(offenders)
    )
