"""Run the SAST fix-quality eval against the frozen corpus (#117).

Drives the REAL advisor (real LLM, real verifier, real re-advise loop) over the
frozen fixtures and writes a per-rule counts report. This is the measurement
that decides template changes and, ultimately, the auto-fix gate — run it
before AND after any guidance/template edit, one change at a time.

    python manage.py run_sast_fix_eval --label baseline
    python manage.py run_sast_fix_eval --label candidate --fixture sql-set-search-path-fstring

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

    def handle(self, *args, **options):
        from components.agents.infrastructure.evaluation.sast_fix_eval import (
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

        report_path = write_report(results, label=options["label"], out_dir=REPORTS_DIR)
        summary = summarize(results)
        self.stdout.write(self.style.SUCCESS(f"\nReport: {report_path}"))
        a, b = summary["class_a"], summary["class_b"]
        self.stdout.write(f"Class A (patchable): {a['machine_pass']}/{a['total']} machine-pass")
        self.stdout.write(f"Class B (design change): {b['honest_decline']}/{b['total']} honest declines")
        for rule, counts in summary["per_rule"].items():
            self.stdout.write(
                f"  {rule}: {counts['machine_pass']}/{counts['total']} pass"
                + (f", gate failures {counts['gate_failures']}" if counts["gate_failures"] else "")
            )
        self.stdout.write(
            "Machine gates catch wrong SHAPES, not every wrong MEANING — "
            "hand-label the human_verdict column in the JSON before quoting numbers."
        )
