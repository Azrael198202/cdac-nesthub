from __future__ import annotations

from typing import Any


class ToolSchemaValidator:
    """
    Small generic JSON-schema subset validator used by the runtime tool layer.

    It intentionally stays domain-neutral. It validates generic JSON object
    shapes declared by runtime-generated tool manifests. The tool itself owns
    any domain-specific validation rules.
    """

    def validate_input(self, schema: dict[str, Any] | None, value: Any) -> dict[str, Any]:
        return self._validate(schema or {"type": "object", "additionalProperties": True}, value, path="$")

    def validate_output(self, schema: dict[str, Any] | None, value: Any) -> dict[str, Any]:
        return self._validate(schema or {"type": "object", "additionalProperties": True}, value, path="$")

    def _validate(self, schema: dict[str, Any], value: Any, path: str) -> dict[str, Any]:
        errors: list[str] = []
        self._check(schema, value, path, errors)
        return {"valid": not errors, "errors": errors}

    def _check(self, schema: dict[str, Any], value: Any, path: str, errors: list[str]) -> None:
        if not isinstance(schema, dict):
            return

        expected_type = schema.get("type")
        if expected_type:
            allowed = expected_type if isinstance(expected_type, list) else [expected_type]
            if not any(self._matches_type(t, value) for t in allowed):
                errors.append(f"{path}: expected {expected_type}, got {type(value).__name__}")
                return

        enum_values = schema.get("enum")
        if isinstance(enum_values, list) and value not in enum_values:
            errors.append(f"{path}: value is not in enum")

        if schema.get("type") == "object" or isinstance(value, dict):
            if not isinstance(value, dict):
                return
            required = schema.get("required", [])
            if isinstance(required, list):
                for key in required:
                    if key not in value:
                        errors.append(f"{path}.{key}: required property is missing")
            properties = schema.get("properties", {})
            if isinstance(properties, dict):
                for key, child_schema in properties.items():
                    if key in value and isinstance(child_schema, dict):
                        self._check(child_schema, value[key], f"{path}.{key}", errors)
            additional = schema.get("additionalProperties", True)
            if additional is False and isinstance(properties, dict):
                for key in value.keys():
                    if key not in properties:
                        errors.append(f"{path}.{key}: additional property is not allowed")

        if schema.get("type") == "array" or isinstance(value, list):
            if not isinstance(value, list):
                return
            item_schema = schema.get("items")
            if isinstance(item_schema, dict):
                for index, item in enumerate(value):
                    self._check(item_schema, item, f"{path}[{index}]", errors)

    def _matches_type(self, expected: str, value: Any) -> bool:
        if expected == "object":
            return isinstance(value, dict)
        if expected == "array":
            return isinstance(value, list)
        if expected == "string":
            return isinstance(value, str)
        if expected == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if expected == "number":
            return (isinstance(value, int) or isinstance(value, float)) and not isinstance(value, bool)
        if expected == "boolean":
            return isinstance(value, bool)
        if expected == "null":
            return value is None
        return True
