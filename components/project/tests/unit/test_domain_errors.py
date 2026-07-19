"""Unit tests for project domain errors.

Tests error hierarchy, inheritance, and proper error instantiation.
"""

from components.project.domain.errors import (
    ProjectError,
    ProjectNotFoundError,
    ColumnNotFoundError,
    TaskNotFoundError,
    TaskValidationError,
    TaskLimitExceededError,
    ProjectLimitExceededError,
    BudgetRequiredError,
    TeamNotFoundError,
    TeamMembershipRequiredError,
    WorkspaceMembershipRequiredError,
)
from components.shared_kernel.domain.errors import (
    DomainError,
    ValidationError,
    NotFoundError,
    AuthorizationError,
)


class TestProjectErrorHierarchy:
    """Test error class hierarchy and inheritance."""

    def test_project_error_is_domain_error(self):
        """ProjectError should extend DomainError."""
        error = ProjectError("test")
        assert isinstance(error, DomainError)
        assert isinstance(error, Exception)

    def test_project_error_can_be_instantiated(self):
        """ProjectError should be instantiable with a message."""
        message = "A project error occurred"
        error = ProjectError(message)
        assert str(error) == message

    def test_project_error_empty_message(self):
        """ProjectError should handle empty messages."""
        error = ProjectError()
        assert isinstance(error, ProjectError)


class TestNotFoundErrors:
    """Test not-found error variants."""

    def test_project_not_found_error_inherits_properly(self):
        """ProjectNotFoundError should extend both ProjectError and NotFoundError."""
        error = ProjectNotFoundError("Project not found")
        assert isinstance(error, ProjectError)
        assert isinstance(error, NotFoundError)
        assert isinstance(error, DomainError)
        assert isinstance(error, LookupError)

    def test_column_not_found_error_inherits_properly(self):
        """ColumnNotFoundError should extend both ProjectError and NotFoundError."""
        error = ColumnNotFoundError("Column 123 not found")
        assert isinstance(error, ProjectError)
        assert isinstance(error, NotFoundError)
        assert isinstance(error, DomainError)

    def test_task_not_found_error_inherits_properly(self):
        """TaskNotFoundError should extend both ProjectError and NotFoundError."""
        error = TaskNotFoundError("Task 456 not found")
        assert isinstance(error, ProjectError)
        assert isinstance(error, NotFoundError)
        assert isinstance(error, DomainError)

    def test_team_not_found_error_inherits_properly(self):
        """TeamNotFoundError should extend both ProjectError and NotFoundError."""
        error = TeamNotFoundError("Team not found")
        assert isinstance(error, ProjectError)
        assert isinstance(error, NotFoundError)
        assert isinstance(error, DomainError)

    def test_not_found_errors_are_catchable_as_lookup_error(self):
        """NotFound errors should be catchable as LookupError."""
        errors = [
            ProjectNotFoundError(),
            ColumnNotFoundError(),
            TaskNotFoundError(),
            TeamNotFoundError(),
        ]
        for error in errors:
            assert isinstance(error, LookupError)


class TestValidationErrors:
    """Test validation error variants."""

    def test_task_validation_error_inherits_properly(self):
        """TaskValidationError should extend both ProjectError and ValidationError."""
        error = TaskValidationError("Invalid task data")
        assert isinstance(error, ProjectError)
        assert isinstance(error, ValidationError)
        assert isinstance(error, DomainError)
        assert isinstance(error, ValueError)

    def test_task_limit_exceeded_error_inherits_properly(self):
        """TaskLimitExceededError should extend both ProjectError and ValidationError."""
        error = TaskLimitExceededError("Task limit exceeded")
        assert isinstance(error, ProjectError)
        assert isinstance(error, ValidationError)
        assert isinstance(error, DomainError)

    def test_project_limit_exceeded_error_inherits_properly(self):
        """ProjectLimitExceededError should extend both ProjectError and ValidationError."""
        error = ProjectLimitExceededError("Project limit exceeded")
        assert isinstance(error, ProjectError)
        assert isinstance(error, ValidationError)
        assert isinstance(error, DomainError)

    def test_budget_required_error_inherits_properly(self):
        """BudgetRequiredError should extend both ProjectError and ValidationError."""
        error = BudgetRequiredError("Budget required")
        assert isinstance(error, ProjectError)
        assert isinstance(error, ValidationError)
        assert isinstance(error, DomainError)

    def test_validation_errors_are_catchable_as_value_error(self):
        """Validation errors should be catchable as ValueError."""
        errors = [
            TaskValidationError(),
            TaskLimitExceededError(),
            ProjectLimitExceededError(),
            BudgetRequiredError(),
        ]
        for error in errors:
            assert isinstance(error, ValueError)


