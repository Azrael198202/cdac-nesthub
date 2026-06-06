from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class GraphPartition:
    """Domain-neutral graph partitions for runtime coordination.

    metadata_graph stores definitions, policies, and generated descriptors.
    execution_graph stores nodes that are allowed to run.
    dataflow_graph stores edges and data binding rules between executable nodes.
    """

    metadata_graph: dict[str, Any] = field(default_factory=dict)
    execution_graph: dict[str, Any] = field(default_factory=dict)
    dataflow_graph: dict[str, Any] = field(default_factory=dict)
    boundary_report: dict[str, Any] = field(default_factory=dict)


class GraphBoundaryNormalizer:
    """Separates planning metadata from executable runtime graph.

    The normalizer is intentionally structural. It does not inspect business
    vocabulary. A node is executable only when its record explicitly declares it
    can run, or when it contains an executable method/config marker. Everything
    else is metadata and must not be dispatched by the scheduler.
    """

    EXECUTABLE_MARKERS = {
        "executor_type",
        "node_config",
        "execution_method",
        "runtime_callable",
        "tool_ref",
        "module_ref",
        "provider_ref",
    }
    NON_EXECUTABLE_KINDS = {
        "definition",
        "descriptor",
        "registration",
        "metadata",
        "policy",
        "schema",
        "profile",
    }

    def normalize(self, graph: dict[str, Any] | None) -> GraphPartition:
        graph = graph if isinstance(graph, dict) else {}
        raw_nodes = self._as_list(graph.get("nodes"))
        raw_edges = self._as_list(graph.get("edges"))

        metadata_nodes: list[dict[str, Any]] = []
        execution_nodes: list[dict[str, Any]] = []
        node_ids: set[str] = set()

        for index, node in enumerate(raw_nodes):
            if not isinstance(node, dict):
                continue
            normalized = dict(node)
            node_id = self._node_id(normalized, index)
            normalized["node_id"] = node_id
            node_ids.add(node_id)
            if self._is_executable(normalized):
                normalized.setdefault("status", "pending")
                execution_nodes.append(normalized)
            else:
                normalized.setdefault("status", "metadata_only")
                metadata_nodes.append(normalized)

        execution_ids = {str(n.get("node_id")) for n in execution_nodes}
        dataflow_edges: list[dict[str, Any]] = []
        metadata_edges: list[dict[str, Any]] = []
        rejected_edges: list[dict[str, Any]] = []

        for edge in raw_edges:
            if not isinstance(edge, dict):
                continue
            normalized_edge = self._normalize_edge(edge)
            src = normalized_edge.get("from")
            dst = normalized_edge.get("to")
            if src in execution_ids and dst in execution_ids:
                normalized_edge.setdefault("status", "pending")
                dataflow_edges.append(normalized_edge)
            elif src in node_ids and dst in node_ids:
                normalized_edge.setdefault("status", "metadata_only")
                metadata_edges.append(normalized_edge)
            else:
                normalized_edge.setdefault("status", "invalid_reference")
                rejected_edges.append(normalized_edge)

        boundary_report = {
            "status": "separated",
            "metadata_node_count": len(metadata_nodes),
            "execution_node_count": len(execution_nodes),
            "dataflow_edge_count": len(dataflow_edges),
            "metadata_edge_count": len(metadata_edges),
            "rejected_edge_count": len(rejected_edges),
            "non_executable_node_ids": [str(n.get("node_id")) for n in metadata_nodes],
        }
        return GraphPartition(
            metadata_graph={"nodes": metadata_nodes, "edges": metadata_edges},
            execution_graph={"nodes": execution_nodes},
            dataflow_graph={"edges": dataflow_edges, "rejected_edges": rejected_edges},
            boundary_report=boundary_report,
        )

    def _is_executable(self, node: dict[str, Any]) -> bool:
        kind = str(node.get("node_type") or node.get("kind") or "").strip().lower()
        if kind in self.NON_EXECUTABLE_KINDS:
            return False
        explicit = node.get("executable")
        if isinstance(explicit, bool):
            return explicit
        return any(node.get(marker) not in (None, "", [], {}) for marker in self.EXECUTABLE_MARKERS)

    def _node_id(self, node: dict[str, Any], index: int) -> str:
        value = node.get("node_id") or node.get("id") or node.get("name") or f"node_{index + 1}"
        return str(value).strip() or f"node_{index + 1}"

    def _normalize_edge(self, edge: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(edge)
        src = normalized.get("from") or normalized.get("source") or normalized.get("source_id")
        dst = normalized.get("to") or normalized.get("target") or normalized.get("target_id")
        normalized["from"] = str(src or "").strip()
        normalized["to"] = str(dst or "").strip()
        normalized.setdefault("data_contract", "runtime_json")
        return normalized

    def _as_list(self, value: Any) -> list[Any]:
        return value if isinstance(value, list) else []
