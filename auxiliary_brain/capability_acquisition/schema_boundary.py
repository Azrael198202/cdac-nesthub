from __future__ import annotations

from copy import deepcopy
from typing import Any


class CapabilitySchemaBoundary:
    """Keep generated capability contracts split by lifecycle.

    The boundary is intentionally capability-neutral.  It does not know what a
    tool does and it does not contain domain templates.  It only follows JSON
    schema annotations and generic sensitivity/configuration metadata so that:

    - input_schema contains values supplied at invocation time;
    - connection_schema contains non-secret values saved in a runtime profile;
    - secret_schema contains secret values saved in the secret/profile store.

    Generated artifacts may propose schemas in imperfect shape.  This class
    normalizes those schemas before verification, registration, and execution.
    """

    INPUT = "input"
    CONNECTION = "connection"
    SECRETS = "secrets"

    def normalize(
        self,
        *,
        input_schema: dict[str, Any] | None,
        connection_schema: dict[str, Any] | None,
        secret_schema: dict[str, Any] | None,
        verification_input: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        input_schema = self._object_schema(input_schema, "input")
        connection_schema = self._object_schema(connection_schema, "connection")
        secret_schema = self._object_schema(secret_schema, "secrets")

        schemas = {
            self.INPUT: input_schema,
            self.CONNECTION: connection_schema,
            self.SECRETS: secret_schema,
        }

        # First honor explicit lifecycle annotations on every schema section.
        for section in (self.INPUT, self.CONNECTION, self.SECRETS):
            self._move_annotated_fields(schemas, source_section=section)

        # Then remove duplicates with deterministic precedence.  A field cannot
        # be both invocation-time input and preset configuration.  Secret wins
        # over connection; connection wins over input for fields already declared
        # in preset schemas.  This is schema lifecycle logic, not capability logic.
        self._deduplicate_by_precedence(schemas)
        for schema in schemas.values():
            self._close_and_sort_required(schema)

        normalized_verification = self.normalize_verification_input(
            verification_input or {},
            input_schema=schemas[self.INPUT],
            connection_schema=schemas[self.CONNECTION],
            secret_schema=schemas[self.SECRETS],
        )
        return {
            "input_schema": schemas[self.INPUT],
            "connection_schema": schemas[self.CONNECTION],
            "secret_schema": schemas[self.SECRETS],
            "verification_input": normalized_verification,
        }

    def normalize_verification_input(
        self,
        verification_input: dict[str, Any] | None,
        *,
        input_schema: dict[str, Any] | None,
        connection_schema: dict[str, Any] | None,
        secret_schema: dict[str, Any] | None,
    ) -> dict[str, Any]:
        payload = deepcopy(verification_input) if isinstance(verification_input, dict) else {}
        out = {
            "input": payload.get("input") if isinstance(payload.get("input"), dict) else {},
            "connection": payload.get("connection") if isinstance(payload.get("connection"), dict) else {},
            "secrets": payload.get("secrets") if isinstance(payload.get("secrets"), dict) else {},
        }
        # Some older planners put all values at the root.  Route only by schema
        # membership.  Unknown values stay out of the executable payload.
        root_values = {k: v for k, v in payload.items() if k not in {"input", "connection", "secrets", "_runtime"}}
        for key, value in root_values.items():
            section = self.section_for_field(
                key,
                input_schema=input_schema or {},
                connection_schema=connection_schema or {},
                secret_schema=secret_schema or {},
            )
            if section:
                out[section][key] = value
        # Re-project explicit nested values too, in case an older artifact placed
        # preset values under input.  Values whose names are unknown to the final
        # schemas are not copied into executable verification payloads.
        for section_name in ("input", "connection", "secrets"):
            values = payload.get(section_name)
            if not isinstance(values, dict):
                continue
            for key, value in values.items():
                target = self.section_for_field(
                    key,
                    input_schema=input_schema or {},
                    connection_schema=connection_schema or {},
                    secret_schema=secret_schema or {},
                )
                if target in out:
                    out[target][key] = value
        for section_name, schema in (("input", input_schema or {}), ("connection", connection_schema or {}), ("secrets", secret_schema or {})):
            allowed = set(self._properties(schema).keys())
            out[section_name] = {k: v for k, v in out[section_name].items() if k in allowed}
        return out

    def section_for_field(
        self,
        field_name: str,
        *,
        input_schema: dict[str, Any],
        connection_schema: dict[str, Any],
        secret_schema: dict[str, Any],
    ) -> str | None:
        name = str(field_name or "")
        if name in self._properties(secret_schema):
            return "secrets"
        if name in self._properties(connection_schema):
            return "connection"
        if name in self._properties(input_schema):
            return "input"
        return None

    def _move_annotated_fields(self, schemas: dict[str, dict[str, Any]], *, source_section: str) -> None:
        source = schemas[source_section]
        props = self._properties(source)
        for field_name, prop in list(props.items()):
            prop = prop if isinstance(prop, dict) else {}
            target = self._declared_lifecycle(prop)
            if target is None:
                # Secret metadata is part of JSON schema / UI contract.  It is
                # generic and not tied to a business capability.
                if self._is_secret_property(prop):
                    target = self.SECRETS
            if target is None or target == source_section:
                continue
            self._move_field(schemas, field_name=str(field_name), source_section=source_section, target_section=target)

    def _declared_lifecycle(self, prop: dict[str, Any]) -> str | None:
        markers: list[Any] = [
            prop.get("x-runtime-source"),
            prop.get("x-lifecycle"),
            prop.get("x-capability-section"),
            prop.get("x-config-section"),
        ]
        for marker in markers:
            text = str(marker or "").strip().casefold().replace("-", "_")
            if text in {"runtime", "runtime_input", "input", "invocation", "invocation_input"}:
                return self.INPUT
            if text in {"connection", "connections", "profile", "config", "configuration", "preset", "preset_config"}:
                return self.CONNECTION
            if text in {"secret", "secrets", "credential", "credentials", "sensitive"}:
                return self.SECRETS
        if prop.get("x-secret") is True or prop.get("x-sensitive") is True:
            return self.SECRETS
        if prop.get("x-connection") is True or prop.get("x-preset") is True or prop.get("x-profile") is True:
            return self.CONNECTION
        return None

    def _is_secret_property(self, prop: dict[str, Any]) -> bool:
        if prop.get("writeOnly") is True:
            return True
        fmt = str(prop.get("format") or prop.get("contentFormat") or "").strip().casefold()
        if fmt in {"password", "secret", "credential", "token"}:
            return True
        return False

    def _move_field(self, schemas: dict[str, dict[str, Any]], *, field_name: str, source_section: str, target_section: str) -> None:
        source = schemas[source_section]
        target = schemas[target_section]
        source_props = self._properties(source)
        target_props = self._properties(target)
        was_required = self._was_required(source, field_name)
        prop = deepcopy(source_props.pop(field_name, {}))
        # Remove routing-only metadata from the executable schema shape while
        # preserving descriptive metadata useful to UI/rendering.
        for key in ("x-runtime-source", "x-lifecycle", "x-capability-section", "x-config-section"):
            prop.pop(key, None)
        target_props.setdefault(field_name, prop)
        self._remove_required(source, field_name)
        if was_required:
            self._add_required(target, field_name)

    def _deduplicate_by_precedence(self, schemas: dict[str, dict[str, Any]]) -> None:
        secret_fields = set(self._properties(schemas[self.SECRETS]).keys())
        connection_fields = set(self._properties(schemas[self.CONNECTION]).keys())
        for name in secret_fields:
            self._properties(schemas[self.CONNECTION]).pop(name, None)
            self._properties(schemas[self.INPUT]).pop(name, None)
            self._remove_required(schemas[self.CONNECTION], name)
            self._remove_required(schemas[self.INPUT], name)
        for name in connection_fields:
            if name in secret_fields:
                continue
            self._properties(schemas[self.INPUT]).pop(name, None)
            self._remove_required(schemas[self.INPUT], name)

    def _object_schema(self, schema: dict[str, Any] | None, title: str) -> dict[str, Any]:
        if not isinstance(schema, dict):
            schema = {}
        out = deepcopy(schema)
        out["type"] = "object"
        if not isinstance(out.get("properties"), dict):
            out["properties"] = {}
        if not isinstance(out.get("required"), list):
            out["required"] = []
        out.setdefault("additionalProperties", False)
        out.setdefault("title", title)
        return out

    def _properties(self, schema: dict[str, Any]) -> dict[str, Any]:
        props = schema.get("properties")
        if not isinstance(props, dict):
            schema["properties"] = {}
        return schema["properties"]

    def _required(self, schema: dict[str, Any]) -> set[str]:
        return {str(x) for x in schema.get("required", []) if isinstance(x, str) and str(x).strip()}

    def _was_required(self, schema: dict[str, Any], field_name: str) -> bool:
        return field_name in self._required(schema)

    def _remove_required(self, schema: dict[str, Any], field_name: str) -> None:
        schema["required"] = [x for x in schema.get("required", []) if str(x) != str(field_name)]

    def _add_required(self, schema: dict[str, Any], field_name: str) -> None:
        required = self._required(schema)
        required.add(str(field_name))
        schema["required"] = sorted(required)

    def _close_and_sort_required(self, schema: dict[str, Any]) -> None:
        props = self._properties(schema)
        required = [name for name in sorted(self._required(schema)) if name in props]
        schema["required"] = required
        schema.setdefault("additionalProperties", False)
