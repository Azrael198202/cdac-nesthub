from __future__ import annotations

from typing import Any


class RuntimeSchemaGenerator:
    """Generates neutral runtime schemas for dynamically created artifacts."""

    def workflow_structure_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["nodes", "edges", "parallel_batches"],
            "properties": {
                "version": {"type": "string"},
                "nodes": {"type": "array", "items": self._task_node_schema()},
                "edges": {"type": "array", "items": {"type": "object", "required": ["from", "to"]}},
                "parallel_batches": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
            },
            "additionalProperties": True,
        }

    def trace_structure_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["run_id", "events"],
            "properties": {
                "run_id": {"type": "string"},
                "events": {"type": "array", "items": {"type": "object", "required": ["type", "timestamp"]}},
                "assertions": {"type": "array"},
            },
            "additionalProperties": True,
        }

    def fact_graph_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["facts", "relations"],
            "properties": {
                "facts": {"type": "array", "items": {"type": "object", "required": ["fact_id", "value", "source_id"]}},
                "relations": {"type": "array", "items": {"type": "object", "required": ["from", "to", "relation"]}},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "additionalProperties": True,
        }

    def _task_node_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["task_id", "objective", "task_type", "depends_on", "required_outputs"],
            "properties": {
                "task_id": {"type": "string"},
                "objective": {"type": "string"},
                "task_type": {"type": "string"},
                "depends_on": {"type": "array", "items": {"type": "string"}},
                "required_outputs": {"type": "array", "items": {"type": "string"}},
                "parameters": {"type": "object"},
                "can_run_parallel": {"type": "boolean"},
            },
            "additionalProperties": True,
        }
