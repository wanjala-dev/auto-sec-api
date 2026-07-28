"""The onboarding template generator: the hosted (parameterized) CloudFormation +
the one-click quick-create launch URL. Pure document generation — no DB, no network."""

from __future__ import annotations

from types import SimpleNamespace

from components.integrations.application.use_cases.generate_onboarding_template_use_case import (
    GenerateOnboardingTemplateUseCase,
)

_VENDOR = "111122223333"
_CONN = SimpleNamespace(
    id="c0ffee00-0000-4000-8000-000000000001",
    role_name="AutoSecAuditRole",
    external_id="autosec-abc123def456",
    org_wide=False,
    regions=["eu-west-1"],
)


def _use_case(template_url=""):
    return GenerateOnboardingTemplateUseCase(
        _vendor_account_resolver=lambda: _VENDOR,
        _template_url_resolver=lambda: template_url,
    )


def test_launch_url_is_none_without_a_hosted_template():
    assert _use_case(template_url="").launch_url(_CONN) is None


def test_launch_url_builds_a_quickcreate_link_with_prefilled_external_id():
    url = "https://autosec-cfn.s3.us-east-1.amazonaws.com/audit-role.yaml"
    got = _use_case(template_url=url).launch_url(_CONN, region="eu-west-1")

    assert got.startswith("https://console.aws.amazon.com/cloudformation/home?region=eu-west-1#/stacks/quickcreate?")
    # the S3 templateURL is url-encoded into the query
    assert "templateURL=https%3A%2F%2Fautosec-cfn.s3.us-east-1.amazonaws.com%2Faudit-role.yaml" in got
    # the connection's External ID is prefilled via param_ExternalId
    assert "param_ExternalId=autosec-abc123def456" in got
    assert "param_RoleName=AutoSecAuditRole" in got
    assert "stackName=AutoSecAuditRole" in got


def test_hosted_template_parameterizes_the_external_id():
    tmpl = _use_case().hosted_cloudformation()

    # ExternalId is a CloudFormation Parameter (so the quick-create URL can prefill it) …
    assert "ExternalId" in tmpl["Parameters"]
    assert tmpl["Parameters"]["ExternalId"]["Type"] == "String"
    # … and the trust policy references it, not a baked value.
    trust = tmpl["Resources"]["AutoSecAuditRole"]["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]
    assert trust["Condition"]["StringEquals"]["sts:ExternalId"] == {"Ref": "ExternalId"}
    # the vendor principal is still baked (one hosted template, our account) …
    assert trust["Principal"]["AWS"] == f"arn:aws:iam::{_VENDOR}:root"
    # … and it stays single-account (no org StackSet in the hosted template).
    assert "AutoSecOrgStackSet" not in tmpl["Resources"]
