from __future__ import annotations

from ai_core.validation.schema_validator import SchemaValidator


class ConfigValidator:
    def __init__(self):
        self.schema_validator = SchemaValidator()

    def validate_workflow(self, workflow: dict) -> None:
        self.schema_validator.validate_workflow_schema(workflow)
        node_ids = [node["id"] for node in workflow.get("nodes", [])]
        duplicated = {node_id for node_id in node_ids if node_ids.count(node_id) > 1}
        if duplicated:
            raise ValueError(f"Duplicated node ids: {sorted(duplicated)}")
