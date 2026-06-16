from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FormationAssessment:
    """Generic capability formation assessment.

    The assessment is intentionally capability-neutral.  It never classifies by
    business words, provider names, product names, or requested capability id.
    It only checks whether the acquisition pipeline already has enough contract
    material to ask a code generator for implementation without making it repeat
    intent recognition or planning.
    """

    status: str
    level: str
    confidence: float
    passed: bool
    reasons: list[str]
    missing_contracts: list[str]
    generation_strategy: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "level": self.level,
            "confidence": self.confidence,
            "passed": self.passed,
            "reasons": list(self.reasons),
            "missing_contracts": list(self.missing_contracts),
            "generation_strategy": dict(self.generation_strategy),
            "classifier": "capability_formation_contract_v1",
        }


class CapabilityFormationContractBuilder:
    """Build and devil-validate a generic formation contract.

    Design boundary:
    - No capability-specific branches.
    - No hard-coded application domain handling.
    - No provider/product keyword routing.
    - The only signal is completeness of lifecycle contracts produced by earlier
      stages: identity, schema boundary, runtime execution policy, approval, and
      verification.
    """

    def build(
        self,
        *,
        blueprint: dict[str, Any],
        identity_contract: dict[str, Any],
        input_schema: dict[str, Any],
        output_schema: dict[str, Any],
        connection_schema: dict[str, Any],
        secret_schema: dict[str, Any],
        runtime_execution_policy: dict[str, Any],
        approval_policy: dict[str, Any],
        verification_input: dict[str, Any],
        verification_expectations: dict[str, Any],
        specification_contract: dict[str, Any],
    ) -> dict[str, Any]:
        capability_id = str(
            blueprint.get("capability_id")
            or blueprint.get("tool_id")
            or blueprint.get("template_id")
            or identity_contract.get("requested_capability_id")
            or ""
        ).strip()
        entrypoint = blueprint.get("entrypoint") if isinstance(blueprint.get("entrypoint"), dict) else {}
        field_contracts = {
            "input": self._field_contracts_from_schema(input_schema, scope="input"),
            "output": self._field_contracts_from_schema(output_schema, scope="output"),
            "connection": self._field_contracts_from_schema(connection_schema, scope="connection"),
            "secrets": self._field_contracts_from_schema(secret_schema, scope="secrets"),
        }
        contract = {
            "identity": {
                "capability_id": capability_id,
                "capability_name": blueprint.get("capability_name") or blueprint.get("name") or identity_contract.get("requested_capability_name"),
                "entrypoint": {
                    "module": entrypoint.get("module") or "tool.py",
                    "function": entrypoint.get("function") or "run",
                },
            },
            "schemas": {
                "input_schema": input_schema,
                "output_schema": output_schema,
                "connection_schema": connection_schema,
                "secret_schema": secret_schema,
            },
            "field_contracts": field_contracts,
            "runtime": runtime_execution_policy,
            "approval": approval_policy,
            "verification": {
                "verification_input": verification_input,
                "verification_expectations": verification_expectations,
            },
            "specification_contract": self._compact_spec(specification_contract),
        }
        assessment = self.assess(contract)
        return {"contract": contract, "assessment": assessment.to_dict()}

    def assess(self, formation_contract: dict[str, Any]) -> FormationAssessment:
        missing: list[str] = []
        reasons: list[str] = []
        identity = formation_contract.get("identity") if isinstance(formation_contract.get("identity"), dict) else {}
        schemas = formation_contract.get("schemas") if isinstance(formation_contract.get("schemas"), dict) else {}
        runtime = formation_contract.get("runtime") if isinstance(formation_contract.get("runtime"), dict) else {}
        approval = formation_contract.get("approval") if isinstance(formation_contract.get("approval"), dict) else {}
        verification = formation_contract.get("verification") if isinstance(formation_contract.get("verification"), dict) else {}

        if not str(identity.get("capability_id") or "").strip():
            missing.append("identity.capability_id")
        entrypoint = identity.get("entrypoint") if isinstance(identity.get("entrypoint"), dict) else {}
        if not str(entrypoint.get("module") or "").strip() or not str(entrypoint.get("function") or "").strip():
            missing.append("identity.entrypoint")

        field_contracts = formation_contract.get("field_contracts") if isinstance(formation_contract.get("field_contracts"), dict) else {}
        schema_to_scope = {
            "input_schema": "input",
            "output_schema": "output",
            "connection_schema": "connection",
            "secret_schema": "secrets",
        }
        for schema_name in ("input_schema", "output_schema", "connection_schema", "secret_schema"):
            schema = schemas.get(schema_name)
            if not self._is_json_schema(schema):
                missing.append(f"schemas.{schema_name}")
            elif schema_name in {"connection_schema", "secret_schema"} and not self._is_closed_schema(schema):
                missing.append(f"schemas.{schema_name}.additionalProperties_false")
            scope = schema_to_scope[schema_name]
            contracts = field_contracts.get(scope) if isinstance(field_contracts.get(scope), dict) else {}
            if not isinstance(contracts, dict):
                missing.append(f"field_contracts.{scope}")
            elif isinstance(schema, dict):
                props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
                required = {str(x) for x in schema.get("required", []) if isinstance(x, str)} if isinstance(schema.get("required"), list) else set()
                for field_name in props.keys():
                    item = contracts.get(str(field_name)) if isinstance(contracts.get(str(field_name)), dict) else None
                    if item is None or "required" not in item:
                        missing.append(f"field_contracts.{scope}.{field_name}.required")
                    elif bool(item.get("required")) != (str(field_name) in required):
                        missing.append(f"field_contracts.{scope}.{field_name}.schema_required_mismatch")

        if not runtime:
            missing.append("runtime")
        else:
            # These are generic execution safety signals, not capability type signals.
            if "side_effects" not in runtime:
                missing.append("runtime.side_effects")
            if "network_access" not in runtime and "external_access" not in runtime:
                missing.append("runtime.network_access")

        if not approval:
            missing.append("approval")
        else:
            if not isinstance(approval.get("supported_modes"), list) or not approval.get("supported_modes"):
                missing.append("approval.supported_modes")
            if not str(approval.get("default_mode") or approval.get("mode") or "").strip():
                missing.append("approval.default_mode")

        if not isinstance(verification.get("verification_input"), dict):
            missing.append("verification.verification_input")
        if not isinstance(verification.get("verification_expectations"), dict):
            missing.append("verification.verification_expectations")

        # Devil validation: reject large opaque contracts that would force the
        # code generator to re-plan.  This keeps generation fast and grounded.
        contract_size = len(json.dumps(formation_contract, ensure_ascii=False, default=str))
        if contract_size > 22000:
            missing.append("contract.size_within_generation_budget")
            reasons.append("formation contract is too large for reliable single-pass generation")

        score_units = 12
        score = max(0, score_units - len(set(missing))) / score_units
        if score >= 0.92:
            level = "level_1_contract_complete"
            strategy = {"llm_attempts": 1, "prompt_mode": "formation_contract_only", "retry_repair": False}
        elif score >= 0.67:
            level = "level_2_contract_partial"
            strategy = {"llm_attempts": 2, "prompt_mode": "formation_contract_plus_compact_spec", "retry_repair": True}
        else:
            level = "level_3_open_ended"
            strategy = {"llm_attempts": 4, "prompt_mode": "full_compact_contract", "retry_repair": True}

        passed = score >= 0.67
        if not reasons:
            reasons.append("contract completeness assessed without capability-specific routing")
        status = "passed" if passed else "incomplete"
        return FormationAssessment(
            status=status,
            level=level,
            confidence=round(score, 3),
            passed=passed,
            reasons=reasons,
            missing_contracts=sorted(set(missing)),
            generation_strategy=strategy,
        )


    def normalize_schemas_from_field_contracts(self, formation_contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Derive schema.required arrays mechanically from Formation Contract.

        Requiredness may be decided while forming the contract, but downstream
        schemas are not allowed to make a second independent decision.  This
        keeps schema, runtime validation, sandbox samples, and registry metadata
        aligned without using capability names or field-name special cases.
        """
        if not isinstance(formation_contract, dict):
            return {}
        schemas = formation_contract.get("schemas") if isinstance(formation_contract.get("schemas"), dict) else {}
        field_contracts = formation_contract.get("field_contracts") if isinstance(formation_contract.get("field_contracts"), dict) else {}
        result: dict[str, dict[str, Any]] = {}
        mapping = {
            "input_schema": "input",
            "output_schema": "output",
            "connection_schema": "connection",
            "secret_schema": "secrets",
        }
        for schema_name, scope in mapping.items():
            schema = schemas.get(schema_name) if isinstance(schemas.get(schema_name), dict) else {}
            contracts = field_contracts.get(scope) if isinstance(field_contracts.get(scope), dict) else {}
            result[schema_name] = self._schema_with_required_from_contract(schema, contracts)
        return result

    def _schema_with_required_from_contract(self, schema: dict[str, Any], field_contract: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(schema) if isinstance(schema, dict) else {"type": "object", "properties": {}}
        normalized.setdefault("type", "object")
        props = normalized.get("properties") if isinstance(normalized.get("properties"), dict) else {}
        normalized["properties"] = props
        required: list[str] = []
        for name in props.keys():
            item = field_contract.get(str(name)) if isinstance(field_contract.get(str(name)), dict) else {}
            if bool(item.get("required")) and str(name) not in required:
                required.append(str(name))
        normalized["required"] = required
        if props:
            normalized.setdefault("additionalProperties", False)
        return normalized

    def _field_contracts_from_schema(self, schema: dict[str, Any], *, scope: str) -> dict[str, dict[str, Any]]:
        if not isinstance(schema, dict):
            return {}
        props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        declared_required = {str(x) for x in schema.get("required", []) if isinstance(x, str)} if isinstance(schema.get("required"), list) else set()
        has_declared_required_array = isinstance(schema.get("required"), list) and bool(schema.get("required"))
        contracts: dict[str, dict[str, Any]] = {}
        for name, raw_field_schema in props.items():
            field_name = str(name)
            field_schema = raw_field_schema if isinstance(raw_field_schema, dict) else {}
            explicit = self._explicit_requiredness(field_schema)
            if explicit is not None:
                required = explicit
                source = "field_explicit_requiredness"
            elif field_name in declared_required:
                required = True
                source = "schema_required_array"
            elif scope in {"connection", "secrets"} and not has_declared_required_array and not self._has_runtime_default(field_schema):
                # Generic operational dependency rule: connection/secret values
                # without an explicit default or optional marker are required to
                # initialize a side-effecting runtime.  This is scope-based, not
                # capability-name or field-name routing.
                required = True
                source = "operational_dependency_without_default"
            else:
                required = False
                source = "contract_optional"
            contracts[field_name] = {
                "required": bool(required),
                "source": source,
                "has_default": self._has_runtime_default(field_schema),
            }
        return contracts

    def _explicit_requiredness(self, field_schema: dict[str, Any]) -> bool | None:
        for key in ("x-required", "required"):
            if key in field_schema and isinstance(field_schema.get(key), bool):
                return bool(field_schema.get(key))
        for key in ("x-optional", "optional", "nullable"):
            if key in field_schema and isinstance(field_schema.get(key), bool):
                if bool(field_schema.get(key)):
                    return False
        return None

    def _has_runtime_default(self, field_schema: dict[str, Any]) -> bool:
        if not isinstance(field_schema, dict):
            return False
        if "default" in field_schema:
            return True
        if "const" in field_schema:
            return True
        typ = field_schema.get("type")
        if isinstance(typ, list) and "null" in typ:
            return True
        if field_schema.get("nullable") is True:
            return True
        return False

    def _is_json_schema(self, value: Any) -> bool:
        if not isinstance(value, dict):
            return False
        if str(value.get("type") or "object") != "object":
            return False
        return isinstance(value.get("properties", {}), dict)

    def _is_closed_schema(self, value: Any) -> bool:
        if not isinstance(value, dict):
            return False
        return value.get("additionalProperties") is False

    def _compact_spec(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        keep = {"schema_version", "capability_identity", "verification_contract", "security_contract", "output_bindings"}
        compact = {k: value.get(k) for k in keep if k in value}
        raw = json.dumps(compact, ensure_ascii=False, default=str)
        if len(raw) > 5000:
            return {"schema_version": value.get("schema_version"), "summary": raw[:5000]}
        return compact
