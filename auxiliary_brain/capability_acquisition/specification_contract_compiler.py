from __future__ import annotations

from copy import deepcopy
from ai_core.safe_collections import safe_string_set
from typing import Any


class CapabilitySpecificationContractCompiler:
    """Compile a capability blueprint into the single contract used by generation,
    sandbox validation, and registration.

    This compiler is intentionally generic. It does not know capability names or
    business domains. It only preserves and normalizes declared interface facts:
    field names, JSON value types, defaults, schema-level formats, and explicit
    field-to-field constraints. Generated code must implement this contract;
    sandbox validation must verify this same contract.
    """

    def compile(self, *, blueprint: dict[str, Any], input_schema: dict[str, Any], output_schema: dict[str, Any], connection_schema: dict[str, Any] | None = None, secret_schema: dict[str, Any] | None = None, verification_input: dict[str, Any], verification_expectations: dict[str, Any] | None = None) -> dict[str, Any]:
        source = deepcopy(blueprint if isinstance(blueprint, dict) else {})
        input_contracts = self._field_contracts(input_schema, root="input")
        connection_contracts = self._field_contracts(connection_schema or {}, root="connection")
        secret_contracts = self._field_contracts(secret_schema or {}, root="secrets")
        output_contracts = self._field_contracts(output_schema, root="output")
        bindings = self._declared_output_bindings(output_schema)
        default_bindings = self._infer_generic_default_bindings(input_contracts=input_contracts, output_contracts=output_contracts)
        bindings.extend(item for item in default_bindings if item not in bindings)
        verification_contract = {
            "status": "contract_compiled",
            "input_contracts": input_contracts,
            "connection_contracts": connection_contracts,
            "secret_contracts": secret_contracts,
            "output_contracts": output_contracts,
            "output_bindings": bindings,
            "required_output_paths": self._required_output_paths(output_schema),
            "expected_status": (verification_expectations or {}).get("status", "completed"),
            "verification_input": deepcopy(verification_input if isinstance(verification_input, dict) else {}),
        }
        return {
            "schema_version": "capability-specification-contract/v1",
            "source": "capability_blueprint_specification_compiler",
            "capability_identity": {
                "capability_id": source.get("capability_id") or source.get("template_id") or source.get("tool_id"),
                "capability_name": source.get("capability_name") or source.get("name"),
            },
            "input_schema": deepcopy(input_schema),
            "connection_schema": deepcopy(connection_schema or {}),
            "secret_schema": deepcopy(secret_schema or {}),
            "output_schema": deepcopy(output_schema),
            "verification_contract": verification_contract,
            "generation_requirements": {
                "must_implement_input_contracts": True,
                "must_implement_output_contracts": True,
                "must_preserve_declared_connection_contracts": True,
                "must_preserve_declared_secret_contracts": True,
                "must_not_copy_format_or_template_values_as_runtime_outputs": True,
                "must_return_json_serializable_object": True,
                "must_place_declared_output_values_under_top_level_or_data_object": True,
                "format_handling_policy": "The code generator owns any interpretation required by declared field contracts. Sandbox and validators must not translate, repair, or guess formats. Generated code must use the schema/default/verification contract to produce runtime values that satisfy the declared output contract.",
            },
        }

    def _field_contracts(self, schema: dict[str, Any], *, root: str) -> list[dict[str, Any]]:
        contracts: list[dict[str, Any]] = []
        self._walk_schema(schema if isinstance(schema, dict) else {}, root=root, path=root, required=safe_string_set(schema.get("required", [])) if isinstance(schema, dict) and isinstance(schema.get("required"), list) else set(), out=contracts)
        return contracts

    def _walk_schema(self, schema: dict[str, Any], *, root: str, path: str, required: set[str], out: list[dict[str, Any]]) -> None:
        props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        for name, prop in props.items():
            if not isinstance(prop, dict):
                prop = {}
            child_path = f"{path}.{name}"
            contract = {
                "path": child_path,
                "name": str(name),
                "json_type": prop.get("type", "string"),
                "required": str(name) in required,
            }
            for key in ("format", "pattern", "enum", "default", "description", "examples", "minimum", "maximum", "minLength", "maxLength"):
                if key in prop:
                    contract[key] = deepcopy(prop[key])
            for key, value in prop.items():
                if isinstance(key, str) and key.startswith("x-"):
                    contract[key] = deepcopy(value)
            value_contract = self._value_contract_from_schema(contract)
            if value_contract:
                contract["value_contract"] = value_contract
            out.append(contract)
            nested_required = safe_string_set(prop.get("required", [])) if isinstance(prop.get("required"), list) else set()
            self._walk_schema(prop, root=root, path=child_path, required=nested_required, out=out)

    def _required_output_paths(self, output_schema: dict[str, Any]) -> list[str]:
        paths: list[str] = []
        for item in self._field_contracts(output_schema, root="output"):
            if item.get("required"):
                paths.append(str(item.get("path")))
        return paths

    def _declared_output_bindings(self, output_schema: dict[str, Any]) -> list[dict[str, Any]]:
        bindings: list[dict[str, Any]] = []
        for item in self._field_contracts(output_schema, root="output"):
            source = item.get("x-format-source") or item.get("x-format-source-field") or item.get("x-value-source")
            if source:
                bindings.append({
                    "output_path": item.get("path"),
                    "source_path": str(source) if str(source).startswith("input.") else f"input.{source}",
                    "binding_type": "declared_field_binding",
                    "binding_policy": "generator_must_satisfy_source_contract; sandbox_must_only_verify",
                })
        return bindings

    def _infer_generic_default_bindings(self, *, input_contracts: list[dict[str, Any]], output_contracts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Generic fallback: if the interface has one declared input field whose
        # schema role is a format/template contract, expose that field as a
        # source contract for string outputs. This does not translate the value;
        # it only tells the generator and validator that such a relationship
        # exists. The generated implementation must satisfy it.
        format_sources = [item for item in input_contracts if self._is_format_contract(item)]
        if len(format_sources) != 1:
            return []
        source = format_sources[0]
        bindings: list[dict[str, Any]] = []
        for output in output_contracts:
            if output.get("json_type") == "string" and not str(output.get("name") or "").casefold().endswith("zone"):
                bindings.append({
                    "output_path": output.get("path"),
                    "source_path": source.get("path"),
                    "binding_type": "schema_role_inferred_format_source",
                    "binding_policy": "generator_must_satisfy_source_contract; sandbox_must_only_verify",
                })
        return bindings

    def _is_format_contract(self, item: dict[str, Any]) -> bool:
        role = str(item.get("x-role") or item.get("format") or item.get("name") or "").casefold()
        return "format" in role or "template" in role

    def _value_contract_from_schema(self, contract: dict[str, Any]) -> dict[str, Any]:
        value_contract: dict[str, Any] = {}
        role = str(contract.get("x-role") or contract.get("name") or "").casefold()
        if "format" in role or "template" in role:
            value_contract["role"] = "format" if "format" in role else "template"
            if "default" in contract:
                value_contract["declared_default"] = deepcopy(contract.get("default"))
            if "examples" in contract:
                value_contract["examples"] = deepcopy(contract.get("examples"))
            value_contract["generation_responsibility"] = "generated_code_must_interpret_or_use_this_contract"
            value_contract["validation_responsibility"] = "validator_checks_outputs_against_contract_without_translating_inputs"
        if contract.get("format"):
            value_contract.setdefault("schema_format", deepcopy(contract.get("format")))
        if contract.get("pattern"):
            value_contract.setdefault("pattern", deepcopy(contract.get("pattern")))
        return value_contract
