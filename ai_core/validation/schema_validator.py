from __future__ import annotations

from pathlib import Path

from ai_core.config_loader import ConfigLoader


class SchemaValidator:
    def __init__(self):
        self.loader = ConfigLoader(".")

    def validate_workflow_schema(self, workflow: dict) -> None:
        required = {"workflow_id", "nodes"}
        missing = required.difference(workflow.keys())
        if missing:
            raise ValueError(f"Missing workflow keys: {sorted(missing)}")

    def load_schema(self, schema_path: str) -> dict:
        return self.loader.load_path(Path(schema_path))
