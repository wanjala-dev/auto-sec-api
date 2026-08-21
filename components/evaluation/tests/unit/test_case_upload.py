"""Parsing a file someone wrote by hand.

The tests worth having here are about REFUSALS, because every one of them has a
permissive alternative that produces a suite quietly different from what the
author intended — and a suite nobody can see is wrong is scored anyway.
"""

from __future__ import annotations

import json

import pytest

from components.evaluation.domain.services import case_upload

pytestmark = [pytest.mark.unit]


def _case(**over):
    base = {
        "scenario": "public bucket",
        "prompt_inputs": {"title": "S3 bucket is public"},
        "solution_criteria": ["names the bucket"],
        "label": "good",
    }
    base.update(over)
    return base


def _json(*cases):
    return json.dumps({"cases": list(cases)})


class TestHappyPath:
    def test_a_well_formed_file_parses(self):
        result = case_upload.parse(_json(_case(), _case(scenario="open security group")), fmt="json")

        assert result.ok
        assert len(result.cases) == 2
        assert result.cases[0].scenario == "public bucket"

    def test_a_bare_list_is_accepted_as_well_as_a_cases_object(self):
        """People hand-write the list; the template emits the object."""
        result = case_upload.parse(json.dumps([_case()]), fmt="json")

        assert result.ok

    def test_criteria_and_inputs_survive_intact(self):
        result = case_upload.parse(
            _json(_case(solution_criteria=["a", "b"], prompt_inputs={"severity": "high"})), fmt="json"
        )

        assert result.cases[0].solution_criteria == ["a", "b"]
        assert result.cases[0].prompt_inputs == {"severity": "high"}


class TestItRefusesRatherThanPartiallyImporting:
    def test_one_bad_row_rejects_the_whole_file(self):
        """Importing 1 of 2 leaves a suite that silently differs from the file
        that created it, and the missing row is invisible from then on."""
        result = case_upload.parse(_json(_case(), _case(scenario="")), fmt="json")

        assert not result.ok
        assert result.cases == []

    def test_the_error_names_the_row_the_author_can_find(self):
        result = case_upload.parse(_json(_case(), _case(scenario="")), fmt="json")

        assert result.errors[0].row == 2
        assert "scenario" in result.errors[0].message

    def test_every_bad_row_is_reported_not_just_the_first(self):
        """Fixing a file one error per upload is a miserable loop."""
        result = case_upload.parse(_json(_case(scenario=""), _case(), _case(label="maybe")), fmt="json")

        assert {e.row for e in result.errors} == {1, 3}

    def test_a_missing_scenario_is_an_error_not_an_empty_case(self):
        """An empty scenario would be scored anyway, producing a verdict about
        nothing at all."""
        result = case_upload.parse(_json(_case(scenario="   ")), fmt="json")

        assert not result.ok

    def test_an_unknown_label_is_refused_rather_than_coerced(self):
        result = case_upload.parse(_json(_case(label="probably-fine")), fmt="json")

        assert not result.ok
        assert "label" in result.errors[0].message

    def test_malformed_json_says_so_instead_of_raising(self):
        result = case_upload.parse("{not json", fmt="json")

        assert not result.ok
        assert "not valid JSON" in result.errors[0].message

    def test_an_empty_file_is_an_error_not_an_empty_suite(self):
        result = case_upload.parse(_json(), fmt="json")

        assert not result.ok

    def test_an_unsupported_format_is_named(self):
        result = case_upload.parse("x", fmt="xlsx")

        assert not result.ok
        assert "xlsx" in result.errors[0].message


