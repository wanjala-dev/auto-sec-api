"""Sample findings for the never-empty HUD (onboarding slice B).

A realistic, clearly-labelled demo dataset so a brand-new workspace isn't a blank
slate — the operator can poke findings/severity/compliance/ATT&CK before connecting
a real cloud. Every row's ``source`` starts with ``sample.`` so the data is trivially
identifiable and one-click clearable, and the HUD shows a "SAMPLE DATA" banner while
any are present. Findings only, workspace-scoped (ADR 0004) — no real assets or
integrations are touched, and seeding never fires FindingRaised events (no triage/
Slack on fake data).
"""

from __future__ import annotations

SAMPLE_SOURCE_PREFIX = "sample."

# compliance["MITRE ATT&CK"] lights up the ATT&CK coverage heatmap; the framework
# tags feed the compliance bars. Severities are spread so the severity ring/counts
# read realistically.
SAMPLE_FINDINGS: tuple[dict, ...] = (
    {
        "source": "sample.cloud_posture",
        "fingerprint": "s3-public-read-acl",
        "asset_urn": "urn:aws:s3:::acme-analytics-exports",
        "severity": "critical",
        "title": "S3 bucket is publicly readable",
        "description": "Bucket 'acme-analytics-exports' grants READ to AllUsers via its ACL — anyone on the internet can list and download objects.",
        "remediation": "Remove the public-read ACL grant and enable S3 Block Public Access at the account level.",
        "compliance": {"CIS-2.0": ["2.1.5"], "PCI-DSS": ["1.2"], "MITRE ATT&CK": ["T1530"]},
    },
    {
        "source": "sample.cloud_posture",
        "fingerprint": "sg-open-ssh-world",
        "asset_urn": "urn:aws:ec2:us-east-1:sg-0a1b2c3d",
        "severity": "critical",
        "title": "Security group allows SSH from 0.0.0.0/0",
        "description": "Security group sg-0a1b2c3d exposes port 22 to the entire internet.",
        "remediation": "Restrict inbound 22/tcp to your bastion/VPN CIDR; prefer SSM Session Manager over open SSH.",
        "compliance": {"CIS-2.0": ["5.2"], "MITRE ATT&CK": ["T1190", "T1021.004"]},
    },
    {
        "source": "sample.iam",
        "fingerprint": "iam-admin-no-mfa",
        "asset_urn": "urn:aws:iam::123456789012:user/ci-deployer",
        "severity": "high",
        "title": "IAM user with AdministratorAccess has no MFA",
        "description": "User 'ci-deployer' holds AdministratorAccess but has no MFA device enrolled.",
        "remediation": "Enforce MFA for all human users; move CI to a scoped role via OIDC instead of a long-lived admin user.",
        "compliance": {"CIS-2.0": ["1.10"], "SOC2": ["CC6.1"], "MITRE ATT&CK": ["T1078.004"]},
    },
    {
        "source": "sample.iam",
        "fingerprint": "iam-access-key-unrotated",
        "asset_urn": "urn:aws:iam::123456789012:user/legacy-svc",
        "severity": "high",
        "title": "Access key older than 180 days",
        "description": "Access key for 'legacy-svc' has not been rotated in 214 days.",
        "remediation": "Rotate the access key and adopt short-lived credentials (STS / IAM Roles Anywhere).",
        "compliance": {"CIS-2.0": ["1.14"], "MITRE ATT&CK": ["T1552.001"]},
    },
    {
        "source": "sample.container_security",
        "fingerprint": "cve-2024-3094-xz",
        "asset_urn": "urn:oci:ecr:acme/api@sha256:9f2c",
        "severity": "critical",
        "title": "CVE-2024-3094 — backdoored xz-utils in image",
        "description": "Image acme/api bundles a compromised liblzma (xz-utils 5.6.0) with a known SSH backdoor.",
        "remediation": "Rebuild on a patched base image (xz >= 5.6.2) and redeploy; rotate any exposed host keys.",
        "compliance": {"MITRE ATT&CK": ["T1195.002", "T1554"]},
    },
    {
        "source": "sample.container_security",
        "fingerprint": "cve-2023-44487-http2",
        "asset_urn": "urn:oci:ecr:acme/gateway@sha256:1a7b",
        "severity": "high",
        "title": "CVE-2023-44487 — HTTP/2 Rapid Reset",
        "description": "Gateway image ships an nginx build vulnerable to the HTTP/2 rapid-reset DoS.",
        "remediation": "Upgrade nginx to a fixed release and cap concurrent streams.",
        "compliance": {"MITRE ATT&CK": ["T1499.004"]},
    },
    {
        "source": "sample.cloud_posture",
        "fingerprint": "rds-unencrypted",
        "asset_urn": "urn:aws:rds:us-east-1:db:acme-prod",
        "severity": "high",
        "title": "RDS instance is not encrypted at rest",
        "description": "Production database 'acme-prod' has storage encryption disabled.",
        "remediation": "Snapshot, copy with encryption enabled, and restore; enforce encryption via SCP.",
        "compliance": {"CIS-2.0": ["2.3.1"], "PCI-DSS": ["3.4"], "SOC2": ["CC6.7"]},
    },
    {
        "source": "sample.cloud_posture",
        "fingerprint": "cloudtrail-not-enabled",
        "asset_urn": "urn:aws:cloudtrail:us-east-1:acme",
        "severity": "medium",
        "title": "CloudTrail is not enabled in all regions",
        "description": "Multi-region CloudTrail logging is off — API activity in secondary regions is invisible.",
        "remediation": "Enable a multi-region trail with log-file validation to a locked-down S3 bucket.",
        "compliance": {"CIS-2.0": ["3.1"], "SOC2": ["CC7.2"], "MITRE ATT&CK": ["T1562.008"]},
    },
    {
        "source": "sample.cloud_posture",
        "fingerprint": "ebs-public-snapshot",
        "asset_urn": "urn:aws:ec2:us-east-1:snapshot/snap-0dead",
        "severity": "high",
        "title": "EBS snapshot is public",
        "description": "Snapshot snap-0dead is shared with all AWS accounts.",
        "remediation": "Set the snapshot permission back to private and audit for data exposure.",
        "compliance": {"MITRE ATT&CK": ["T1530"]},
    },
    {
        "source": "sample.cloud_posture",
        "fingerprint": "kms-key-rotation-off",
        "asset_urn": "urn:aws:kms:us-east-1:key/1234abcd",
        "severity": "medium",
        "title": "KMS key rotation disabled",
        "description": "Customer-managed key 1234abcd does not have annual rotation enabled.",
        "remediation": "Enable automatic key rotation.",
        "compliance": {"CIS-2.0": ["3.8"]},
    },
    {
        "source": "sample.iam",
        "fingerprint": "s3-bucket-no-versioning",
        "asset_urn": "urn:aws:s3:::acme-terraform-state",
        "severity": "medium",
        "title": "Terraform state bucket has no versioning",
        "description": "State bucket lacks versioning — a bad apply can irrecoverably corrupt state.",
        "remediation": "Enable versioning + MFA-delete on the state bucket.",
        "compliance": {"SOC2": ["CC7.2"]},
    },
    {
        "source": "sample.cloud_posture",
        "fingerprint": "lambda-secret-in-env",
        "asset_urn": "urn:aws:lambda:us-east-1:function/acme-webhook",
        "severity": "high",
        "title": "Hard-coded secret in Lambda environment",
        "description": "Function 'acme-webhook' stores a Stripe live key in a plaintext environment variable.",
        "remediation": "Move the secret to Secrets Manager and reference it at runtime.",
        "compliance": {"PCI-DSS": ["3.5"], "MITRE ATT&CK": ["T1552.001"]},
    },
    {
        "source": "sample.container_security",
        "fingerprint": "image-runs-as-root",
        "asset_urn": "urn:oci:ecr:acme/worker@sha256:44ce",
        "severity": "low",
        "title": "Container runs as root",
        "description": "Image acme/worker has no USER directive and runs as uid 0.",
        "remediation": "Add a non-root USER and drop Linux capabilities.",
        "compliance": {"CIS-Docker": ["4.1"]},
    },
    {
        "source": "sample.cloud_posture",
        "fingerprint": "guardduty-disabled",
        "asset_urn": "urn:aws:guardduty:us-east-1:acme",
        "severity": "low",
        "title": "GuardDuty is not enabled",
        "description": "Threat detection (GuardDuty) is off in the primary region.",
        "remediation": "Enable GuardDuty and route findings to your SOC.",
        "compliance": {"SOC2": ["CC7.2"], "MITRE ATT&CK": ["T1562.001"]},
    },
)
