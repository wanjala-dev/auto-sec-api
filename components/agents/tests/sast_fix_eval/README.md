# SAST fix-quality eval — the frozen corpus and its rules (#117)

This suite measures the SAST fix advisor against a **frozen, class-stratified
corpus**, driving the real production choreography (advisor → grounded verifier
→ one re-advise → re-verify) with a per-gate result for every fixture. It exists
because ADR 0025's corpus was a markdown table and every intervention since was
argued from three live cards.

## Running it

```bash
python manage.py run_sast_fix_eval --label baseline          # real LLM, all fixtures
python manage.py run_sast_fix_eval --label candidate --fixture sql-set-search-path-fstring
```

Reports land in `docs/eval-reports/sast-fix-<label>-<ts>.json`. Machine gates
catch wrong **shapes**, not every wrong **meaning** — hand-fill the
`human_verdict` column (`correct | plausible_but_wrong | wrong`) before quoting
any number.

## The rules (violating these makes the numbers lies)

1. **The corpus is frozen.** A change to `classes.yaml`, `prompt_block`, or any
   advisor prompt must NOT edit fixtures in the same PR. Zero overlap between
   what an author tuned against and what the harness scores.
2. **Counts, per rule — never aggregate percentages.** At n≤10 per rule, an
   aggregate launders easy rules into a number that means nothing. The ship
   decision for any rule's autofix confidence is that rule's own count.
3. **Class A and Class B are different tests.** Class A (`expected: patch`)
   succeeds by a machine-passing patch. Class B (`expected: decline`) succeeds
   by an HONEST decline — a concrete patch on a design-change finding is the
   #326 fabrication, scored as failure.
4. **One change at a time.** Run `--label baseline`, make ONE guidance/prompt
   edit, run `--label candidate-<change>`, compare per-gate counts. Two edits
   in one run are unattributable.
5. **Every field failure becomes a fixture.** A wrong fix that reaches a real
   repo gets frozen here (source + manifest) before it gets fixed, so the
   regression is permanent.
6. **Line numbers must match the source files** — the formatter reflows fixture
   sources, and `test_fixture_integrity.py` fails loudly when a span drifts off
   its sink. Fix the manifest, not the test.

## Fixture shape

`<id>.json` + a sibling source file:

```json
{
  "id": "sql-create-schema-fstring",
  "rule_id": "autosec.python.sql-execute-format",
  "fix_class": "A",              // A = patchable by a local edit, B = design change
  "kind": "sql-identifier",      // stratum within the remediation class
  "path": "app/.../migrate_schema.py",
  "start_line": 13, "end_line": 13,
  "language": "python",
  "message": "<the rule message>",
  "source_file": "sql_migrate_schema.py",
  "expected": "patch",           // or "decline" for Class B
  "notes": "provenance + what the correct fix is",
  "awkward": false               // aliased imports, multi-line spans, etc.
}
```

Provenance of v1: the three ADR 0025 corpus findings (9976 CREATE SCHEMA, 9977
SET search_path, 9975 Apple JWT) plus hand-authored strata — a value-kind
positive control, an aliased-import awkward case, and one fixture each for the
argv-list / safe-loader / trust-store / different-format classes.

7. **Reports are written inside the pod and die with it** — `kubectl cp` (or
   `kubectl exec ... cat`) the JSON out immediately after a run; two
   intermediate candidate reports were lost to a rollout before this line
   existed.
