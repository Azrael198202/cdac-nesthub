from typing import Any
from jsonschema import validate
class SchemaValidator:
    def validate_data(self, data: dict, schema: dict[str, Any]) -> None:
        if schema: validate(instance=data, schema=schema)
