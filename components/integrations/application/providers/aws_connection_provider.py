"""Composition root for AWS organization onboarding.

The only application-layer file that knows the concrete STS adapter,
repository, and vendor-account resolver exist (provider files are the
allowed composition-root slot for own-context infrastructure imports).
Controllers resolve their dependencies here and stay ORM/SDK-free.
"""

from __future__ import annotations

from components.integrations.application.aws_connection_service import AwsConnectionService
from components.integrations.application.use_cases.generate_onboarding_template_use_case import (
    GenerateOnboardingTemplateUseCase,
)


def get_aws_connection_service() -> AwsConnectionService:
    from components.integrations.infrastructure.adapters.sts_org_adapter import StsOrgAdapter
    from components.integrations.infrastructure.repositories.aws_connection_repository import (
        AwsConnectionRepository,
    )

    return AwsConnectionService(_repo=AwsConnectionRepository(), _verifier=StsOrgAdapter())


def get_onboarding_template_use_case() -> GenerateOnboardingTemplateUseCase:
    from components.integrations.infrastructure.adapters.vendor_account_adapter import (
        resolve_vendor_account_id,
    )

    return GenerateOnboardingTemplateUseCase(_vendor_account_resolver=resolve_vendor_account_id)
