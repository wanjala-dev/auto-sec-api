"""Run the SAST fix-quality eval against the frozen corpus (#117).

Drives the REAL advisor (real LLM, real verifier, real re-advise loop) over the
frozen fixtures and writes a per-rule counts report. This is the measurement
that decides template changes and feeds the auto-fix confidence gate — run it
before AND after any guidance/template edit, one change at a time.

    python manage.py run_sast_fix_eval --label baseline
    python manage.py run_sast_fix_eval --label candidate --fixture sql-set-search-path-fstring

Turning measurements into gate evidence (#117 step 3) is a separate, offline
step, because a report is not evidence until a human labels it:

    # 1. hand-fill human_verdict on every machine_pass row in the report JSONs
    # 2. aggregate the labeled reports into the committed evidence file
    python manage.py run_sast_fix_eval --write-evidence docs/eval-reports/sast-fix-run-*.json

``--write-evidence`` makes no LLM calls: it aggregates existing hand-labeled
reports into ``components/code_security/rules/remediation/fix_confidence.yaml``
and prints the per-rule gate verdict that evidence produces. It refuses
unlabeled machine_pass rows, stale-corpus reports, and mixed-model batches —
each refusal names the file and the fix.

Needs a configured LLM provider (same requirement as run_planner_eval); the
file content comes from the fixtures, so no VCS connection and no workspace
are touched. Roughly one to three LLM calls per fixture (the re-advise loop).
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "tests" / "sast_fix_eval" / "fixtures"
REPORTS_DIR = Path(__file__).resolve().parents[5] / "docs" / "eval-reports"


class Command(BaseCommand):
    help = "Measure SAST fix quality against the frozen corpus (per-rule counts, class-stratified)."

    def add_arguments(self, parser):
        parser.add_argument("--label", default="run", help="Report label, e.g. baseline / candidate-contrastive")
        parser.add_argument("--fixture", action="append", default=None, help="Run only these fixture ids (repeatable)")
        parser.add_argument(
            "--write-evidence",
            nargs="+",
            metavar="REPORT_JSON",
            default=None,
            help=(
                "Aggregate HAND-LABELED report JSONs into the committed fix-confidence "
                "evidence file, print the resulting per-rule gate verdicts, and exit. "
                "No LLM calls."
            ),
        )

    def handle(self, *args, **options):
        if options.get("write_evidence"):
            self._write_evidence([Path(p) for p in options["write_evidence"]])
            return

        from components.agents.infrastructure.evaluation.sast_fix_eval import (
            corpus_digest_of,
            load_fixtures,
            run_fixture,
            summarize,
            write_report,
        )
        from components.code_security.application.sast_fix_advisor_service import SastFixAdvisor

        fixtures = load_fixtures(FIXTURES_DIR)
        wanted = options.get("fixture")
        if wanted:
            fixtures = [f for f in fixtures if f.id in set(wanted)]
            missing = set(wanted) - {f.id for f in fixtures}
            if missing:
                raise CommandError(f"Unknown fixture ids: {sorted(missing)}")
        if not fixtures:
            raise CommandError(f"No fixtures found under {FIXTURES_DIR}")

        sources = {f.id: f.source_content for f in fixtures}
        by_path = {f.path: f.id for f in fixtures}

        def read_fixture_file(workspace_id, repo, path, ref):
            fixture_id = by_path.get(path)
            return sources.get(fixture_id) if fixture_id else None

        advisor = SastFixAdvisor(file_reader=read_fixture_file)

        results = []
        for fixture in fixtures:
            self.stdout.write(f"→ {fixture.id} ({fixture.rule_id}, class {fixture.fix_class})")
            result = run_fixture(fixture, advisor)
            results.append(result)
            self.stdout.write(f"   outcome={result.outcome} verification={result.verification}")
            for gate, verdict in result.gates.items():
                self.stdout.write(f"   {gate}: {verdict}")

        # A partial run (--fixture) is a debugging aid, not a measurement of the
        # corpus — stamping the full-corpus digest on it would let a cherry-picked
        # subset masquerade as full-corpus evidence at aggregation time.
        digest = corpus_digest_of(FIXTURES_DIR) if not wanted else ""
        report_path = write_report(results, label=options["label"], out_dir=REPORTS_DIR, corpus_digest=digest)
        summary = summarize(results)
        self.stdout.write(self.style.SUCCESS(f"\nReport: {report_path}"))
        a, b = summary["class_a"], summary["class_b"]
        self.stdout.write(
            f"Class A (patchable): {a['machine_pass']}/{a['total']} machine-pass"
            + (f", {a['declined_patchable']} declined_patchable (misses)" if a.get("declined_patchable") else "")
        )
        self.stdout.write(
            f"Class B (design change): {b['honest_decline']}/{b['total']} honest declines"
            + (f", {b['fabricated_patch']} fabricated" if b.get("fabricated_patch") else "")
        )
        for rule, counts in summary["per_rule"].items():
            self.stdout.write(
                f"  {rule}: {counts['machine_pass']}/{counts['total']} pass"
                + (f", gate failures {counts['gate_failures']}" if counts["gate_failures"] else "")
            )
        self.stdout.write(
            "Machine gates catch wrong SHAPES, not every wrong MEANING — "
            "hand-label the human_verdict column in the JSON, then feed labeled "
            "reports to --write-evidence to update the confidence gate."
        )

    def _write_evidence(self, report_paths: list[Path]) -> None:
        import yaml

        from components.agents.infrastructure.evaluation.sast_fix_eval import (
            EvidenceAggregationError,
            corpus_digest_of,
            evidence_from_reports,
        )
        from components.code_security.domain import fix_confidence as fc

        missing = [p for p in report_paths if not p.is_file()]
        if missing:
            raise CommandError(f"Report(s) not found: {[str(p) for p in missing]}")

        digest = corpus_digest_of(FIXTURES_DIR)
        try:
            evidence = evidence_from_reports(report_paths, fixtures_digest=digest)
        except EvidenceAggregationError as exc:
            raise CommandError(str(exc)) from exc

        fc.EVIDENCE_FILE.write_text(
            "# GENERATED by `manage.py run_sast_fix_eval --write-evidence` — do not hand-edit.\n"
            "# Counts come from hand-labeled eval reports; hand-editing this file is the\n"
            "# unmeasured-quality-claim failure the gate exists to remove (#117).\n"
            + yaml.safe_dump(evidence, sort_keys=False)
        )
        fc._load.cache_clear()

        self.stdout.write(self.style.SUCCESS(f"Evidence written: {fc.EVIDENCE_FILE}"))
        self.stdout.write(f"model={evidence['model'] or '<unknown>'} corpus={digest[:12]}\n")
        for rule in evidence["rules"]:
            verdict = fc.confidence_for(rule, model=evidence["model"])
            marker = "✅ AUTOFIX-ELIGIBLE" if verdict.autofix_permitted else f"⛔ {verdict.tier}"
            self.stdout.write(f"  {rule}: {verdict.passes}/{verdict.trials} → {marker} — {verdict.reason}")
        self.stdout.write(
            "\nCommit the evidence file with the reports that produced it. "
            "The tier is a LABEL on findings and a permission bit for the "
            "unattended tier only — draft PRs open regardless."
        )
