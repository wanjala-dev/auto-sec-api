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
    role_name="FauraAuditRole",
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
    assert "param_RoleName=FauraAuditRole" in got
    assert "stackName=FauraAuditRole" in got


def test_hosted_template_parameterizes_the_external_id():
    tmpl = _use_case().hosted_cloudformation()

    # ExternalId is a CloudFormation Parameter (so the quick-create URL can prefill it) …
    assert "ExternalId" in tmpl["Parameters"]
    assert tmpl["Parameters"]["ExternalId"]["Type"] == "String"
    # … and the trust policy references it, not a baked value.
    trust = tmpl["Resources"]["AuditRole"]["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]
    assert trust["Condition"]["StringEquals"]["sts:ExternalId"] == {"Ref": "ExternalId"}
    # the vendor principal is still baked (one hosted template, our account) …
    assert trust["Principal"]["AWS"] == f"arn:aws:iam::{_VENDOR}:root"
    # … and it stays single-account (no org StackSet in the hosted template).
    assert "OrgAuditStackSet" not in tmpl["Resources"]


# ── workspace-derived naming (Henry, 2026-08-18: nothing vendor-hardcoded in the role) ──


def _faura_conn(**over):
    base = dict(
        id="c0ffee00-0000-4000-8000-000000000002",
        role_name="FauraAuditRole",
        external_id="faura-tok123456789",
        org_wide=False,
        regions=[],
        workspace=SimpleNamespace(workspace_name="Faura"),
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_cloudformation_carries_no_vendor_branding_and_names_from_the_workspace():
    tmpl = _use_case().cloudformation(_faura_conn())

    assert "AuditRole" in tmpl["Resources"]
    policy = tmpl["Resources"]["AuditRole"]["Properties"]["Policies"][0]
    assert policy["PolicyName"] == "FauraAuditReadOnly"
    # NOTHING vendor-branded anywhere in the document — the single allowed
    # occurrence is the functional aws:ResourceTag/autosec tag-contract key.
    import json as _json

    doc = _json.dumps(tmpl)
    assert doc.replace("aws:ResourceTag/autosec", "").lower().count("autosec") == 0
    assert "AutoSec" not in doc.replace("aws:ResourceTag/autosec", "")


def test_org_wide_stackset_is_named_from_the_workspace():
    tmpl = _use_case().cloudformation(_faura_conn(org_wide=True))

    stackset = tmpl["Resources"]["OrgAuditStackSet"]["Properties"]
    assert stackset["StackSetName"] == "faura-audit-c0ffee00"


def test_terraform_labels_and_policy_are_workspace_named_not_vendor_named():
    tf = _use_case().terraform(_faura_conn())

    assert 'resource "aws_iam_role" "audit"' in tf
    assert 'name = "FauraAuditReadOnly"' in tf
    assert 'output "audit_role_arn"' in tf
    assert "autosec_audit" not in tf
    assert tf.replace('"aws:ResourceTag/autosec"', "").lower().count("autosec") == 0


def test_role_stays_read_only_managed_policies():
    """The read-only guarantee: SecurityAudit + ViewOnlyAccess, and the only
    non-Get/List/Describe inline action is sqs:DeleteMessage gated to the
    autosec-tagged CloudTrail queue (the log-delivery contract)."""
    tmpl = _use_case().cloudformation(_faura_conn())
    props = tmpl["Resources"]["AuditRole"]["Properties"]

    assert props["ManagedPolicyArns"] == [
        "arn:aws:iam::aws:policy/SecurityAudit",
        "arn:aws:iam::aws:policy/job-function/ViewOnlyAccess",
    ]
    for stmt in props["Policies"][0]["PolicyDocument"]["Statement"]:
        for action in stmt["Action"]:
            if action == "sqs:DeleteMessage":
                assert stmt["Condition"] == {"StringLike": {"aws:ResourceTag/autosec": "*"}}
            else:
                verb = action.split(":")[1]
                assert verb.startswith(("Get", "List", "Describe", "Receive", "Decrypt")), action
