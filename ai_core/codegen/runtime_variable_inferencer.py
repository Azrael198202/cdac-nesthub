from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class RuntimeVariable:
    name: str
    aliases: list[str]
    sources: list[str]
    required: bool = True


class RuntimeVariableInferencer:
    """Infer dynamic runtime variables from intent/workflow/request payloads.

    This class is intentionally domain-neutral. It does not hardcode business
    fields such as weather, flight, booking, etc. Instead it walks generic
    runtime structures and extracts values that came from user input,
    parsed entities, temporal expressions, workflow parameters, schemas and
    evidence metadata. Any such value is treated as runtime data and must be
    read from payload by generated code instead of being hardcoded.
    """

    DYNAMIC_CONTAINER_KEYS = {
        "known",
        "known_parameters",
        "parsed_entities",
        "temporal_expressions",
        "runtime_modifiers",
        "runtime_constraints",
        "output_preferences",
        "parameters",
        "optional_parameters",
        "parameter_mapping",
    }
    STRUCTURAL_SKIP_KEYS = {
        "api_discovery",
        "external_solution_discovery",
        "documentation_evidence",
        "web_evidence",
        "documents",
        "web_results",
        "checks",
        "sample",
        "text_excerpt",
        "selected_evidence",
        "source_provenance",
        "files",
    }
    VALUE_MIN_LEN = 2

    def infer(self, payload: dict[str, Any]) -> dict[str, Any]:
        variables: dict[str, RuntimeVariable] = {}
        self._visit(payload, path=[], variables=variables)
        schema_vars = self._schema_variables(payload)
        for name in schema_vars:
            self._add_variable(variables, name=name, values=[], source="input_schema", required=True)
        result = [asdict(v) for v in variables.values() if v.name]
        result.sort(key=lambda x: x["name"])
        return {
            "runtime_variables": result,
            "parameterization_policy": {
                "payload_driven": True,
                "forbid_hardcoded_runtime_values": True,
                "value_sources": [
                    "original_user_input",
                    "input_parsing",
                    "intent_recognition",
                    "workflow_planning",
                    "runtime_request_semantics",
                    "step.parameters",
                    "capability_schema",
                    "evidence_candidate_fields",
                ],
                "required_access_patterns": [
                    "payload.get(name)",
                    "payload.get('known', {}).get(name)",
                    "payload.get('parameters', {}).get('known', {}).get(name)",
                ],
            },
        }

    def _visit(self, obj: Any, *, path: list[str], variables: dict[str, RuntimeVariable]) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                key_s = str(key)
                if key_s in self.STRUCTURAL_SKIP_KEYS:
                    continue
                new_path = path + [key_s]
                if key_s in {"known", "known_parameters", "parsed_entities", "parameter_mapping", "optional_parameters", "output_preferences", "runtime_constraints"} and isinstance(value, dict):
                    for k, v in value.items():
                        if isinstance(v, (dict, list)):
                            self._visit(v, path=new_path + [str(k)], variables=variables)
                        else:
                            self._add_variable(variables, name=str(k), values=self._aliases(v), source=".".join(new_path))
                    continue
                if key_s == "temporal_expressions" and isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            name = str(item.get("name") or item.get("field") or item.get("value_type") or "date")
                            vals = self._aliases(item.get("normalized_value")) + self._aliases(item.get("text"))
                            self._add_variable(variables, name=name, values=vals, source=".".join(new_path))
                    continue
                if key_s == "runtime_request_semantics" and isinstance(value, dict):
                    self._visit(value, path=new_path, variables=variables)
                    continue
                if key_s == "step" and isinstance(value, dict):
                    self._visit(value.get("parameters") or {}, path=new_path + ["parameters"], variables=variables)
                    continue
                if isinstance(value, (dict, list)):
                    self._visit(value, path=new_path, variables=variables)
        elif isinstance(obj, list):
            for idx, item in enumerate(obj[:50]):
                self._visit(item, path=path + [str(idx)], variables=variables)

    def _schema_variables(self, payload: dict[str, Any]) -> set[str]:
        out: set[str] = set()
        def visit(obj: Any):
            if isinstance(obj, dict):
                schema = obj.get("input_schema") if isinstance(obj.get("input_schema"), dict) else None
                if schema:
                    props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
                    out.update(str(k) for k in props.keys())
                    for k in schema.get("required") or []:
                        out.add(str(k))
                for k, v in obj.items():
                    if k in self.STRUCTURAL_SKIP_KEYS:
                        continue
                    if isinstance(v, (dict, list)):
                        visit(v)
            elif isinstance(obj, list):
                for x in obj[:50]:
                    visit(x)
        visit(payload)
        return out

    def _add_variable(self, variables: dict[str, RuntimeVariable], *, name: str, values: list[str], source: str, required: bool = True) -> None:
        clean_name = self._safe_name(name)
        if not clean_name:
            return
        aliases = [v for v in values if self._is_dynamic_value(v)]
        existing = variables.get(clean_name)
        if existing is None:
            variables[clean_name] = RuntimeVariable(name=clean_name, aliases=[], sources=[], required=required)
            existing = variables[clean_name]
        for alias in aliases:
            if alias not in existing.aliases:
                existing.aliases.append(alias)
        if source and source not in existing.sources:
            existing.sources.append(source)
        existing.required = existing.required or required

    def _safe_name(self, value: str) -> str:
        value = re.sub(r"[^0-9a-zA-Z_]+", "_", str(value or "").strip()).strip("_").lower()
        if not value or value in {"parameters", "known", "optional", "context", "source_step"}:
            return ""
        return value

    def _aliases(self, value: Any) -> list[str]:
        out: list[str] = []
        def add(x: Any):
            if x is None:
                return
            if isinstance(x, (int, float, bool)):
                out.append(str(x))
                return
            if isinstance(x, str):
                s = x.strip()
                if s:
                    out.append(s)
                    if "T" in s and len(s) >= 10:
                        out.append(s[:10])
                    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
                        y, m, d = s.split("-")
                        out.extend([f"{m}/{d}", f"{int(m)}/{int(d)}", f"{m}-{d}", f"{int(m)}-{int(d)}", str(int(d))])
                return
            if isinstance(x, list):
                for item in x[:10]:
                    add(item)
        add(value)
        dedup: list[str] = []
        for item in out:
            if item not in dedup and self._is_dynamic_value(item):
                dedup.append(item)
        return dedup

    def _is_dynamic_value(self, value: str) -> bool:
        s = str(value or "").strip()
        if len(s) < self.VALUE_MIN_LEN:
            return False
        if s.lower() in {"true", "false", "none", "null", "yes", "no", "api", "json", "html", "get", "post"}:
            return False
        return True
