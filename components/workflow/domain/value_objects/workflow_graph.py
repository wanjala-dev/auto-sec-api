"""WorkflowGraph — pure navigation over a workflow's node/edge JSON.

No Django, no ORM. This is the single place that knows how to read the graph
shape, find the start node, walk edges, and — critically — pick the branch
target for an autonomous ``condition`` / ``wait_until`` outcome. Keeping this
logic in the domain (not the Celery task) is what makes branch selection
unit-testable without a broker or a database.

Graph shape::

    {
        "nodes": [{"id": "n1", "type": "start", "label": "..."}, ...],
        "edges": [{"id": "e1", "from": "n1", "to": "n2", "label": "yes"}, ...],
    }

Branch selection rule (the autonomous-engine keystone):

- A boolean ``outcome`` (from a condition / wait_until) maps True -> the "yes"
  edge and False -> the "no" edge. An edge is a "yes"/"no" edge if its
  ``label`` (or ``branch`` / ``when`` field) equals "yes"/"no" (case-insensitive)
  or a configured truthy/falsey synonym.
- Fallback when labels are absent: with exactly two outgoing edges, True takes
  the first and False the second (the builder lays Yes before No). With one
  edge, both outcomes take it. With none, there is no target.
- A string ``outcome`` (legacy ``decision`` node) matches an edge ``label``
  directly, falling back to the first edge.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

_TRUE_LABELS = {"yes", "true", "y", "1", "pass", "match", "matched", "satisfied"}
_FALSE_LABELS = {"no", "false", "n", "0", "fail", "nomatch", "no_match", "timeout", "timed_out"}


class WorkflowGraph:
    """Read-only navigation over a workflow graph dict."""

    def __init__(self, graph: Optional[Dict[str, Any]]) -> None:
        graph = graph or {}
        raw_nodes = graph.get("nodes") or []
        raw_edges = graph.get("edges") or []
        self._nodes: Dict[str, Dict[str, Any]] = {
            node["id"]: node
            for node in raw_nodes
            if isinstance(node, dict) and node.get("id")
        }
        self._edges: List[Dict[str, Any]] = [
            edge for edge in raw_edges if isinstance(edge, dict) and edge.get("from")
        ]

    # -- nodes --------------------------------------------------------------
    @property
    def nodes(self) -> Dict[str, Dict[str, Any]]:
        return self._nodes

    def node(self, node_id: str) -> Optional[Dict[str, Any]]:
        return self._nodes.get(node_id)

    def node_type(self, node_id: str) -> Optional[str]:
        node = self._nodes.get(node_id)
        return node.get("type") if node else None

    def start_node_id(self) -> Optional[str]:
        starts = [nid for nid, node in self._nodes.items() if node.get("type") == "start"]
        return starts[0] if len(starts) == 1 else None

    # -- edges --------------------------------------------------------------
    def edges_from(self, node_id: str) -> List[Dict[str, Any]]:
        return [edge for edge in self._edges if edge.get("from") == node_id]

    def default_target(self, node_id: str) -> Optional[str]:
        """The next node for a linear (non-branching) advance — the first edge."""
        edges = self.edges_from(node_id)
        return edges[0].get("to") if edges else None

    def branch_target(self, node_id: str, outcome: Any) -> Optional[str]:
        """Resolve the destination node id for a branch outcome.

        ``outcome`` may be a bool (condition / wait_until) or a label string
        (legacy decision). Returns None when no edge can be selected.
        """
        edges = self.edges_from(node_id)
        if not edges:
            return None

        if isinstance(outcome, bool):
            wanted = _TRUE_LABELS if outcome else _FALSE_LABELS
            for edge in edges:
                if _edge_label(edge) in wanted:
                    return edge.get("to")
            # Fallback: positional (Yes first, No second).
            if len(edges) >= 2:
                return edges[0].get("to") if outcome else edges[1].get("to")
            return edges[0].get("to")

        # String / labelled outcome (legacy decision node).
        if outcome is not None:
            target = str(outcome).strip().lower()
            for edge in edges:
                if _edge_label(edge) == target:
                    return edge.get("to")
        return edges[0].get("to")


def _edge_label(edge: Dict[str, Any]) -> str:
    label = edge.get("label") or edge.get("branch") or edge.get("when") or ""
    return str(label).strip().lower()
