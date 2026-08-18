"""Unit — saved-view input validation (task #74). No DB, no framework."""

from __future__ import annotations

import pytest

from components.workspace.application.use_cases.validate_board_view_input import (
    MAX_VIEW_NAME_LENGTH,
    validate_filter_shape,
    validate_group_by,
    validate_name,
    validate_order,
)
from components.workspace.domain.errors import WorkspaceValidationError

pytestmark = pytest.mark.unit


class TestValidateName:
    def test_strips_and_returns(self):
        assert validate_name("  High severity  ") == "High severity"

    @pytest.mark.parametrize("bad", [None, "", "   ", 42, ["x"]])
    def test_rejects_missing_or_non_string(self, bad):
        with pytest.raises(WorkspaceValidationError):
            validate_name(bad)

    def test_rejects_overlong(self):
        with pytest.raises(WorkspaceValidationError):
            validate_name("x" * (MAX_VIEW_NAME_LENGTH + 1))


class TestValidateFilterShape:
    def test_accepts_dict(self):
        assert validate_filter_shape({"min_severity": "high"}) == {"min_severity": "high"}

    @pytest.mark.parametrize("bad", ["a=b", ["a"], 3, None])
    def test_rejects_non_dict(self, bad):
        with pytest.raises(WorkspaceValidationError):
            validate_filter_shape(bad)


class TestValidateGroupBy:
    def test_status_is_the_only_supported_grouping(self):
        assert validate_group_by("status") == "status"
        with pytest.raises(WorkspaceValidationError):
            validate_group_by("assignee")


class TestValidateOrder:
    def test_accepts_ints_and_numeric_strings(self):
        assert validate_order(3) == 3
        assert validate_order("7") == 7
        assert validate_order(-1) == -1

    @pytest.mark.parametrize("bad", ["junk", None, True, 1.5, {}])
    def test_rejects_non_integers(self, bad):
        with pytest.raises(WorkspaceValidationError):
            validate_order(bad)
