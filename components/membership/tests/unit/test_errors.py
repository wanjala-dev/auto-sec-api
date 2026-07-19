"""Unit tests for membership domain errors."""

from __future__ import annotations

import pytest

from components.membership.domain.errors import (
    InsufficientRoleError,
    InvitationAlreadyAcceptedError,
    InvitationExpiredError,
    InvitationNotFoundError,
    MembershipConflictError,
    MembershipError,
    MembershipNotFoundError,
    MembershipValidationError,
    TeamMembershipRequiredError,
    WorkspaceMembershipRequiredError,
)
from components.shared_kernel.domain.errors import (
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)


class TestMembershipError:
    """Tests for MembershipError base class."""

    def test_membership_error_is_domain_error(self) -> None:
        """Test that MembershipError is a DomainError."""
        error = MembershipError("Test error")
        assert isinstance(error, Exception)

    def test_membership_error_can_be_raised(self) -> None:
        """Test that MembershipError can be raised and caught."""
        with pytest.raises(MembershipError) as exc_info:
            raise MembershipError("Test message")

        assert str(exc_info.value) == "Test message"

    def test_membership_error_with_empty_message(self) -> None:
        """Test that MembershipError works with empty message."""
        error = MembershipError("")
        assert str(error) == ""


class TestMembershipNotFoundError:
    """Tests for MembershipNotFoundError."""

    def test_is_membership_error(self) -> None:
        """Test that MembershipNotFoundError is a MembershipError."""
        error = MembershipNotFoundError("Not found")
        assert isinstance(error, MembershipError)

    def test_is_not_found_error(self) -> None:
        """Test that MembershipNotFoundError is a NotFoundError."""
        error = MembershipNotFoundError("Not found")
        assert isinstance(error, NotFoundError)

    def test_can_be_raised_and_caught_as_membership_error(self) -> None:
        """Test that error can be caught as MembershipError."""
        with pytest.raises(MembershipError):
            raise MembershipNotFoundError("Membership not found")

    def test_can_be_raised_and_caught_as_not_found_error(self) -> None:
        """Test that error can be caught as NotFoundError."""
        with pytest.raises(NotFoundError):
            raise MembershipNotFoundError("Membership not found")

    def test_message_is_preserved(self) -> None:
        """Test that error message is preserved."""
        msg = "Membership ID 123 not found in workspace XYZ"
        with pytest.raises(MembershipNotFoundError) as exc_info:
            raise MembershipNotFoundError(msg)

        assert str(exc_info.value) == msg


class TestInvitationNotFoundError:
    """Tests for InvitationNotFoundError."""

    def test_is_membership_error(self) -> None:
        """Test that InvitationNotFoundError is a MembershipError."""
        error = InvitationNotFoundError("Not found")
        assert isinstance(error, MembershipError)

    def test_is_not_found_error(self) -> None:
        """Test that InvitationNotFoundError is a NotFoundError."""
        error = InvitationNotFoundError("Not found")
        assert isinstance(error, NotFoundError)

    def test_error_hierarchy(self) -> None:
        """Test the full error hierarchy."""
        error = InvitationNotFoundError("Test")
        assert isinstance(error, InvitationNotFoundError)
        assert isinstance(error, MembershipError)
        assert isinstance(error, NotFoundError)


class TestInvitationExpiredError:
    """Tests for InvitationExpiredError."""

    def test_is_membership_error(self) -> None:
        """Test that InvitationExpiredError is a MembershipError."""
        error = InvitationExpiredError("Expired")
        assert isinstance(error, MembershipError)

    def test_is_validation_error(self) -> None:
        """Test that InvitationExpiredError is a ValidationError."""
        error = InvitationExpiredError("Expired")
        assert isinstance(error, ValidationError)

    def test_error_hierarchy(self) -> None:
        """Test the full error hierarchy."""
        error = InvitationExpiredError("Test")
        assert isinstance(error, InvitationExpiredError)
        assert isinstance(error, MembershipError)
        assert isinstance(error, ValidationError)


class TestInvitationAlreadyAcceptedError:
    """Tests for InvitationAlreadyAcceptedError."""

    def test_is_membership_error(self) -> None:
        """Test that InvitationAlreadyAcceptedError is a MembershipError."""
        error = InvitationAlreadyAcceptedError("Already accepted")
        assert isinstance(error, MembershipError)

    def test_is_conflict_error(self) -> None:
        """Test that InvitationAlreadyAcceptedError is a ConflictError."""
        error = InvitationAlreadyAcceptedError("Already accepted")
        assert isinstance(error, ConflictError)

    def test_error_hierarchy(self) -> None:
        """Test the full error hierarchy."""
        error = InvitationAlreadyAcceptedError("Test")
        assert isinstance(error, InvitationAlreadyAcceptedError)
        assert isinstance(error, MembershipError)
        assert isinstance(error, ConflictError)


