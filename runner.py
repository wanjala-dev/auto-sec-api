"""Custom Django test runner that delegates to pytest."""

from __future__ import annotations

from typing import List


class PytestTestRunner:
    """Run the Django test suite via pytest."""

    def __init__(self, verbosity: int = 1, failfast: bool = False, keepdb: bool = False, **_: object) -> None:
        self.verbosity = verbosity
        self.failfast = failfast
        self.keepdb = keepdb

    @classmethod
    def add_arguments(cls, parser) -> None:
        parser.add_argument(
            "--keepdb",
            action="store_true",
            help="Preserve the test database between runs when supported.",
        )

    def run_tests(self, test_labels: List[str]) -> int:
        """Translate Django's test command options to pytest CLI arguments."""
        import pytest

        argv: List[str] = []
        if self.verbosity == 0:
            argv.append("--quiet")
        elif self.verbosity == 2:
            argv.append("--verbose")
        elif self.verbosity >= 3:
            argv.append("-vv")

        if self.failfast:
            argv.append("--exitfirst")
        if self.keepdb:
            argv.append("--reuse-db")

        argv.extend(test_labels)
        return pytest.main(argv)

