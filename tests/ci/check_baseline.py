#!/usr/bin/env python3
"""Gate a pytest junit-XML run against the documented failure baseline.

The repo carries known pre-existing failures (architecture drift, sponsorship
test drift — see CLAUDE.md "Test-After-Change Rule" for the history). CI must
fail on NEW failures without forcing anyone to fix years of documented drift
in an unrelated PR. Same philosophy as the EC2 pre-deploy gate: pre-existing
baseline failures don't block; new ones do.

Usage: check_baseline.py <baseline.txt> <junit.xml> [<junit.xml> ...]

Multiple junit files are unioned — the CI matrix shards the suite across
parallel jobs and this gate runs once over all shard reports.

The baseline file lists one `classname::name` per line (junit identity, i.e.
dotted module path), `#` comments allowed. When a baseline entry starts
passing, this script says so — prune it in the same PR that fixed it.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def main() -> int:
    baseline_path, junit_paths = sys.argv[1], sys.argv[2:]
    if not junit_paths:
        print("no junit files supplied — did every shard fail before producing a report?")
        return 1

    failed: set[str] = set()
    total_cases = 0
    for junit_path in junit_paths:
        for case in ET.parse(junit_path).iter("testcase"):
            total_cases += 1
            if case.find("failure") is not None or case.find("error") is not None:
                failed.add(f"{case.get('classname')}::{case.get('name')}")
    print(f"shards: {len(junit_paths)} | testcases seen: {total_cases}")

    baseline = {
        line.strip()
        for line in Path(baseline_path).read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    }

    new = sorted(failed - baseline)
    fixed = sorted(baseline - failed)

    print(f"failures this run: {len(failed)} | baseline: {len(baseline)} | new: {len(new)} | now-passing: {len(fixed)}")

    if fixed:
        print("\nBaseline entries that now PASS — prune them from the baseline in this PR:")
        for test_id in fixed:
            print(f"  {test_id}")

    if new:
        print("\nNEW failures (not in baseline) — the gate FAILS:")
        for test_id in new:
            print(f"  {test_id}")
        return 1

    print("\nNo new failures — gate passes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
