"""Boto3 inventory adapter — the rich, relationship-aware ``AssetInventoryPort``.

Where the finding-derived adapter gives nodes only (Prowler findings name resources,
not relationships), this one calls the AWS APIs read-only (via the customer's audit
role, reused from the CSPM creds seam) and emits the **typed edges** the
``AttackPathAnalyzer`` walks — so a PUBLIC workload → privileged role → admin policy /
data store becomes a ranked attack path.

Slice 1 (toxic-path core): EC2 instances (entries), IAM roles + instance-profiles +
policies (privilege sinks), S3 buckets (data sinks), and the edges linking them
(ATTACHED_TO / CAN_ASSUME / HAS_POLICY / READS_BUCKET). Full network reachability
(subnets / route-tables / IGW topology) and multi-region breadth are later slices.

Driven adapter (Rule 5): shaped to the core's ``sync_workspace`` need. Cross-context
access goes ONLY through ``integrations.application.ports.AwsAccountAccessPort`` — never
integrations' models. Every AWS call is best-effort: one service failing (or a partial
permission) degrades coverage, never the whole sync.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from urllib.parse import unquote
from uuid import UUID, uuid4

from django.utils import timezone

from components.cloud_graph.application.ports.asset_inventory_port import AssetInventoryPort, AssetSyncResult
from components.cloud_graph.domain.entities.cloud_asset_edge_entity import CloudAssetEdgeEntity
from components.cloud_graph.domain.entities.cloud_asset_entity import CloudAssetEntity
from components.cloud_graph.domain.value_objects.enums import AssetRelation, Exposure

logger = logging.getLogger(__name__)

# EC2 is regional; IAM + S3 are global. Slice 1 scans a small default region set (the
# demo lives in us-east-1); override with a comma list. Multi-region breadth is a follow-up.
_DEFAULT_REGIONS = tuple(
    r.strip() for r in os.environ.get("AUTOSEC_INVENTORY_REGIONS", "us-east-1").split(",") if r.strip()
)


def _default_session_factory(creds: dict):
    import boto3

    return boto3.Session(
        aws_access_key_id=creds.get("AccessKeyId"),
        aws_secret_access_key=creds.get("SecretAccessKey"),
        aws_session_token=creds.get("SessionToken"),
    )


@dataclass(frozen=True)
class _Edge:
    src_arn: str
    dst_arn: str
    relation: AssetRelation


class Boto3InventoryAdapter(AssetInventoryPort):
    def __init__(self, *, access_port=None, asset_store=None, session_factory=None, regions=None):
        self._access_port = access_port
        self._asset_store = asset_store
        self._session_factory = session_factory or _default_session_factory
        self._regions = tuple(regions) if regions else _DEFAULT_REGIONS

    def _deps(self):
        access = self._access_port
        store = self._asset_store
        if access is None:
            from components.integrations.application.providers.aws_account_access_provider import (
                get_aws_account_access_port,
            )

            access = get_aws_account_access_port()
        if store is None:
            from components.cloud_graph.application.providers.cloud_graph_provider import CloudGraphProvider

            store = CloudGraphProvider.build_cloud_asset_store()
        return access, store

    def sync_workspace(self, workspace_id: UUID) -> AssetSyncResult:
        access, store = self._deps()
        accounts = access.accounts_for(str(workspace_id))
        now = timezone.now()
        total_assets = 0
        total_edges = 0

        for account_id in accounts:
            try:
                creds = access.credentials_for(
                    workspace_id=str(workspace_id), account_id=account_id, session_name="autosec-inventory"
                )
                session = self._session_factory(creds)
            except Exception:
                logger.exception("boto3_inventory assume-role failed workspace=%s account=%s", workspace_id, account_id)
                continue

            assets, edges = self._collect(workspace_id, account_id, session, now)

            arn_to_id: dict[str, UUID] = {}
            for asset in assets:
                try:
                    persisted = store.upsert_asset(asset)
                    arn_to_id[asset.arn] = persisted.id
                except Exception:
                    logger.exception("boto3_inventory upsert_asset failed arn=%s", asset.arn)
            total_assets += len(arn_to_id)

            for edge in edges:
                src, dst = arn_to_id.get(edge.src_arn), arn_to_id.get(edge.dst_arn)
                if not src or not dst or src == dst:
                    continue
                try:
                    store.upsert_edge(
                        CloudAssetEdgeEntity(
                            id=uuid4(),
                            workspace_id=workspace_id,
                            src_asset_id=src,
                            dst_asset_id=dst,
                            relation=edge.relation,
                            last_seen_at=now,
                        )
                    )
                    total_edges += 1
                except Exception:
                    logger.exception("boto3_inventory upsert_edge failed %s->%s", edge.src_arn, edge.dst_arn)

        logger.info(
            "boto3_inventory synced workspace=%s accounts=%d assets=%d edges=%d",
            workspace_id,
            len(accounts),
            total_assets,
            total_edges,
        )
        return AssetSyncResult(
            workspace_id=workspace_id, assets_upserted=total_assets, findings_scanned=0, edges_upserted=total_edges
        )

    # ── collection ──────────────────────────────────────────────────────────

    def _collect(self, workspace_id, account_id, session, now):
        assets: list[CloudAssetEntity] = []
        edges: list[_Edge] = []
        seen_arns: set[str] = set()

        def add(asset: CloudAssetEntity):
            if asset.arn not in seen_arns:
                seen_arns.add(asset.arn)
                assets.append(asset)

        def mk(arn, resource_type, exposure, name, region="", attrs=None):
            return CloudAssetEntity(
                id=uuid4(),
                workspace_id=workspace_id,
                provider="aws",
                arn=arn,
                asset_urn=arn,  # ARN == the cross-pillar correlation key (matches Prowler)
                resource_type=resource_type,
                exposure=exposure,
                first_seen_at=now,
                last_seen_at=now,
                region=region,
                name=name or "",
                attributes={"account_id": account_id, "derived_from": "boto3", **(attrs or {})},
            )

        # IAM + S3 are global — one client each.
        self._collect_iam(session, account_id, mk, add, edges)
        self._collect_s3(session, account_id, mk, add)
        for region in self._regions:
            self._collect_ec2(session, account_id, region, mk, add, edges)

        # Fan a role's "reads S3" grant (Resource "*" or s3:*) out to every bucket node —
        # the coarse data-reach edge for slice 1 (precise bucket-ARN matching is a follow-up).
        bucket_arns = [a.arn for a in assets if a.resource_type == "AwsS3Bucket"]
        expanded: list[_Edge] = []
        for edge in edges:
            if edge.dst_arn == "__ALL_BUCKETS__":
                expanded.extend(_Edge(edge.src_arn, b, AssetRelation.READS_BUCKET) for b in bucket_arns)
            else:
                expanded.append(edge)
        return assets, expanded

    def _collect_ec2(self, session, account_id, region, mk, add, edges):
        try:
            ec2 = session.client("ec2", region_name=region)
            paginator = ec2.get_paginator("describe_instances")
            for page in paginator.paginate():
                for reservation in page.get("Reservations", []):
                    for inst in reservation.get("Instances", []):
                        iid = inst.get("InstanceId")
                        if not iid:
                            continue
                        arn = f"arn:aws:ec2:{region}:{account_id}:instance/{iid}"
                        public = bool(inst.get("PublicIpAddress")) or bool(
                            inst.get("NetworkInterfaces", [{}])[0].get("Association", {}).get("PublicIp")
                            if inst.get("NetworkInterfaces")
                            else False
                        )
                        name = next(
                            (t["Value"] for t in inst.get("Tags", []) if t.get("Key") == "Name"),
                            iid,
                        )
                        add(mk(arn, "AwsEc2Instance", Exposure.PUBLIC if public else Exposure.PRIVATE, name, region))
                        prof = (inst.get("IamInstanceProfile") or {}).get("Arn")
                        if prof:
                            # Instance profile arn: arn:aws:iam::acct:instance-profile/Name
                            add(mk(prof, "AwsIamInstanceProfile", Exposure.INTERNAL, prof.rsplit("/", 1)[-1]))
                            edges.append(_Edge(arn, prof, AssetRelation.ATTACHED_TO))
        except Exception:
            logger.exception("boto3_inventory ec2 enumerate failed account=%s region=%s", account_id, region)

    def _collect_iam(self, session, account_id, mk, add, edges):
        try:
            iam = session.client("iam")
            # instance-profile -> role edges
            for page in iam.get_paginator("list_instance_profiles").paginate():
                for prof in page.get("InstanceProfiles", []):
                    parn = prof.get("Arn")
                    if parn:
                        add(mk(parn, "AwsIamInstanceProfile", Exposure.INTERNAL, prof.get("InstanceProfileName", "")))
                    for role in prof.get("Roles", []):
                        rarn = role.get("Arn")
                        if parn and rarn:
                            add(mk(rarn, "AwsIamRole", Exposure.INTERNAL, role.get("RoleName", "")))
                            edges.append(_Edge(parn, rarn, AssetRelation.CAN_ASSUME))
            # roles -> attached/inline policies (+ admin / s3 analysis)
            for page in iam.get_paginator("list_roles").paginate():
                for role in page.get("Roles", []):
                    rarn = role.get("Arn")
                    rname = role.get("RoleName", "")
                    if not rarn:
                        continue
                    add(mk(rarn, "AwsIamRole", Exposure.INTERNAL, rname))
                    self._role_policies(iam, account_id, rarn, rname, mk, add, edges)
        except Exception:
            logger.exception("boto3_inventory iam enumerate failed account=%s", account_id)

    def _role_policies(self, iam, account_id, rarn, rname, mk, add, edges):
        docs: list[tuple[str, str, dict]] = []  # (policy_arn, policy_name, document)
        try:
            for ap in iam.list_attached_role_policies(RoleName=rname).get("AttachedPolicies", []):
                parn, pname = ap.get("PolicyArn"), ap.get("PolicyName", "")
                doc = self._managed_policy_doc(iam, parn)
                docs.append((parn, pname, doc))
        except Exception:
            logger.exception("boto3_inventory list_attached_role_policies failed role=%s", rname)
        try:
            for inline_name in iam.list_role_policies(RoleName=rname).get("PolicyNames", []):
                doc = iam.get_role_policy(RoleName=rname, PolicyName=inline_name).get("PolicyDocument")
                if isinstance(doc, str):
                    doc = json.loads(unquote(doc))
                synthetic = f"{rarn}/inline-policy/{inline_name}"
                docs.append((synthetic, inline_name, doc or {}))
        except Exception:
            logger.exception("boto3_inventory inline policies failed role=%s", rname)

        for parn, pname, doc in docs:
            if not parn:
                continue
            is_admin, grants_s3 = _analyze_policy(doc)
            # The analyzer flags an admin sink by name/arn text ("admin"/"*"); surface a
            # detected wildcard-admin as "* " so a custom broad policy is caught too.
            display = (
                f"* {pname}" if (is_admin and not any(h in pname.lower() for h in ("admin", "poweruser"))) else pname
            )
            add(mk(parn, "AwsIamPolicy", Exposure.INTERNAL, display, attrs={"is_admin": is_admin}))
            edges.append(_Edge(rarn, parn, AssetRelation.HAS_POLICY))
            if grants_s3:
                edges.append(_Edge(rarn, "__ALL_BUCKETS__", AssetRelation.READS_BUCKET))

    def _managed_policy_doc(self, iam, policy_arn):
        try:
            ver = iam.get_policy(PolicyArn=policy_arn)["Policy"]["DefaultVersionId"]
            doc = iam.get_policy_version(PolicyArn=policy_arn, VersionId=ver)["PolicyVersion"]["Document"]
            if isinstance(doc, str):
                doc = json.loads(unquote(doc))
            return doc or {}
        except Exception:
            return {}

    def _collect_s3(self, session, account_id, mk, add):
        try:
            s3 = session.client("s3")
            for b in s3.list_buckets().get("Buckets", []):
                name = b.get("Name")
                if not name:
                    continue
                arn = f"arn:aws:s3:::{name}"
                add(mk(arn, "AwsS3Bucket", Exposure.PRIVATE, name))
        except Exception:
            logger.exception("boto3_inventory s3 enumerate failed account=%s", account_id)


def _analyze_policy(doc: dict) -> tuple[bool, bool]:
    """(is_admin, grants_s3) from an IAM policy document — best-effort, defensive."""
    is_admin = False
    grants_s3 = False
    statements = doc.get("Statement", []) if isinstance(doc, dict) else []
    if isinstance(statements, dict):
        statements = [statements]
    for st in statements:
        if not isinstance(st, dict) or st.get("Effect") != "Allow":
            continue
        actions = st.get("Action", [])
        actions = [actions] if isinstance(actions, str) else (actions or [])
        resources = st.get("Resource", [])
        resources = [resources] if isinstance(resources, str) else (resources or [])
        acts = [a.lower() for a in actions if isinstance(a, str)]
        if any(a in ("*", "*:*") for a in acts) and any(r == "*" for r in resources):
            is_admin = True
        if any(a == "*" or a.startswith("s3:") for a in acts):
            grants_s3 = True
    return is_admin, grants_s3