class TestDuplicatesAreCollapsedAndCounted:
    def test_the_same_case_twice_becomes_one_case(self):
        """The miner's lesson: a pass rate is only as meaningful as the number
        of DISTINCT questions behind it. 1,645 identical rows cleared the
        aggregate threshold while carrying one decision's worth of information."""
        result = case_upload.parse(_json(_case(), _case(), _case()), fmt="json")

        assert len(result.cases) == 1
        assert result.duplicates_collapsed == 2

    def test_the_collapse_is_reported_so_the_author_learns_what_they_have(self):
        result = case_upload.parse(_json(_case(), _case()), fmt="json")

        assert result.as_dict()["duplicates_collapsed"] == 1
        assert result.as_dict()["accepted"] == 1

    def test_whitespace_and_case_do_not_fake_variety(self):
        result = case_upload.parse(_json(_case(scenario="Public  Bucket"), _case(scenario="public bucket")), fmt="json")

        assert len(result.cases) == 1

    def test_a_different_label_on_the_same_question_is_still_one_question(self):
        result = case_upload.parse(_json(_case(label="good"), _case(label="bad")), fmt="json")

        assert len(result.cases) == 1

    def test_different_inputs_are_genuinely_different_cases(self):
        result = case_upload.parse(_json(_case(prompt_inputs={"a": 1}), _case(prompt_inputs={"a": 2})), fmt="json")

        assert len(result.cases) == 2


class TestLimits:
    def test_a_file_past_the_case_ceiling_is_refused(self):
        payload = _json(*[_case(scenario=f"s{i}") for i in range(case_upload.MAX_CASES + 1)])

        result = case_upload.parse(payload, fmt="json")

        assert not result.ok
        assert str(case_upload.MAX_CASES) in result.errors[0].message

    def test_an_enormous_field_is_refused_with_its_size(self):
        """One pasted log file becomes an agent prompt that costs real money
        every time the suite runs."""
        result = case_upload.parse(
            _json(_case(prompt_inputs={"log": "x" * (case_upload.MAX_FIELD_CHARS + 1)})), fmt="json"
        )

        assert not result.ok
        assert "log" in result.errors[0].message

    def test_too_many_criteria_is_refused(self):
        result = case_upload.parse(
            _json(_case(solution_criteria=[f"c{i}" for i in range(case_upload.MAX_CRITERIA + 1)])), fmt="json"
        )

        assert not result.ok
        assert "checks, not a specification" in result.errors[0].message


class TestCsv:
    def test_a_simple_sheet_parses(self):
        csv_text = "scenario,label\npublic bucket,good\nopen sg,bad\n"

        result = case_upload.parse(csv_text, fmt="csv")

        assert result.ok
        assert len(result.cases) == 2

    def test_unrecognised_columns_become_prompt_inputs_rather_than_being_dropped(self):
        """Dropping them silently discards the context the author added the
        column in order to supply."""
        csv_text = "scenario,severity,asset_urn\npublic bucket,high,arn:aws:s3:::x\n"

        result = case_upload.parse(csv_text, fmt="csv")

        assert result.cases[0].prompt_inputs == {"severity": "high", "asset_urn": "arn:aws:s3:::x"}

    def test_semicolons_split_criteria_the_way_a_spreadsheet_writes_them(self):
        csv_text = "scenario,solution_criteria\npublic bucket,names the bucket;proposes a policy\n"

        result = case_upload.parse(csv_text, fmt="csv")

        assert result.cases[0].solution_criteria == ["names the bucket", "proposes a policy"]

    def test_a_sheet_without_a_scenario_column_says_which_column_is_missing(self):
        result = case_upload.parse("title,severity\na,high\n", fmt="csv")

        assert not result.ok
        assert "scenario" in result.errors[0].message

    def test_a_headerless_file_is_refused(self):
        result = case_upload.parse("", fmt="csv")

        assert not result.ok


class TestTemplate:
    def test_the_template_is_itself_a_valid_upload(self):
        """If the worked example does not round-trip, the first thing every user
        does fails."""
        result = case_upload.parse(json.dumps(case_upload.TEMPLATE), fmt="json")

        assert result.ok
        assert len(result.cases) == 2
