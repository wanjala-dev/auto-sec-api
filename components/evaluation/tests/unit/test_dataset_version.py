"""What the fingerprint must and must not notice.

The property under test is narrow and load-bearing: the fingerprint has to change
when the QUESTION changes, and stay put when nothing about the question did.

Get the first half wrong and editing a case becomes indistinguishable from the
model changing — which matters most in the direction nobody reports, where
someone softens the criteria a suite is failing and reads the improvement as
progress. Get the second half wrong and the version churns on unrelated edits
until people learn to ignore it, which is the same as not having it.
"""

from __future__ import annotations

import pytest

from components.evaluation.domain.value_objects.dataset_version import (
    SHORT_LENGTH,
    CaseFingerprintInput,
    comparable,
    fingerprint,
    short,
)

pytestmark = [pytest.mark.unit]


def _case(case_id="a", scenario="public bucket", inputs=None, criteria=("names the bucket",)):
    return CaseFingerprintInput(
        case_id=case_id,
        scenario=scenario,
        prompt_inputs=inputs if inputs is not None else {"title": "public bucket"},
        solution_criteria=list(criteria),
    )


class TestStability:
    def test_the_same_cases_fingerprint_the_same_way_every_time(self):
        assert fingerprint([_case(), _case("b")]) == fingerprint([_case(), _case("b")])

    def test_reordering_the_suite_is_not_a_change(self):
        """Order is presentation. Treating it as content would report a changed
        dataset every time a case list was sorted differently."""
        assert fingerprint([_case("a"), _case("b")]) == fingerprint([_case("b"), _case("a")])

    def test_it_does_not_depend_on_python_hash_randomisation(self):
        """`hash()` is salted per interpreter, so a fingerprint built on it
        would differ between the web process and the worker — and a run would
        never match the suite it came from."""
        value = fingerprint([_case()])

        assert len(value) == 64
        assert value == fingerprint([_case()])


class TestItNoticesRealChanges:
    def test_editing_the_expected_criteria_changes_the_version(self):
        """The one that matters most. Softening the criteria a suite is failing
        is the easiest way to manufacture an improvement, and the case id does
        not move when you do it."""
        before = fingerprint([_case(criteria=("names the bucket", "proposes a policy change"))])
        after = fingerprint([_case(criteria=("mentions S3",))])

        assert before != after

    def test_editing_the_prompt_inputs_changes_the_version(self):
        assert fingerprint([_case(inputs={"title": "a"})]) != fingerprint([_case(inputs={"title": "b"})])

    def test_editing_the_scenario_changes_the_version(self):
        assert fingerprint([_case(scenario="one")]) != fingerprint([_case(scenario="two")])

    def test_adding_a_case_changes_the_version(self):
        assert fingerprint([_case()]) != fingerprint([_case(), _case("b")])

    def test_removing_a_case_changes_the_version(self):
        assert fingerprint([_case(), _case("b")]) != fingerprint([_case()])

    def test_an_empty_suite_has_its_own_stable_version(self):
        assert fingerprint([]) == fingerprint([])
        assert fingerprint([]) != fingerprint([_case()])


class TestComparability:
    def test_identical_versions_are_comparable(self):
        assert comparable("abc123", "abc123") is True

    def test_different_versions_are_not(self):
        assert comparable("abc123", "def456") is False

    def test_an_unknown_version_is_never_comparable(self):
        """Runs recorded before fingerprints existed carry none. Treating "we do
        not know" as "the same" is exactly the false comparison this prevents —
        and it is the permissive default someone would reach for."""
        assert comparable("", "abc123") is False
        assert comparable("abc123", "") is False
        assert comparable("", "") is False


class TestDisplayForm:
    def test_it_shortens_to_something_readable(self):
        assert len(short(fingerprint([_case()]))) == SHORT_LENGTH

    def test_an_absent_version_stays_absent_rather_than_becoming_a_string(self):
        """A run with no version must render as having none. Inventing a
        placeholder would put a version-shaped thing on screen that identifies
        nothing."""
        assert short("") == ""
        assert short(None) == ""
