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
        fragments = self._split_fragments(text)
        if not fragments:
            return []

        selected_ids: list[str] = []
        steps: list[dict[str, Any]] = []
        for fragment in fragments:
            refs = self._referenced_participants(fragment, participants)
            # A fragment may contain multiple existing participant references.
            # Each declared participant remains its own executable node so the
            # downstream graph can show parallel branches and bind outputs.
            added_participant = False
            for participant in refs:
                pid = self._participant_id(participant)
                if not pid or pid in selected_ids:
                    continue
                selected_ids.append(pid)
                steps.append({
                    "id": f"declared_step_{len(steps) + 1}",
                    "label": self._participant_name(participant),
                    "objective": fragment.strip() or self._participant_name(participant),
                    "instruction_fragment": fragment.strip(),
                    "executable": True,
                    "depends_on": [],
                    "route": {"participant_id": pid},
                })
                added_participant = True

            # If the fragment references already-selected upstream participants
            # but is not just a participant call fragment, keep it as a generated
            # dataflow step. Its objective remains runtime text, not source-code
            # knowledge about a specific operation.
            deps = [self._participant_id(p) for p in refs if self._participant_id(p) in selected_ids]
            if deps and self._should_keep_generated_fragment(fragment, refs, added_participant):
                steps.append({
                    "id": f"generated_step_{len(steps) + 1}",
                    "label": "Generated dataflow step",
                    "objective": fragment.strip(),
                    "instruction_fragment": fragment.strip(),
                    "executable": True,
                    "depends_on": deps,
                    "route": {"requires_generated_step": True},
                })

        return self._remove_redundant_generated_steps(steps)

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
            if any(alias and alias.casefold() in haystack for alias in aliases):
                matched.append(participant)
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
