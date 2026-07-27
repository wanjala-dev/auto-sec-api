"""boto3 asset-inventory collector — real nodes + edges for the CNAPP graph.

The keystone the finding-derived adapter's docstring calls out: Prowler findings give
NODES for failing-check resources only and NO edges, so attack-path traversal has
nothing to walk. This adapter assumes the customer's audit role and reads the live
topology via targeted ``describe``/``list`` calls, producing the nodes AND the typed
edges the ``AttackPathAnalyzer`` walks (ADR 0005 §7 build item #1).

Slice 1 lights up the ``PUBLIC_COMPUTE_ADMIN`` path:

    public EC2 instance ──attached_to──▶ instance-profile role ──has_policy──▶ admin policy

- EC2 ``describe_instances`` → instance nodes (``exposure=PUBLIC`` when a public IP is
  attached) + the instance-profile they carry.
- IAM ``get_instance_profile`` → the role (``attached_to`` edge), then
  ``list_attached_role_policies`` → policy nodes (``has_policy`` edge). The analyzer
  flags an admin sink from the policy's own name/arn (``AdministratorAccess`` →
  "administrator"), so no extra marking is needed here.

Two passes: collect every node by ARN, upsert them (so both endpoints exist + have
stable ids), then upsert the edges by resolved id. Idempotent — a re-sync updates in
place via the store's ``(workspace, arn)`` / ``(src, dst, relation)`` identities.
Per-account failures are isolated (one unreachable account never voids the rest).
``s3``/``public_data_exposure`` edges are the next slice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from components.cloud_graph.application.ports.asset_inventory_port import (
    AssetInventoryPort,
    AssetSyncResult,
)
from components.cloud_graph.domain.entities.cloud_asset_edge_entity import CloudAssetEdgeEntity
from components.cloud_graph.domain.entities.cloud_asset_entity import CloudAssetEntity
from components.cloud_graph.domain.value_objects.enums import AssetRelation, Exposure

logger = logging.getLogger(__name__)

_DEFAULT_REGIONS = ("us-east-1",)


@dataclass
class _Collected:
    """Staging: nodes keyed by ARN (so we upsert each once), edges by ARN pair."""

    nodes: dict[str, CloudAssetEntity] = field(default_factory=dict)
    edges: list[tuple[str, str, AssetRelation, dict]] = field(default_factory=list)

    def add_node(self, node: CloudAssetEntity) -> None:
        # "Most exposed wins" so a private re-observation never downgrades a PUBLIC node.
        existing = self.nodes.get(node.arn)
        if existing is None or (node.exposure is Exposure.PUBLIC and existing.exposure is not Exposure.PUBLIC):
            self.nodes[node.arn] = node

    def add_edge(self, src_arn: str, dst_arn: str, relation: AssetRelation, attributes: dict | None = None) -> None:
        self.edges.append((src_arn, dst_arn, relation, attributes or {}))


class Boto3AssetInventoryAdapter(AssetInventoryPort):
    def __init__(self, *, asset_store=None, access_port=None) -> None:
        self._asset_store = asset_store
        self._access_port = access_port

    def _deps(self):
        asset_store = self._asset_store
        access_port = self._access_port
        if asset_store is None:
            from components.cloud_graph.application.providers.cloud_graph_provider import (
                CloudGraphProvider,
            )

            asset_store = CloudGraphProvider.build_cloud_asset_store()
        if access_port is None:
            from components.integrations.application.providers.aws_account_access_provider import (
                get_aws_account_access_port,
            )

            access_port = get_aws_account_access_port()
        return asset_store, access_port

    def sync_workspace(self, workspace_id: UUID) -> AssetSyncResult:
        asset_store, access_port = self._deps()
        now = datetime.now(UTC)
        collected = _Collected()

        for account in access_port.accounts_for(str(workspace_id)):
            try:
                creds = access_port.credentials_for(
                    workspace_id=str(workspace_id),
                    account_id=account.account_id,
                    session_name="autosec-inventory",
                    use_cache=True,
                )
            except Exception:
                logger.exception("inventory_assume_role_failed account=%s", account.account_id)
                continue
            self._collect_account(
                workspace_id, account.account_id, account.regions or _DEFAULT_REGIONS, creds, now, collected
            )

        # Pass 1: upsert every node, remembering its persisted id keyed by ARN.
        arn_to_id: dict[str, UUID] = {}
        for node in collected.nodes.values():
            saved = asset_store.upsert_asset(node)
            arn_to_id[node.arn] = saved.id

        # Pass 2: upsert edges whose BOTH endpoints are known nodes (skip dangling).
        edges_written = 0
        for src_arn, dst_arn, relation, attributes in collected.edges:
            src_id = arn_to_id.get(src_arn)
            dst_id = arn_to_id.get(dst_arn)
            if src_id is None or dst_id is None:
                continue
            asset_store.upsert_edge(
                CloudAssetEdgeEntity(
                    id=uuid4(),
                    workspace_id=workspace_id,
                    src_asset_id=src_id,
                    dst_asset_id=dst_id,
                    relation=relation,
                    last_seen_at=now,
                    attributes=attributes,
                )
            )
            edges_written += 1

        logger.info(
            "boto3_inventory_synced workspace_id=%s nodes=%d edges=%d",
            workspace_id,
            len(collected.nodes),
            edges_written,
        )
        return AssetSyncResult(workspace_id=workspace_id, assets_upserted=len(collected.nodes))

    # ── per-account collection ────────────────────────────────────────────────

    def _collect_account(self, workspace_id, account_id, regions, creds, now, collected) -> None:
        # instance_profile_arn -> [instance_arn, …] gathered across regions, resolved once via IAM.
        profile_to_instances: dict[str, list[str]] = {}
        for region in regions:
            try:
                self._collect_ec2(workspace_id, account_id, region, creds, now, collected, profile_to_instances)
            except Exception:
                logger.exception("inventory_ec2_failed account=%s region=%s", account_id, region)

        if profile_to_instances:
            try:
                self._collect_iam(workspace_id, account_id, creds, now, collected, profile_to_instances)
            except Exception:
                logger.exception("inventory_iam_failed account=%s", account_id)

    def _client(self, service, creds, region):
        import boto3

        return boto3.client(
            service,
            region_name=region,
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
        )

    def _collect_ec2(self, workspace_id, account_id, region, creds, now, collected, profile_to_instances) -> None:
        ec2 = self._client("ec2", creds, region)
        for page in ec2.get_paginator("describe_instances").paginate():
            for reservation in page.get("Reservations", []):
                for inst in reservation.get("Instances", []):
                    instance_id = inst.get("InstanceId")
                    if not instance_id:
                        continue
                    arn = f"arn:aws:ec2:{region}:{account_id}:instance/{instance_id}"
                    public = bool(inst.get("PublicIpAddress"))
                    name = next(
                        (t["Value"] for t in inst.get("Tags", []) if t.get("Key") == "Name"),
                        instance_id,
                    )
                    collected.add_node(
                        self._node(
                            workspace_id,
                            account_id,
                            region,
                            arn=arn,
                            resource_type="aws_ec2_instance",
                            name=name,
                            exposure=Exposure.PUBLIC if public else Exposure.PRIVATE,
                            now=now,
                            extra={
                                "public_ip": inst.get("PublicIpAddress") or "",
                                "state": (inst.get("State") or {}).get("Name", ""),
                            },
                        )
                    )
                    profile_arn = (inst.get("IamInstanceProfile") or {}).get("Arn")
                    if profile_arn:
                        profile_to_instances.setdefault(profile_arn, []).append(arn)

    def _collect_iam(self, workspace_id, account_id, creds, now, collected, profile_to_instances) -> None:
        iam = self._client("iam", creds, "us-east-1")  # IAM is global
        for profile_arn, instance_arns in profile_to_instances.items():
            profile_name = profile_arn.rsplit("/", 1)[-1]
            try:
                profile = iam.get_instance_profile(InstanceProfileName=profile_name)["InstanceProfile"]
            except Exception:
                logger.warning("inventory_get_instance_profile_failed profile=%s", profile_name)
                continue
            for role in profile.get("Roles", []):
                role_arn = role.get("Arn")
                if not role_arn:
                    continue
                collected.add_node(
                    self._node(
                        workspace_id,
                        account_id,
                        "",
                        arn=role_arn,
                        resource_type="aws_iam_role",
                        name=role.get("RoleName", ""),
                        exposure=Exposure.PRIVATE,
                        now=now,
                    )
                )
                for instance_arn in instance_arns:
                    collected.add_edge(instance_arn, role_arn, AssetRelation.ATTACHED_TO, {"via": "instance_profile"})
                self._collect_role_policies(iam, workspace_id, account_id, role, now, collected)

    def _collect_role_policies(self, iam, workspace_id, account_id, role, now, collected) -> None:
        role_arn = role["Arn"]
        role_name = role.get("RoleName", "")
        for page in iam.get_paginator("list_attached_role_policies").paginate(RoleName=role_name):
            for pol in page.get("AttachedPolicies", []):
                policy_arn = pol.get("PolicyArn")
                if not policy_arn:
                    continue
                collected.add_node(
                    self._node(
                        workspace_id,
                        account_id,
                        "",
                        arn=policy_arn,
                        resource_type="aws_iam_policy",
                        name=pol.get("PolicyName", ""),
                        exposure=Exposure.PRIVATE,
                        now=now,
                    )
                )
                collected.add_edge(
                    role_arn, policy_arn, AssetRelation.HAS_POLICY, {"policy_name": pol.get("PolicyName", "")}
                )

    def _node(
        self, workspace_id, account_id, region, *, arn, resource_type, name, exposure, now, extra=None
    ) -> CloudAssetEntity:
        from components.shared_kernel.domain.security import AssetUrn

        return CloudAssetEntity(
            id=uuid4(),
            workspace_id=workspace_id,
            provider="aws",
            arn=arn,
            asset_urn=AssetUrn.canonical("aws", arn).value,
            resource_type=resource_type,
            exposure=exposure,
            first_seen_at=now,
            last_seen_at=now,
            region=region,
            name=name or "",
            attributes={"account_id": account_id, "derived_from": "boto3_inventory", **(extra or {})},
        )
