"""Unit tests for the workflow condition predicate evaluator (pure domain)."""

from __future__ import annotations

import pytest

from components.workflow.domain.errors import WorkflowConditionError
from components.workflow.domain.services.condition_evaluator import evaluate_condition


class TestEmptyAndShape:
    def test_empty_predicate_passes(self):
        assert evaluate_condition(None, {}) is True
        assert evaluate_condition({}, {}) is True
        assert evaluate_condition({"conditions": []}, {}) is True

    def test_bare_single_condition(self):
        ctx = {"amount": 750}
        assert evaluate_condition({"field": "amount", "op": "gte", "value": 500}, ctx) is True

    def test_malformed_predicate_raises(self):
        with pytest.raises(WorkflowConditionError):
            evaluate_condition({"conditions": "nope"}, {})
        with pytest.raises(WorkflowConditionError):
            evaluate_condition({"match": "xor", "conditions": [{"field": "a", "op": "eq", "value": 1}]}, {"a": 1})
        with pytest.raises(WorkflowConditionError):
            evaluate_condition({"conditions": [{"op": "eq", "value": 1}]}, {})  # no field


class TestNumericOps:
    @pytest.mark.parametrize(
        "op,value,expected",
        [
            ("gte", 500, True),
            ("gt", 750, False),
            ("lte", 750, True),
            ("lt", 1000, True),
            ("eq", 750, True),
            ("ne", 100, True),
        ],
    )
    def test_numeric(self, op, value, expected):
        assert evaluate_condition({"field": "amount", "op": op, "value": value}, {"amount": 750}) is expected

    def test_between(self):
        assert evaluate_condition({"field": "score", "op": "between", "value": [0, 30]}, {"score": 12}) is True
        assert evaluate_condition({"field": "score", "op": "between", "value": [0, 30]}, {"score": 80}) is False

    def test_string_number_coercion(self):
        # Donation amounts often arrive as strings in the payload.
        assert evaluate_condition({"field": "amount", "op": "gte", "value": "500"}, {"amount": "750.00"}) is True


class TestMembershipAndContains:
    def test_in_not_in(self):
        ctx = {"campaign_id": "eoy"}
        assert evaluate_condition({"field": "campaign_id", "op": "in", "value": ["eoy", "spring"]}, ctx) is True
        assert evaluate_condition({"field": "campaign_id", "op": "not_in", "value": ["spring"]}, ctx) is True

    def test_tags_contains(self):
        ctx = {"contact": {"tags": ["Major Donor", "Volunteers"]}}
        assert evaluate_condition({"field": "contact.tags", "op": "contains", "value": "Volunteers"}, ctx) is True
        assert evaluate_condition({"field": "contact.tags", "op": "not_contains", "value": "Staff"}, ctx) is True
        assert evaluate_condition({"field": "contact.tags", "op": "contains", "value": "Staff"}, ctx) is False


class TestPresenceAndMissing:
    def test_is_set_is_empty(self):
        assert evaluate_condition({"field": "email", "op": "is_set", "value": None}, {"email": "a@b.co"}) is True
        assert evaluate_condition({"field": "email", "op": "is_empty", "value": None}, {"email": ""}) is True
        assert evaluate_condition({"field": "email", "op": "is_empty", "value": None}, {}) is True

    def test_missing_field_comparison_is_false(self):
        # A real comparison against a missing field can't match.
        assert evaluate_condition({"field": "amount", "op": "gte", "value": 1}, {}) is False


class TestMatchModes:
    def test_all_and_any(self):
        ctx = {"amount": 750, "contact": {"tags": ["Major Donor"]}}
        pred_all = {
            "match": "all",
            "conditions": [
                {"field": "amount", "op": "gte", "value": 500},
                {"field": "contact.tags", "op": "not_contains", "value": "Staff"},
            ],
        }
        assert evaluate_condition(pred_all, ctx) is True

        pred_any = {
            "match": "any",
            "conditions": [
                {"field": "amount", "op": "gte", "value": 10000},  # false
                {"field": "contact.tags", "op": "contains", "value": "Major Donor"},  # true
            ],
        }
        assert evaluate_condition(pred_any, ctx) is True

        pred_all_fail = {
            "match": "all",
            "conditions": [
                {"field": "amount", "op": "gte", "value": 10000},
                {"field": "contact.tags", "op": "contains", "value": "Major Donor"},
            ],
        }
        assert evaluate_condition(pred_all_fail, ctx) is False
