from __future__ import annotations


class ContributorEnrollmentPolicyService:
    def should_mark_contributor(
        self,
        *,
        mark_contributor: bool,
        is_contributor: bool,
    ) -> bool:
        return mark_contributor and not is_contributor
