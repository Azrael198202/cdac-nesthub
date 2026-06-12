from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class StructuralStepPlanner:
    """Builds a conservative fallback graph from declared runtime objects.

    The planner is intentionally domain-neutral. It does not know capability,
    business, language, or operation vocabularies. It only uses:
    - declared participant names/ids;
    - generic sequencing separators loaded from configuration;
    - textual references from generated fragments to declared participant names.

    This fallback is used only when the semantic planner is unavailable, so the
    runtime can still preserve explicit dataflow instead of silently dropping a
    downstream user-requested step.
    """

    DEFAULT_CONFIG = {
        "split_markers": [",finally ", ", finally ", ";finally ", "; finally ", ".finally ", ". finally ", " finally ", " then ", " and then ", " next ", " after that ", "，最后", "。最后", " 最后", " 然后", " 次に", " 最後に"],
        "wrapper_patterns": [r"^\s*create\s+a\s+task\s+named\s+[^,.;。]+\s*,?\s*", r"^\s*create\s+task\s+[^,.;。]+\s*,?\s*"],
        "minimum_generated_fragment_chars": 8,
        "participant_selection_residual_patterns": [r"^(which)?(calls?|uses?|runs?|executes?|invokes?|and|the|a|an|,|\s)+$"],
    }

    def __init__(self, config_path: str | Path | None = None) -> None:
        self.config_path = Path(config_path or "runtime/configs/planning/structural_graph_patterns.json")
        self.config = self._load_config()

    def build_steps(self, instruction: str, participants: list[dict[str, Any]]) -> list[dict[str, Any]]:
        text = self._strip_wrappers(str(instruction or ""))
        explicit_fragments = self._numbered_step_fragments(text)
        fragments = [item["fragment"] for item in explicit_fragments] if explicit_fragments else self._split_fragments(text)
        if not fragments:
            return []

        selected_ids: list[str] = []
        step_aliases: dict[str, str] = {}
        last_outputs: list[str] = []
        steps: list[dict[str, Any]] = []
        for idx, fragment in enumerate(fragments):
            source_step_id = explicit_fragments[idx]["id"] if explicit_fragments and idx < len(explicit_fragments) else ""
            declared_deps = self._declared_step_dependencies(fragment, step_aliases)
            refs = self._referenced_participants(fragment, participants)
            prior_ref_deps = [self._participant_id(p) for p in refs if self._participant_id(p) in selected_ids]
            for dep in prior_ref_deps:
                if dep and dep not in declared_deps:
                    declared_deps.append(dep)
            if explicit_fragments and not declared_deps and not refs and last_outputs:
                declared_deps = list(last_outputs)
            current_outputs: list[str] = []
            # A fragment may contain multiple existing participant references.
            # Each declared participant remains its own executable node so the
            # downstream graph can show parallel branches and bind outputs.
            # If a later fragment mentions an already-selected participant, that
            # mention is treated as a structural upstream material reference, not
            # as a request to execute the upstream participant again.
            added_participant = False
            for participant in refs:
                pid = self._participant_id(participant)
                if not pid or pid in selected_ids:
                    continue
                selected_ids.append(pid)
                step_id = f"declared_step_{len(steps) + 1}"
                steps.append({
                    "id": step_id,
                    "declared_step_id": source_step_id,
                    "label": self._participant_name(participant),
                    "objective": fragment.strip() or self._participant_name(participant),
                    "instruction_fragment": fragment.strip(),
                    "executable": True,
                    "depends_on": list(declared_deps),
                    "input_contract": self._input_contract(declared_deps),
                    "output_contract": self._output_contract(),
                    "route": {"participant_id": pid},
                })
                if source_step_id:
                    step_aliases[source_step_id] = pid
                    step_aliases[source_step_id.casefold()] = pid
                    step_aliases[step_id] = pid
                current_outputs.append(pid)
                added_participant = True

            # If the fragment references already-selected upstream participants
            # but is not just a participant call fragment, keep it as a generated
            # dataflow step. Its objective remains runtime text, not source-code
            # knowledge about a specific operation.
            deps = [self._participant_id(p) for p in refs if self._participant_id(p) in selected_ids]
            for dep in declared_deps:
                if dep and dep not in deps:
                    deps.append(dep)
            if deps and not added_participant and self._should_keep_generated_fragment(fragment, refs, added_participant):
                step_id = f"generated_step_{len(steps) + 1}"
                parameter_contract = self._parameter_contract_from_fragment(fragment)
                capability_profile = self._capability_profile_from_fragment(fragment, parameter_contract)
                steps.append({
                    "id": step_id,
                    "declared_step_id": source_step_id,
                    "label": self._compact_fragment_label(fragment),
                    "objective": fragment.strip(),
                    "instruction_fragment": fragment.strip(),
                    "executable": True,
                    "depends_on": deps,
                    "input_contract": self._input_contract(deps),
                    "output_contract": self._output_contract(),
                    "parameter_contract": parameter_contract,
                    "capability_profile": capability_profile,
                    "route": {"requires_generated_step": True, "capability_profile": capability_profile},
                })
                if source_step_id:
                    step_aliases[source_step_id] = step_id
                    step_aliases[source_step_id.casefold()] = step_id
                current_outputs.append(step_id)
            if not current_outputs and explicit_fragments and self._should_keep_generated_fragment(fragment, refs, added_participant):
                deps = list(declared_deps) if declared_deps else (list(last_outputs) if last_outputs else [])
                step_id = f"generated_step_{len(steps) + 1}"
                parameter_contract = self._parameter_contract_from_fragment(fragment)
                capability_profile = self._capability_profile_from_fragment(fragment, parameter_contract)
                steps.append({
                    "id": step_id,
                    "declared_step_id": source_step_id,
                    "label": self._compact_fragment_label(fragment),
                    "objective": fragment.strip(),
                    "instruction_fragment": fragment.strip(),
                    "executable": True,
                    "depends_on": deps,
                    "input_contract": self._input_contract(deps),
                    "output_contract": self._output_contract(),
                    "parameter_contract": parameter_contract,
                    "capability_profile": capability_profile,
                    "route": {"requires_generated_step": True, "capability_profile": capability_profile},
                })
                if source_step_id:
                    step_aliases[source_step_id] = step_id
                    step_aliases[source_step_id.casefold()] = step_id
                current_outputs.append(step_id)
            if current_outputs:
                last_outputs = list(current_outputs)

        return self._remove_redundant_generated_steps(steps)


    def _parameter_contract_from_fragment(self, fragment: str) -> dict[str, Any]:
        """Infer explicitly requested runtime inputs from generic prompt shape.

        This parser is intentionally structural. It only recognizes the user
        instruction pattern that a value should be asked for when missing and
        turns that value into a runtime parameter contract. It does not encode
        task domains, participant names, or example questions.
        """
        params: list[dict[str, Any]] = []
        seen: set[str] = set()
        text = str(fragment or "")
        patterns = [
            r"(?is)ask\s+(?:the\s+)?user\s+for\s+(?:the\s+)?(?P<items>.+?)\s+if\s+missing",
            r"(?is)(?:only\s+)?ask\s+for\s+(?:the\s+)?(?P<items>.+?)\s+if\s+missing",
            r"(?is)provide\s+(?:the\s+)?(?P<items>.+?)\s+if\s+missing",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                items = str(match.group("items") or "")
                for name in self._split_requested_input_names(items):
                    field_name = self._normalize_parameter_name(name)
                    if not field_name or field_name in seen:
                        continue
                    seen.add(field_name)
                    params.append({
                        "name": field_name,
                        "label": " ".join(part.capitalize() for part in field_name.split("_")),
                        "description": "Runtime value requested by the task instruction.",
                        "type": "string",
                        "input_type": "text",
                        "required": True,
                        "runtime_required": True,
                        "blocking": True,
                        "execution_required": True,
                        "source": "task_instruction",
                        "input_role": "query" if field_name in {"question", "query", "request"} else "runtime_input",
                        "values": [],
                    })
        return {
            "contract_type": "generated_intermediate_step_contract",
            "parameters": params,
            "missing_information": [dict(p) for p in params],
            "runtime_scope": "task_run",
        }

    def _split_requested_input_names(self, text: str) -> list[str]:
        cleaned = re.sub(r"(?is)\bonly\b.*$", "", str(text or ""))
        cleaned = re.sub(r"(?is)\s+if\s+missing.*$", "", cleaned)
        cleaned = cleaned.strip(" .,:;()[]{}\n\t")
        if not cleaned:
            return []
        parts = re.split(r"\s*(?:,|/|\band\b|\bor\b|、|，)\s*", cleaned, flags=re.I)
        return [p.strip(" .,:;()[]{}\n\t") for p in parts if p.strip(" .,:;()[]{}\n\t")]

    def _normalize_parameter_name(self, name: str) -> str:
        text = str(name or "").strip().lower()
        text = re.sub(r"^(?:the|a|an)\s+", "", text)
        text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
        return text[:80]

    def _capability_profile_from_fragment(self, fragment: str, parameter_contract: dict[str, Any]) -> dict[str, Any]:
        """Return a platform capability hint when the instruction names one.

        The returned value is a generic runtime capability profile. It is not a
        business/domain rule and does not select any participant by name.
        """
        text = str(fragment or "").casefold()
        params = parameter_contract.get("parameters") if isinstance(parameter_contract, dict) else []
        query_name = ""
        if isinstance(params, list):
            for item in params:
                if isinstance(item, dict) and str(item.get("input_role") or "") == "query":
                    query_name = str(item.get("name") or "")
                    break
        if "knowledge base" in text or "knowledge_base" in text or "local knowledge" in text:
            return {
                "capability_type": "local_knowledge_retrieval",
                "query_parameter": query_name or "query",
                "requires_user_query": True,
                "produces_verified_material": True,
            }
        # Modality-level capability hints are generic runtime signals. They do
        # not select a business domain or a concrete provider.
        if re.search(r"\b(generate|create|render|produce|make)\b.*\b(image|picture|visual|illustration|graphic)\b", text):
            return {
                "capability_type": "image_generation",
                "prompt_parameter": "prompt",
                "produces_verified_material": True,
                "output_modality": "image",
            }
        if "generate a file" in text:
            return {
                "capability_type": "file_generation",
                "requires_verified_material": True,
                "produces_verified_material": True,
            }
        return {}

    def _input_contract(self, depends_on: list[str]) -> dict[str, Any]:
        deps = [str(x) for x in depends_on or [] if str(x)]
        return {
            "contract_type": "runtime_step_input_contract",
            "bound_from_upstream": deps,
            "accepts_verified_material": bool(deps),
            "user_input_required_for_bound_material": False,
        }

    def _output_contract(self) -> dict[str, Any]:
        return {
            "contract_type": "runtime_step_output_contract",
            "produces_verified_material": True,
            "planner_metadata_is_not_result_material": True,
        }

    def _numbered_step_fragments(self, text: str) -> list[dict[str, str]]:
        """Extract explicitly numbered instruction fragments.

        This is structure parsing, not capability routing. It only recognizes
        generic step labels and preserves the user's fragments for the runtime
        semantic layer. If no numbered structure is present, callers use the
        existing configured splitter.
        """
        source = str(text or "").strip()
        if not source:
            return []
        # Match explicit user step headers in both multiline and pasted single-line instructions.
        # The look-behind boundary prevents matching template references like
        # {{Step1.final_answer}}, while still accepting "... enabled: true Step 1:".
        pattern = re.compile(r"(?is)(?<![\w{])(?:^|[\r\n]+|[.;。]|\s{2,}|\s+)(step\s*\d+|\d+)\s*[:：.)-]\s*")
        matches = list(pattern.finditer(source))
        if len(matches) < 2:
            # Fallback for common single-line pasted task text where each
            # header is separated only by one space. Require the literal
            # word "step" to avoid splitting ordinary numbered prose.
            pattern = re.compile(r"(?is)(?<![\w{])(step\s*\d+)\s*[:：.)-]\s*")
            matches = list(pattern.finditer(source))
        if len(matches) < 1:
            return []
        items: list[dict[str, str]] = []
        for index, match in enumerate(matches):
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(source)
            fragment = source[start:end].strip(" \t\r\n,.;。")
            if not fragment:
                continue
            raw_id = " ".join(match.group(1).split()).casefold()
            number_match = re.search(r"\d+", raw_id)
            canonical = f"step_{number_match.group(0)}" if number_match else raw_id.replace(" ", "_")
            items.append({"id": canonical, "fragment": fragment})
        return items

    def _declared_step_dependencies(self, fragment: str, step_aliases: dict[str, str]) -> list[str]:
        """Resolve explicit references to earlier numbered steps.

        The method never infers business semantics. It only maps references to
        already-known step aliases, so a downstream fragment can consume a prior
        step's material without making the upstream participant depend on it.
        """
        text = str(fragment or "")
        if not text or not step_aliases:
            return []
        deps: list[str] = []
        seen: set[str] = set()
        for match in re.finditer(r"(?i)\bstep\s*(\d+)\b", text):
            key = f"step_{match.group(1)}"
            dep = step_aliases.get(key) or step_aliases.get(key.casefold())
            if dep and dep not in seen:
                deps.append(dep)
                seen.add(dep)
        return deps

    def _load_config(self) -> dict[str, Any]:
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    merged = dict(self.DEFAULT_CONFIG)
                    merged.update(data)
                    return merged
            except Exception:
                pass
        return dict(self.DEFAULT_CONFIG)

    def _strip_wrappers(self, text: str) -> str:
        out = text.strip()
        for pattern in self.config.get("wrapper_patterns") or []:
            try:
                out = re.sub(str(pattern), "", out, flags=re.I)
            except re.error:
                continue
        return out.strip()

    def _split_fragments(self, text: str) -> list[str]:
        normalized = f" {text.strip()} "
        markers = sorted([str(m) for m in self.config.get("split_markers") or [] if str(m)], key=len, reverse=True)
        for idx, marker in enumerate(markers):
            normalized = normalized.replace(marker, f" ||__STEP_{idx}__|| ")
        parts = [p.strip(" ,.;。\n\t") for p in normalized.split("||")]
        return [p for p in parts if p and not p.startswith("__STEP_")]

    def _referenced_participants(self, fragment: str, participants: list[dict[str, Any]]) -> list[dict[str, Any]]:
        haystack = fragment.casefold()
        matched: list[dict[str, Any]] = []
        for participant in sorted([p for p in participants if isinstance(p, dict)], key=lambda p: len(self._participant_name(p)), reverse=True):
            aliases = [self._participant_name(participant), self._participant_id(participant)]
            for alias in aliases:
                alias_text = str(alias or "").strip()
                if len(alias_text) < 3:
                    continue
                pattern = r"(?<![\w-])" + re.escape(alias_text.casefold()) + r"(?![\w-])"
                if re.search(pattern, haystack, flags=re.UNICODE):
                    matched.append(participant)
                    break
        return self._dedupe(matched)

    def _should_keep_generated_fragment(self, fragment: str, refs: list[dict[str, Any]], added_participant: bool) -> bool:
        compact = " ".join(fragment.split())
        minimum = int(self.config.get("minimum_generated_fragment_chars") or 8)
        if len(compact) < minimum:
            return False
        reference_text = " ".join(self._participant_name(p) for p in refs)
        residual = compact.casefold()
        for participant in refs:
            for alias in (self._participant_name(participant), self._participant_id(participant)):
                if alias:
                    residual = residual.replace(alias.casefold(), "")
        residual_words = re.sub(r"[^\w\s]+", " ", residual, flags=re.UNICODE)
        residual_words = " ".join(residual_words.split())
        for pattern in self.config.get("participant_selection_residual_patterns") or []:
            try:
                if re.fullmatch(str(pattern), residual_words, flags=re.I):
                    return False
            except re.error:
                continue
        residual = re.sub(r"[\W_]+", "", residual, flags=re.UNICODE)
        # If a fragment only names participants, it is not a generated step. If
        # there is meaningful residual text, it is a user-declared operation or
        # modifier and must not be silently discarded.
        return bool(residual) and (not added_participant or len(residual) >= minimum)


    def _compact_fragment_label(self, fragment: str) -> str:
        text = " ".join(str(fragment or "").strip().split())
        if not text:
            return "Runtime Step"
        words = text.split(" ")
        if len(words) > 6:
            text = " ".join(words[:6]) + " …"
        return text[:72]

    def _remove_redundant_generated_steps(self, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seen_generated: set[tuple[str, tuple[str, ...]]] = set()
        for step in steps:
            route = step.get("route") if isinstance(step.get("route"), dict) else {}
            if route.get("requires_generated_step"):
                key = (str(step.get("objective") or "").casefold(), tuple(str(x) for x in step.get("depends_on") or []))
                if key in seen_generated:
                    continue
                seen_generated.add(key)
            out.append(step)
        return out

    def _dedupe(self, participants: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for participant in participants:
            key = self._participant_id(participant) or self._participant_name(participant).casefold()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(participant)
        return out

    def _participant_id(self, participant: dict[str, Any]) -> str:
        return str(participant.get("participant_id") or participant.get("id") or participant.get("name") or "").strip()

    def _participant_name(self, participant: dict[str, Any]) -> str:
        return str(participant.get("display_name") or participant.get("agent_name") or participant.get("name") or participant.get("participant_id") or participant.get("id") or "").strip()