class TestAuthorizationErrors:
    """Test authorization error variants."""

    def test_team_membership_required_error_inherits_properly(self):
        """TeamMembershipRequiredError should extend both ProjectError and AuthorizationError."""
        error = TeamMembershipRequiredError("User not a team member")
        assert isinstance(error, ProjectError)
        assert isinstance(error, AuthorizationError)
        assert isinstance(error, DomainError)

    def test_workspace_membership_required_error_inherits_properly(self):
        """WorkspaceMembershipRequiredError should extend both ProjectError and AuthorizationError."""
        error = WorkspaceMembershipRequiredError("User not a workspace member")
        assert isinstance(error, ProjectError)
        assert isinstance(error, AuthorizationError)
        assert isinstance(error, DomainError)


class TestErrorMessages:
    """Test error message handling."""

    def test_error_preserves_message(self):
        """Errors should preserve their message text."""
        messages = [
            "Project 123 not found",
            "Column XYZ not found",
            "Task limit exceeded for plan",
            "Budget required for operation",
            "User not a team member",
        ]
        error_classes = [
            ProjectNotFoundError,
            ColumnNotFoundError,
            TaskLimitExceededError,
            BudgetRequiredError,
            TeamMembershipRequiredError,
        ]
        for ErrorClass, message in zip(error_classes, messages):
            error = ErrorClass(message)
            assert str(error) == message

    def test_error_without_message(self):
        """Errors should be instantiable without a message."""
        error_classes = [
            ProjectError,
            ProjectNotFoundError,
            ColumnNotFoundError,
            TaskNotFoundError,
            TaskValidationError,
            TaskLimitExceededError,
            ProjectLimitExceededError,
            BudgetRequiredError,
            TeamNotFoundError,
            TeamMembershipRequiredError,
            WorkspaceMembershipRequiredError,
        ]
        for ErrorClass in error_classes:
            error = ErrorClass()
            assert isinstance(error, ProjectError)

    def test_error_with_multiple_args(self):
        """Errors should handle multiple arguments."""
        error = ProjectNotFoundError("Project", "123", "not found")
        # All args should be captured
        assert error.args == ("Project", "123", "not found")


class TestErrorCatchBlocks:
    """Test typical error catch block patterns."""

    def test_catch_specific_errors(self):
        """Can catch specific error types."""
        try:
            raise ProjectNotFoundError("Project 123")
        except ProjectNotFoundError as e:
            assert "123" in str(e)

    def test_catch_project_error_catches_all_project_errors(self):
        """ProjectError catch block should catch all project-specific errors."""
        errors = [
            ProjectNotFoundError(),
            ColumnNotFoundError(),
            TaskNotFoundError(),
            TaskValidationError(),
            TaskLimitExceededError(),
            ProjectLimitExceededError(),
            BudgetRequiredError(),
            TeamNotFoundError(),
            TeamMembershipRequiredError(),
            WorkspaceMembershipRequiredError(),
        ]
        for error in errors:
            try:
                raise error
            except ProjectError:
                pass  # Should catch all

    def test_catch_not_found_error_catches_lookup_errors(self):
        """NotFoundError catch block should catch lookup errors."""
        errors = [
            ProjectNotFoundError(),
            ColumnNotFoundError(),
            TaskNotFoundError(),
            TeamNotFoundError(),
        ]
        for error in errors:
            try:
                raise error
            except NotFoundError:
                pass  # Should catch all

    def test_catch_validation_error_catches_value_errors(self):
        """ValidationError catch block should catch value errors."""
        errors = [
            TaskValidationError(),
            TaskLimitExceededError(),
            ProjectLimitExceededError(),
            BudgetRequiredError(),
        ]
        for error in errors:
            try:
                raise error
            except ValueError:
                pass  # Should catch all

    def test_catch_authorization_error_catches_auth_errors(self):
        """AuthorizationError catch block should catch auth errors."""
        errors = [
            TeamMembershipRequiredError(),
            WorkspaceMembershipRequiredError(),
        ]
        for error in errors:
            try:
                raise error
            except AuthorizationError:
                pass  # Should catch all
