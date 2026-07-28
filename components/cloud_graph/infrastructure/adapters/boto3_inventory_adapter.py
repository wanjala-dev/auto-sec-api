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
            net = self._collect_network(session, account_id, region, mk, add, edges)
            self._collect_ec2(session, account_id, region, mk, add, edges, net)

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

    def _collect_ec2(self, session, account_id, region, mk, add, edges, net):
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
                        nics = inst.get("NetworkInterfaces") or []
                        has_public_ip = bool(inst.get("PublicIpAddress")) or any(
                            (nic.get("Association") or {}).get("PublicIp") for nic in nics
                        )
                        subnet_id = inst.get("SubnetId") or (nics[0].get("SubnetId") if nics else None)
                        sg_ids = [g.get("GroupId") for g in inst.get("SecurityGroups", []) if g.get("GroupId")]
                        open_sg_ids = [s for s in sg_ids if s in net["open_sgs"]]

                        # Real reachability, not a public-IP heuristic: an internet-routable
                        # path (a public IP or a subnet whose route table reaches an IGW) AND an
                        # open firewall (a security group allowing 0.0.0.0/0 ingress). A public IP
                        # behind a closed SG is NOT reachable — this cuts false-positive entries.
                        in_public_subnet = subnet_id in net["public_subnets"]
                        routable = has_public_ip or in_public_subnet
                        reachable = routable and bool(open_sg_ids)
                        exposure = Exposure.PUBLIC if reachable else Exposure.INTERNAL if routable else Exposure.PRIVATE

                        name = next(
                            (t["Value"] for t in inst.get("Tags", []) if t.get("Key") == "Name"),
                            iid,
                        )
                        add(
                            mk(
                                arn,
                                "AwsEc2Instance",
                                exposure,
                                name,
                                region,
                                attrs={"public_ip": has_public_ip, "open_to_internet": bool(open_sg_ids)},
                            )
                        )
                        if subnet_id and subnet_id in net["subnet_arns"]:
                            edges.append(_Edge(arn, net["subnet_arns"][subnet_id], AssetRelation.IN_SUBNET))
                        for sid in open_sg_ids:
                            edges.append(_Edge(arn, net["sg_arns"][sid], AssetRelation.ALLOWS_INGRESS_FROM))
                        prof = (inst.get("IamInstanceProfile") or {}).get("Arn")
                        if prof:
                            # Instance profile arn: arn:aws:iam::acct:instance-profile/Name
                            add(mk(prof, "AwsIamInstanceProfile", Exposure.INTERNAL, prof.rsplit("/", 1)[-1]))
                            edges.append(_Edge(arn, prof, AssetRelation.ATTACHED_TO))
        except Exception:
            logger.exception("boto3_inventory ec2 enumerate failed account=%s region=%s", account_id, region)

    def _collect_network(self, session, account_id, region, mk, add, edges) -> dict:
        """Enumerate the VPC network: subnets, route-table→IGW reachability, and security-group
        internet-exposure — the inputs that decide whether an instance is REALLY reachable.
        Adds subnet / IGW / security-group nodes + the topology edges, and returns the maps
        ``_collect_ec2`` reads. Best-effort: a failure degrades EC2 to the public-IP heuristic.
        """
        empty = {"open_sgs": {}, "public_subnets": set(), "subnet_arns": {}, "sg_arns": {}}
        try:
            ec2 = session.client("ec2", region_name=region)

            def _arn(kind, rid):
                return f"arn:aws:ec2:{region}:{account_id}:{kind}/{rid}"

            # IGWs by VPC (an attached IGW is the door to the internet).
            vpc_igw: dict[str, str] = {}
            for page in ec2.get_paginator("describe_internet_gateways").paginate():
                for igw in page.get("InternetGateways", []):
                    gid = igw.get("InternetGatewayId")
                    if not gid:
                        continue
                    garn = _arn("internet-gateway", gid)
                    add(mk(garn, "AwsEc2InternetGateway", Exposure.PUBLIC, gid, region))
                    for att in igw.get("Attachments", []):
                        if att.get("VpcId"):
                            vpc_igw[att["VpcId"]] = garn

            # Route tables → which subnets have a default route to an IGW (public subnets).
            main_public: dict[str, bool] = {}  # vpc_id → main route table is public
            explicit_public: dict[str, bool] = {}  # subnet_id → its route table is public
            for page in ec2.get_paginator("describe_route_tables").paginate():
                for rt in page.get("RouteTables", []):
                    to_igw = any(
                        str(r.get("GatewayId", "")).startswith("igw-") and r.get("DestinationCidrBlock") == "0.0.0.0/0"
                        for r in rt.get("Routes", [])
                    )
                    for a in rt.get("Associations", []):
                        if a.get("Main") and rt.get("VpcId"):
                            main_public[rt["VpcId"]] = to_igw
                        if a.get("SubnetId"):
                            explicit_public[a["SubnetId"]] = to_igw

            # Subnets → node + public/private exposure + ROUTES_TO_IGW edge.
            subnet_arns: dict[str, str] = {}
            public_subnets: set[str] = set()
            for page in ec2.get_paginator("describe_subnets").paginate():
                for s in page.get("Subnets", []):
                    sid = s.get("SubnetId")
                    if not sid:
                        continue
                    vpc_id = s.get("VpcId")
                    is_public = explicit_public.get(sid, main_public.get(vpc_id, False))
                    sarn = _arn("subnet", sid)
                    subnet_arns[sid] = sarn
                    add(mk(sarn, "AwsEc2Subnet", Exposure.PUBLIC if is_public else Exposure.PRIVATE, sid, region))
                    if is_public:
                        public_subnets.add(sid)
                        if vpc_id in vpc_igw:
                            edges.append(_Edge(sarn, vpc_igw[vpc_id], AssetRelation.ROUTES_TO_IGW))

            # Security groups → node + which open 0.0.0.0/0 (or ::/0) ingress.
            sg_arns: dict[str, str] = {}
            open_sgs: dict[str, str] = {}
            for page in ec2.get_paginator("describe_security_groups").paginate():
                for sg in page.get("SecurityGroups", []):
                    gid = sg.get("GroupId")
                    if not gid:
                        continue
                    open_internet = any(
                        any(r.get("CidrIp") == "0.0.0.0/0" for r in perm.get("IpRanges", []))
                        or any(r.get("CidrIpv6") == "::/0" for r in perm.get("Ipv6Ranges", []))
                        for perm in sg.get("IpPermissions", [])
                    )
                    garn = _arn("security-group", gid)
                    sg_arns[gid] = garn
                    add(
                        mk(
                            garn,
                            "AwsEc2SecurityGroup",
                            Exposure.PUBLIC if open_internet else Exposure.INTERNAL,
                            sg.get("GroupName", gid),
                            region,
                            attrs={"open_from_internet": open_internet},
                        )
                    )
                    if open_internet:
                        open_sgs[gid] = garn

            return {
                "open_sgs": open_sgs,
                "public_subnets": public_subnets,
                "subnet_arns": subnet_arns,
                "sg_arns": sg_arns,
            }
        except Exception:
            logger.exception("boto3_inventory network enumerate failed account=%s region=%s", account_id, region)
            return empty

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
            is_admin, reads_all_s3, s3_buckets = _analyze_policy(doc)
            # The analyzer flags an admin sink by name/arn text ("admin"/"*"); surface a
            # detected wildcard-admin as "* " so a custom broad policy is caught too.
            display = (
                f"* {pname}" if (is_admin and not any(h in pname.lower() for h in ("admin", "poweruser"))) else pname
            )
            add(mk(parn, "AwsIamPolicy", Exposure.INTERNAL, display, attrs={"is_admin": is_admin}))
            edges.append(_Edge(rarn, parn, AssetRelation.HAS_POLICY))
            if reads_all_s3:
                edges.append(_Edge(rarn, "__ALL_BUCKETS__", AssetRelation.READS_BUCKET))
            else:
                # Precise: reach only the buckets this grant scopes to (resolves to a bucket
                # node if it exists; a cross-account / absent bucket simply drops).
                for bname in s3_buckets:
                    edges.append(_Edge(rarn, f"arn:aws:s3:::{bname}", AssetRelation.READS_BUCKET))

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


def _analyze_policy(doc: dict) -> tuple[bool, bool, set[str]]:
    """(is_admin, reads_all_s3, s3_bucket_names) from an IAM policy document — best-effort.

    ``reads_all_s3`` is True when an s3 grant targets Resource ``*`` (every bucket);
    ``s3_bucket_names`` is the set of specific buckets an s3 grant scopes to. This lets the
    READS_BUCKET edge point at the buckets a role can ACTUALLY reach, not all of them.
    """
    is_admin = False
    reads_all_s3 = False
    s3_buckets: set[str] = set()
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
        res = [r for r in resources if isinstance(r, str)]
        if any(a in ("*", "*:*") for a in acts) and any(r == "*" for r in res):
            is_admin = True
        if any(a == "*" or a.startswith("s3:") for a in acts):
            for r in res:
                if r in ("*", "arn:aws:s3:::*"):
                    reads_all_s3 = True
                elif r.startswith("arn:aws:s3:::"):
                    # arn:aws:s3:::bucket | …/* | …/key → the bucket name
                    s3_buckets.add(r[len("arn:aws:s3:::") :].split("/", 1)[0])
    return is_admin, reads_all_s3, s3_buckets
