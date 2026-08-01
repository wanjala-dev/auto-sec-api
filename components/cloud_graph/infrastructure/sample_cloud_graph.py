"""Coherent sample cloud environment for demo mode (ADR 0011 Phase 3).

One curated fake AWS account (``123456789012``) whose asset ``asset_urn``s MATCH the
sample findings (``components/findings/infrastructure/sample_findings.py``) so the graph,
map, attack surface, risk gauge, and findings tell ONE consistent story. The set forms a
classic toxic path:

    internet  →  public EC2 (web-01, behind an 0.0.0.0/0 SSH security group)
              →  assumes the over-privileged ``ci-deployer`` IAM user (AdministratorAccess)
              →  which can reach the unencrypted crown-jewel RDS ``acme-prod``.

Plus a public S3 exports bucket (data-exposure), a KMS key, and a Lambda — enough to
light up exposure counts, the resource-type breakdown, and the map. Every row is written
tagged ``is_sample=True`` and torn down by that tag; nothing here is derived from a real
scan and no events fire.

Keys are stable slugs so the seeder can wire edges + attack paths by referencing assets
by key without threading UUIDs through the fixture.
"""

from __future__ import annotations

# ── Assets ────────────────────────────────────────────────────────────────────
# key → dict(arn, asset_urn, resource_type, region, name, exposure, attributes)
SAMPLE_ASSETS: tuple[dict, ...] = (
    {
        "key": "ec2_web",
        "arn": "arn:aws:ec2:us-east-1:123456789012:instance/i-0acme01web",
        "asset_urn": "urn:aws:ec2:us-east-1:i-0acme01web",
        "resource_type": "aws_ec2_instance",
        "region": "us-east-1",
        "name": "acme-web-01",
        "exposure": "public",
        "attributes": {"public_ip": "203.0.113.10", "instance_profile": "acme-ci-deployer"},
    },
    {
        "key": "sg_ssh",
        "arn": "arn:aws:ec2:us-east-1:123456789012:security-group/sg-0a1b2c3d",
        "asset_urn": "urn:aws:ec2:us-east-1:sg-0a1b2c3d",
        "resource_type": "aws_security_group",
        "region": "us-east-1",
        "name": "acme-web-sg",
        "exposure": "public",
        "attributes": {"ingress": [{"port": 22, "cidr": "0.0.0.0/0"}]},
    },
    {
        "key": "iam_ci",
        "arn": "arn:aws:iam::123456789012:user/ci-deployer",
        "asset_urn": "urn:aws:iam::123456789012:user/ci-deployer",
        "resource_type": "aws_iam_user",
        "region": "",
        "name": "ci-deployer",
        "exposure": "internal",
        "attributes": {"managed_policies": ["AdministratorAccess"], "mfa": False},
    },
    {
        "key": "rds_prod",
        "arn": "arn:aws:rds:us-east-1:123456789012:db:acme-prod",
        "asset_urn": "urn:aws:rds:us-east-1:db:acme-prod",
        "resource_type": "aws_rds_instance",
        "region": "us-east-1",
        "name": "acme-prod",
        "exposure": "private",
        "attributes": {"encrypted": False, "engine": "postgres", "crown_jewel": True},
    },
    {
        "key": "s3_exports",
        "arn": "arn:aws:s3:::acme-analytics-exports",
        "asset_urn": "urn:aws:s3:::acme-analytics-exports",
        "resource_type": "aws_s3_bucket",
        "region": "us-east-1",
        "name": "acme-analytics-exports",
        "exposure": "public",
        "attributes": {"public_acl": True, "objects": 41230},
    },
    {
        "key": "kms_key",
        "arn": "arn:aws:kms:us-east-1:123456789012:key/1234abcd",
        "asset_urn": "urn:aws:kms:us-east-1:key/1234abcd",
        "resource_type": "aws_kms_key",
        "region": "us-east-1",
        "name": "acme-data-key",
        "exposure": "private",
        "attributes": {"rotation_enabled": False},
    },
    {
        "key": "lambda_webhook",
        "arn": "arn:aws:lambda:us-east-1:123456789012:function/acme-webhook",
        "asset_urn": "urn:aws:lambda:us-east-1:function/acme-webhook",
        "resource_type": "aws_lambda_function",
        "region": "us-east-1",
        "name": "acme-webhook",
        "exposure": "internal",
        "attributes": {"env_has_secret": True},
    },
)

# ── Edges ─────────────────────────────────────────────────────────────────────
# (src_key, relation, dst_key). Relations are AssetRelation.value.
SAMPLE_EDGES: tuple[tuple[str, str, str], ...] = (
    ("sg_ssh", "allows_ingress_from", "ec2_web"),  # open SG fronts the public instance
    ("ec2_web", "can_assume", "iam_ci"),  # instance profile → admin identity
    ("iam_ci", "has_policy", "rds_prod"),  # admin identity → crown-jewel DB
    ("iam_ci", "reads_bucket", "s3_exports"),  # admin identity → public data bucket
    ("rds_prod", "attached_to", "kms_key"),  # DB → (unrotated) key
    ("lambda_webhook", "reads_table", "rds_prod"),  # webhook fn → DB
)

# ── Attack paths ──────────────────────────────────────────────────────────────
# Seeded DIRECTLY (not via the materialize detector). Each references assets by key;
# the seeder resolves keys → the persisted asset ids/labels/urns and builds the legs.
# category is AttackPathCategory.value.
SAMPLE_ATTACK_PATHS: tuple[dict, ...] = (
    {
        "category": "public_data_exposure",
        "severity": "critical",
        "risk_score": 92.0,
        "entry_key": "ec2_web",
        "target_key": "rds_prod",
        "title": "Internet-exposed web host can reach the unencrypted production database",
        "explanation": (
            "acme-web-01 is publicly reachable (SSH open to 0.0.0.0/0 via sg-0a1b2c3d) and "
            "carries an instance profile that assumes ci-deployer (AdministratorAccess, no MFA), "
            "which can reach the unencrypted crown-jewel RDS acme-prod — a public entry to a "
            "sensitive data store."
        ),
        "leg_keys": ("ec2_web", "iam_ci", "rds_prod"),
    },
    {
        "category": "public_compute_admin",
        "severity": "high",
        "risk_score": 78.0,
        "entry_key": "ec2_web",
        "target_key": "iam_ci",
        "title": "Public compute assumes an administrator identity",
        "explanation": (
            "The internet-facing acme-web-01 can assume ci-deployer, which holds "
            "AdministratorAccess with no MFA — public compute reaching a powerful role."
        ),
        "leg_keys": ("ec2_web", "iam_ci"),
    },
)

# Relation label for a leg when we render entry→…→target legs from the ordered key chain.
# Falls back to a generic "reaches" when a specific edge relation isn't in SAMPLE_EDGES.
_EDGE_RELATION_BY_PAIR = {(s, d): r for (s, r, d) in SAMPLE_EDGES}


def relation_for(src_key: str, dst_key: str) -> str:
    return _EDGE_RELATION_BY_PAIR.get((src_key, dst_key), "reaches")