class TestInsufficientRoleError:
    """Tests for InsufficientRoleError."""

    def test_is_membership_error(self) -> None:
        """Test that InsufficientRoleError is a MembershipError."""
        error = InsufficientRoleError("Insufficient role")
        assert isinstance(error, MembershipError)

    def test_is_authorization_error(self) -> None:
        """Test that InsufficientRoleError is an AuthorizationError."""
        error = InsufficientRoleError("Insufficient role")
        assert isinstance(error, AuthorizationError)

    def test_error_hierarchy(self) -> None:
        """Test the full error hierarchy."""
        error = InsufficientRoleError("Test")
        assert isinstance(error, InsufficientRoleError)
        assert isinstance(error, MembershipError)
        assert isinstance(error, AuthorizationError)


class TestWorkspaceMembershipRequiredError:
    """Tests for WorkspaceMembershipRequiredError."""

    def test_is_membership_error(self) -> None:
        """Test that WorkspaceMembershipRequiredError is a MembershipError."""
        error = WorkspaceMembershipRequiredError("Not a member")
        assert isinstance(error, MembershipError)

    def test_is_authorization_error(self) -> None:
        """Test that WorkspaceMembershipRequiredError is an AuthorizationError."""
        error = WorkspaceMembershipRequiredError("Not a member")
        assert isinstance(error, AuthorizationError)

    def test_error_hierarchy(self) -> None:
        """Test the full error hierarchy."""
        error = WorkspaceMembershipRequiredError("Test")
        assert isinstance(error, WorkspaceMembershipRequiredError)
        assert isinstance(error, MembershipError)
        assert isinstance(error, AuthorizationError)


class TestTeamMembershipRequiredError:
    """Tests for TeamMembershipRequiredError."""

    def test_is_membership_error(self) -> None:
        """Test that TeamMembershipRequiredError is a MembershipError."""
        error = TeamMembershipRequiredError("Not a team member")
        assert isinstance(error, MembershipError)

    def test_is_authorization_error(self) -> None:
        """Test that TeamMembershipRequiredError is an AuthorizationError."""
        error = TeamMembershipRequiredError("Not a team member")
        assert isinstance(error, AuthorizationError)

    def test_error_hierarchy(self) -> None:
        """Test the full error hierarchy."""
        error = TeamMembershipRequiredError("Test")
        assert isinstance(error, TeamMembershipRequiredError)
        assert isinstance(error, MembershipError)
        assert isinstance(error, AuthorizationError)


class TestMembershipValidationError:
    """Tests for MembershipValidationError."""

    def test_is_membership_error(self) -> None:
        """Test that MembershipValidationError is a MembershipError."""
        error = MembershipValidationError("Invalid")
        assert isinstance(error, MembershipError)

    def test_is_validation_error(self) -> None:
        """Test that MembershipValidationError is a ValidationError."""
        error = MembershipValidationError("Invalid")
        assert isinstance(error, ValidationError)

    def test_error_hierarchy(self) -> None:
        """Test the full error hierarchy."""
        error = MembershipValidationError("Test")
        assert isinstance(error, MembershipValidationError)
        assert isinstance(error, MembershipError)
        assert isinstance(error, ValidationError)


class TestMembershipConflictError:
    """Tests for MembershipConflictError."""

    def test_is_membership_error(self) -> None:
        """Test that MembershipConflictError is a MembershipError."""
        error = MembershipConflictError("Conflict")
        assert isinstance(error, MembershipError)

    def test_is_conflict_error(self) -> None:
        """Test that MembershipConflictError is a ConflictError."""
        error = MembershipConflictError("Conflict")
        assert isinstance(error, ConflictError)

    def test_error_hierarchy(self) -> None:
        """Test the full error hierarchy."""
        error = MembershipConflictError("Test")
        assert isinstance(error, MembershipConflictError)
        assert isinstance(error, MembershipError)
        assert isinstance(error, ConflictError)


class TestErrorChaining:
    """Tests for error chaining and cause."""

    def test_error_with_cause(self) -> None:
        """Test that errors can be chained with __cause__."""
        try:
            try:
                raise ValueError("Original error")
            except ValueError as e:
                raise MembershipError("Membership error") from e
        except MembershipError as e:
            assert isinstance(e.__cause__, ValueError)
            assert str(e.__cause__) == "Original error"

    def test_error_with_context(self) -> None:
        """Test that errors can be chained with __context__."""
        try:
            try:
                raise ValueError("Original error")
            except ValueError:
                raise MembershipError("Membership error")
        except MembershipError as e:
            assert isinstance(e.__context__, ValueError)
            assert str(e.__context__) == "Original error"
