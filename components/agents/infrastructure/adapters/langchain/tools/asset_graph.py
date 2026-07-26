"""Read-only asset-graph tool — grounds triage blast-radius (cloud_graph, item #7 §7).

Lets the triage agent replace a window-local ``blast_radius`` guess with the real
cloud-graph facts for a resource: exposure (public/internal/private), type, region,
account. Reads the cloud_graph context through its public provider/port (C3 — never its
ORM). Degrades gracefully to an empty result when the graph isn't enabled/synced.

Node-level today (exposure/type/region/account). Once the graph carries edges (a later
slice), this can also answer "what identity can reach it? what's downstream?" — the tool
name is stable so that enrichment is additive.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

_MAX_RESULTS = 10
_SEARCH_SCAN = 500


def query_asset_graph(agent, input_str: str = "") -> str:
    """READ — cloud-graph facts for an ARN or a service/name/type search."""
    query = (input_str or "").strip().strip('"')
    if query.startswith("{"):  # tolerate a JSON {"arn"|"query"|"service": "..."} wrapper
        try:
            data = json.loads(query)
            query = str(data.get("arn") or data.get("query") or data.get("service") or "").strip()
        except Exception:
            pass

    from components.cloud_graph.application.providers.cloud_graph_provider import CloudGraphProvider

    store = CloudGraphProvider.build_cloud_asset_store()
    workspace_id = agent.workspace_id

    matches = []
    if query.lower().startswith("arn:"):
        asset = store.get_asset_by_arn(workspace_id, query)
        if asset is not None:
            matches = [asset]

    if not matches:
        needle = query.lower()
        assets = store.list_assets(workspace_id, limit=_SEARCH_SCAN)
        if needle:
            matches = [
                a
                for a in assets
                if needle in a.arn.lower()
                or needle in (a.name or "").lower()
                or needle in a.resource_type.lower()
                or needle in (a.attributes or {}).get("service", "").lower()
                or needle in (a.region or "").lower()
            ]
        else:
            matches = assets

    if not matches:
        return json.dumps(
            {
                "assets": [],
                "note": (
                    "No matching cloud assets in the graph. The asset graph may not be "
                    "enabled or synced for this workspace; ground the finding in its own "
                    "evidence instead."
                ),
            }
        )

    rows = [
        {
            "arn": a.arn,
            "resource_type": a.resource_type,
            "exposure": a.exposure.value,
            "region": a.region,
            "account_id": (a.attributes or {}).get("account_id", ""),
            "service": (a.attributes or {}).get("service", ""),
        }
        for a in matches[:_MAX_RESULTS]
    ]
    return json.dumps({"assets": rows, "total": len(matches)})
