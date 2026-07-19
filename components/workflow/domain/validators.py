"""Workflow graph validation helpers.

No Django imports — depends only on domain constants.
"""

from __future__ import annotations

from typing import Any, Dict, List

from components.workflow.domain.constants import NODE_TYPES

MAX_NODES = 250
MAX_EDGES = 500


def validate_graph(graph: Dict[str, Any]) -> List[Dict[str, str]]:
    """Return a list of validation errors for a workflow graph."""

    errors: List[Dict[str, str]] = []

    nodes = graph.get("nodes") if isinstance(graph, dict) else None
    edges = graph.get("edges") if isinstance(graph, dict) else None

    if nodes is None or edges is None:
        return [
            {
                "code": "invalid_graph",
                "path": "graph",
                "message": "Graph must include nodes and edges arrays.",
            }
        ]

    if not isinstance(nodes, list) or not isinstance(edges, list):
        return [
            {
                "code": "invalid_graph",
                "path": "graph",
                "message": "Nodes and edges must be lists.",
            }
        ]

    if len(nodes) > MAX_NODES:
        errors.append(
            {
                "code": "graph_too_large",
                "path": "nodes",
                "message": f"Node count exceeds {MAX_NODES}.",
            }
        )
    if len(edges) > MAX_EDGES:
        errors.append(
            {
                "code": "graph_too_large",
                "path": "edges",
                "message": f"Edge count exceeds {MAX_EDGES}.",
            }
        )

    node_ids = []
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(
                {
                    "code": "invalid_node",
                    "path": f"nodes[{index}]",
                    "message": "Node must be an object.",
                }
            )
            continue

        node_id = node.get("id")
        node_type = node.get("type")
        # The builder + engine + seeded templates use ``label``; some older
        # graphs use ``title``. Accept either so validate_graph never rejects a
        # graph the engine can actually run (constitutional rule: validate what
        # you run).
        title = node.get("label") or node.get("title")
        if not node_id:
            errors.append(
                {
                    "code": "missing_node_id",
                    "path": f"nodes[{index}].id",
                    "message": "Node must include an id.",
                }
            )
        else:
            node_ids.append(node_id)

        if node_type not in NODE_TYPES:
            errors.append(
                {
                    "code": "invalid_node_type",
                    "path": f"nodes[{index}].type",
                    "message": f"Node type '{node_type}' is not supported.",
                }
            )

        if not title:
            errors.append(
                {
                    "code": "missing_node_title",
                    "path": f"nodes[{index}].title",
                    "message": "Node must include a title.",
                }
            )

    duplicates = {node_id for node_id in node_ids if node_ids.count(node_id) > 1}
    if duplicates:
        errors.append(
            {
                "code": "duplicate_node_ids",
                "path": "nodes",
                "message": f"Duplicate node ids found: {', '.join(sorted(duplicates))}.",
            }
        )

    node_id_set = set(node_ids)
    for index, edge in enumerate(edges):
        if not isinstance(edge, dict):
            errors.append(
                {
                    "code": "invalid_edge",
                    "path": f"edges[{index}]",
                    "message": "Edge must be an object.",
                }
            )
            continue

        from_node = edge.get("from")
        to_node = edge.get("to")
        if not from_node or not to_node:
            errors.append(
                {
                    "code": "invalid_edge_reference",
                    "path": f"edges[{index}]",
                    "message": "Edge must include 'from' and 'to' node ids.",
                }
            )
            continue

        if from_node not in node_id_set:
            errors.append(
                {
                    "code": "unknown_edge_source",
                    "path": f"edges[{index}].from",
                    "message": f"Edge source '{from_node}' does not exist.",
                }
            )
        if to_node not in node_id_set:
            errors.append(
                {
                    "code": "unknown_edge_target",
                    "path": f"edges[{index}].to",
                    "message": f"Edge target '{to_node}' does not exist.",
                }
            )

    node_type_lookup = {}
    for node in nodes:
        if isinstance(node, dict) and node.get("id"):
            node_type_lookup[node["id"]] = node.get("type")

    start_nodes = [node_id for node_id, node_type in node_type_lookup.items() if node_type == "start"]
    end_nodes = [node_id for node_id, node_type in node_type_lookup.items() if node_type == "end"]

    if len(start_nodes) != 1:
        errors.append(
            {
                "code": "invalid_start_node",
                "path": "nodes",
                "message": "Graph must include exactly one start node.",
            }
        )
    if len(end_nodes) < 1:
        errors.append(
            {
                "code": "missing_end_node",
                "path": "nodes",
                "message": "Graph must include at least one end node.",
            }
        )

    outgoing_edges = {}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        source = edge.get("from")
        if source:
            outgoing_edges.setdefault(source, []).append(edge)

    # Branching nodes require at least two labelled outgoing edges so the
    # engine can resolve a Yes/No outcome to a destination.
    for node_id, node_type in node_type_lookup.items():
        if node_type in ("decision", "condition", "wait_until", "switch"):
            branch_edges = outgoing_edges.get(node_id, [])
            if len(branch_edges) < 2:
                errors.append(
                    {
                        "code": "branch_missing_branches",
                        "path": f"nodes[{node_id}]",
                        "message": f"'{node_type}' nodes require at least two outgoing edges.",
                    }
                )
            for edge in branch_edges:
                if not (edge.get("label") or edge.get("branch") or edge.get("when")):
                    errors.append(
                        {
                            "code": "branch_missing_label",
                            "path": f"edges[{edge.get('id', '')}]",
                            "message": "Branch edges must include a label (e.g. 'yes'/'no').",
                        }
                    )

    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_type = node.get("type")
        config = node.get("config") or {}
        node_id = node.get("id", "")

        if node_type == "wait":
            if not (config.get("delay_seconds") or config.get("delay_until")):
                errors.append(
                    {
                        "code": "wait_missing_delay",
                        "path": f"nodes[{node_id}].config",
                        "message": "Wait nodes require delay_seconds or delay_until.",
                    }
                )

        if node_type == "wait_until":
            if not (
                config.get("timeout_seconds")
                or config.get("timeout_until")
                or config.get("delay_seconds")
                or config.get("delay_until")
            ):
                errors.append(
                    {
                        "code": "wait_until_missing_timeout",
                        "path": f"nodes[{node_id}].config",
                        "message": "wait_until nodes require a timeout (timeout_seconds/timeout_until).",
                    }
                )

        if node_type == "condition":
            predicate = config.get("predicate")
            inline = "conditions" in config or "field" in config
            if not predicate and not inline:
                errors.append(
                    {
                        "code": "condition_missing_predicate",
                        "path": f"nodes[{node_id}].config",
                        "message": "Condition nodes require a predicate (conditions/field).",
                    }
                )

        if node_type == "switch":
            cases = config.get("cases")
            if not isinstance(cases, list) or not cases:
                errors.append(
                    {
                        "code": "switch_missing_cases",
                        "path": f"nodes[{node_id}].config.cases",
                        "message": "switch nodes require a non-empty 'cases' list.",
                    }
                )
            else:
                for case in cases:
                    if not isinstance(case, dict) or not case.get("label"):
                        errors.append(
                            {
                                "code": "switch_case_missing_label",
                                "path": f"nodes[{node_id}].config.cases",
                                "message": "Each switch case requires a 'label'.",
                            }
                        )
                        break

        if node_type == "message":
            if not config.get("channel"):
                errors.append(
                    {
                        "code": "message_missing_channel",
                        "path": f"nodes[{node_id}].config.channel",
                        "message": "Message nodes require a channel.",
                    }
                )
            if not (config.get("template_id") or config.get("message") or config.get("body")):
                errors.append(
                    {
                        "code": "message_missing_payload",
                        "path": f"nodes[{node_id}].config",
                        "message": "Message nodes require template_id or message/body.",
                    }
                )

        if node_type in ("add_tag", "remove_tag"):
            if not (config.get("tag") or config.get("tag_name")):
                errors.append(
                    {
                        "code": "tag_missing_name",
                        "path": f"nodes[{node_id}].config.tag",
                        "message": f"{node_type} nodes require a tag name.",
                    }
                )

        if node_type == "update_field":
            if not config.get("field"):
                errors.append(
                    {
                        "code": "update_field_missing_field",
                        "path": f"nodes[{node_id}].config.field",
                        "message": "update_field nodes require a field name.",
                    }
                )

    return errors
