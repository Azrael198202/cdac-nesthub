from pathlib import Path
import json
from jsonschema import validate


class SchemaValidator:
    def validate_file(self, data: dict, schema_path: Path) -> None:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        validate(instance=data, schema=schema)
