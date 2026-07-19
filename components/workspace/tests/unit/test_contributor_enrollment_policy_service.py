from __future__ import annotations

from components.workspace.domain.policies.contributor_enrollment_policy_service import (
    ContributorEnrollmentPolicyService,
)


def test_should_mark_contributor_requires_flag_and_missing_role():
    service = ContributorEnrollmentPolicyService()

    assert service.should_mark_contributor(
        mark_contributor=True,
        is_contributor=False,
    ) is True
    assert service.should_mark_contributor(
        mark_contributor=False,
        is_contributor=False,
    ) is False
    assert service.should_mark_contributor(
        mark_contributor=True,
        is_contributor=True,
    ) is False
