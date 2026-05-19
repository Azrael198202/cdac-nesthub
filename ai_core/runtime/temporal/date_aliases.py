from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class DateAliasGenerator:
    """Builds temporal aliases without hard-coded natural-language month names.

    The core can safely generate numeric aliases from ISO-like dates.  Any
    language-specific aliases must be supplied by runtime state, generated
    contracts, or source-specific extractors.  This keeps ai_core generic while
    still allowing multilingual matching when a runtime contract exists.
    """

    ISO_DATE = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$")

    def aliases_for(self, value: Any, *, runtime_state: dict[str, Any] | None = None) -> list[str]:
        result: list[str] = []
        self._collect(value, result)
        self._collect_runtime_aliases(value, runtime_state or {}, result)
        return self._dedupe(result)

    def aliases_from_state(self, state: dict[str, Any]) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}

        def add(name: str, value: Any) -> None:
            aliases = self.aliases_for(value, runtime_state=state)
            if not aliases:
                return
            bucket = result.setdefault(str(name or "value"), [])
            for alias in aliases:
                if alias not in bucket:
                    bucket.append(alias)

        for item in state.get("runtime_variables", []) if isinstance(state.get("runtime_variables"), list) else []:
            if isinstance(item, dict):
                name = str(item.get("name") or "value")
                for alias in item.get("aliases") or []:
                    add(name, alias)
                if item.get("value") is not None:
                    add(name, item.get("value"))

        for section_name in ("runtime_request_semantics", "parameters", "known", "input", "results"):
            section = state.get(section_name)
            if isinstance(section, dict):
                self._walk_section(section, add)

        for node in state.get("workflow_results", {}).values() if isinstance(state.get("workflow_results"), dict) else []:
            if isinstance(node, dict):
                self._walk_section(node, add)

        for item in state.get("temporal_expressions", []) if isinstance(state.get("temporal_expressions"), list) else []:
            if isinstance(item, dict):
                name = str(item.get("name") or item.get("value_type") or "temporal")
                add(name, item.get("text"))
                add(name, item.get("normalized_value"))

        return result

    def _walk_section(self, obj: Any, add) -> None:
        if isinstance(obj, dict):
            if "text" in obj and "normalized_value" in obj:
                add(str(obj.get("value_type") or "temporal"), obj.get("text"))
                add(str(obj.get("value_type") or "temporal"), obj.get("normalized_value"))
            for key, value in obj.items():
                if isinstance(value, (dict, list, tuple, set)):
                    self._walk_section(value, add)
                else:
                    add(str(key), value)
        elif isinstance(obj, (list, tuple, set)):
            for item in obj:
                self._walk_section(item, add)

    def _collect(self, value: Any, out: list[str]) -> None:
        if value is None:
            return
        if isinstance(value, dict):
            for item in value.values():
                self._collect(item, out)
            return
        if isinstance(value, (list, tuple, set)):
            for item in value:
                self._collect(item, out)
            return
        text = str(value).strip()
        if not text:
            return
        out.append(text)
        match = self.ISO_DATE.match(text)
        if not match:
            return
        year_s, month_s, day_s = match.groups()
        year = int(year_s)
        month = int(month_s)
        day = int(day_s)
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return
        yyyy = f"{year:04d}"
        mm = f"{month:02d}"
        dd = f"{day:02d}"
        out.extend([
            f"{yyyy}-{mm}-{dd}", f"{yyyy}/{mm}/{dd}", f"{yyyy}.{mm}.{dd}",
            f"{yyyy}-{month}-{day}", f"{yyyy}/{month}/{day}", f"{yyyy}.{month}.{day}",
            f"{month}/{day}", f"{mm}/{dd}", f"{month}/{dd}", f"{mm}/{day}",
            f"{month}-{day}", f"{mm}-{dd}", f"{month}.{day}", f"{dd}.{mm}",
            str(day), dd,
        ])

    def _collect_runtime_aliases(self, value: Any, state: dict[str, Any], out: list[str]) -> None:
        canonical_values = set(self._canonical_values(value))
        if not canonical_values:
            return

        for item in state.get("temporal_expressions", []) if isinstance(state.get("temporal_expressions"), list) else []:
            if not isinstance(item, dict):
                continue
            normalized = str(item.get("normalized_value") or "").strip()
            if normalized in canonical_values:
                text = str(item.get("text") or "").strip()
                if text:
                    out.append(text)

        for item in state.get("runtime_variables", []) if isinstance(state.get("runtime_variables"), list) else []:
            if not isinstance(item, dict):
                continue
            values = self._canonical_values(item.get("value")) | self._canonical_values(item.get("normalized_value"))
            if values & canonical_values:
                for alias in item.get("aliases") or []:
                    alias_text = str(alias or "").strip()
                    if alias_text:
                        out.append(alias_text)

        contract_aliases = self._load_contract_aliases()
        for canonical in canonical_values:
            for alias in contract_aliases.get(canonical, []):
                alias_text = str(alias or "").strip()
                if alias_text:
                    out.append(alias_text)

    def _canonical_values(self, value: Any) -> set[str]:
        found: set[str] = set()
        raw: list[str] = []
        self._collect_raw(value, raw)
        for text in raw:
            match = self.ISO_DATE.match(text)
            if match:
                y, m, d = match.groups()
                found.add(f"{int(y):04d}-{int(m):02d}-{int(d):02d}")
            else:
                found.add(text)
        return found

    def _collect_raw(self, value: Any, out: list[str]) -> None:
        if value is None:
            return
        if isinstance(value, dict):
            for item in value.values():
                self._collect_raw(item, out)
            return
        if isinstance(value, (list, tuple, set)):
            for item in value:
                self._collect_raw(item, out)
            return
        text = str(value).strip()
        if text:
            out.append(text)

    def _load_contract_aliases(self) -> dict[str, list[str]]:
        # Optional runtime-generated file.  It is intentionally not shipped with
        # static language data; deployments may generate it with a stronger
        # model or locale provider.
        candidates = [
            Path("runtime/generated/contracts/temporal_aliases.json"),
            Path("runtime/configs/semantic/temporal_aliases.json"),
        ]
        for path in candidates:
            try:
                if not path.exists():
                    continue
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    result: dict[str, list[str]] = {}
                    for key, value in data.items():
                        if isinstance(value, list):
                            result[str(key)] = [str(v) for v in value if str(v or "").strip()]
                    return result
            except Exception:
                continue
        return {}

    def _dedupe(self, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = str(value or "").strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(text)
        return result[:40]
