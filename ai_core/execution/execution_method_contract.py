from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class ExecutionMethodContract:
    """Runtime execution method contract.

    The contract is generic and task-neutral.  It describes how a step should be
    executed, what the runtime expects as input/output, and how fallback should
    behave.  LLMs may propose methods, but this contract is the deterministic
    decision surface used by the runtime.
    """

    method: str
    confidence: float = 0.5
    cost_level: str = "unknown"
    latency_level: str = "unknown"
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    fallback: list[str] | None = None
    reason: str = ""
    proposal_source: str = "runtime"
    decision_source: str = "runtime_policy"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["input_schema"] = data.get("input_schema") or {}
        data["output_schema"] = data.get("output_schema") or {}
        data["fallback"] = data.get("fallback") or []
        return data


class ExecutionMethodProposalEngine:
    """Builds generic execution method proposals.

    This class is deliberately not a final router.  It only produces candidate
    methods from model/workflow hints and structural runtime signals.  The
    resolver below makes the final decision with policies and contracts.
    """

    ALLOWED_METHODS = {
        "runtime_generated_tool",
        "existing_tool",
        "web_search",
        "knowledge_base",
        "model_knowledge",
        "content_generation",
        "api_call",
    }

    STRATEGY_METHOD_MAP = {
        "web_evidence": "web_search",
        "web_retrieval": "web_search",
        "external_evidence": "web_search",
        "local_knowledge": "knowledge_base",
        "knowledge_base": "knowledge_base",
        "tool_generation": "runtime_generated_tool",
        "runtime_generated_tool": "runtime_generated_tool",
        "existing_tool": "existing_tool",
        "api_call": "api_call",
        "structured_provider": "api_call",
        "model_knowledge": "model_knowledge",
        "model_generation": "content_generation",
        "content_generation": "content_generation",
        "generate_content": "content_generation",
    }

    MODE_METHOD_MAP = {
        "runtime_native": "runtime_generated_tool",
        "structured_provider": "api_call",
        "web_retrieval": "web_search",
        "local_knowledge": "knowledge_base",
    }

    def propose(
        self,
        *,
        step: dict[str, Any],
        plan: dict[str, Any],
        state: dict[str, Any],
        selected_mode: str,
        has_existing_tool: bool,
        classifier_category: str = "",
    ) -> list[dict[str, Any]]:
        proposals: list[dict[str, Any]] = []

        def add(method: str, confidence: float, source: str, reason: str) -> None:
            method = str(method or "").strip()
            if method not in self.ALLOWED_METHODS:
                return
            proposals.append({
                "method": method,
                "confidence": round(float(confidence), 3),
                "source": source,
                "reason": reason,
            })

        explicit = self._explicit_proposals(step, plan, state)
        for item in explicit:
            add(item.get("method", ""), item.get("confidence", 0.7), "model_or_workflow_proposal", item.get("reason", "explicit proposal"))

        for strategy in self._strategy_values(step):
            method = self.STRATEGY_METHOD_MAP.get(strategy)
            if method:
                add(method, 0.66, "workflow_strategy", "method inferred from workflow execution strategy")

        if selected_mode in self.MODE_METHOD_MAP:
            add(self.MODE_METHOD_MAP[selected_mode], 0.82, "runtime_mode_selector", "method inferred from selected execution mode")

        if has_existing_tool:
            add("existing_tool", 0.9, "tool_registry", "matching executable tool is registered")

        if classifier_category:
            lowered = classifier_category.casefold()
            if "runtime" in lowered or "local" in lowered:
                add("runtime_generated_tool", 0.88, "semantic_classifier", "semantic category prefers local runtime observation")
            elif "external" in lowered or "remote" in lowered:
                add("api_call", 0.74, "semantic_classifier", "semantic category prefers external structured access")

        if not proposals:
            add("content_generation", 0.45, "runtime_default", "no stronger executable method was proposed")
        return self._dedupe(proposals)

    def _explicit_proposals(self, *items: Any) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            for key in ("execution_method_proposal", "method_proposal", "execution_method"):
                value = item.get(key)
                if isinstance(value, str):
                    found.append({"method": value, "confidence": 0.72, "reason": key})
                elif isinstance(value, dict):
                    found.append(value)
            steps = item.get("planned_steps")
            if isinstance(steps, list):
                for step in steps:
                    found.extend(self._explicit_proposals(step))
        return found

    def _strategy_values(self, item: dict[str, Any]) -> list[str]:
        strategy = item.get("execution_strategy") if isinstance(item, dict) else None
        if not isinstance(strategy, list):
            return []
        return [str(x).strip() for x in strategy if str(x).strip()]

    def _dedupe(self, proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        best: dict[str, dict[str, Any]] = {}
        for item in proposals:
            method = str(item.get("method") or "")
            if not method:
                continue
            if method not in best or float(item.get("confidence") or 0) > float(best[method].get("confidence") or 0):
                best[method] = item
        return sorted(best.values(), key=lambda x: float(x.get("confidence") or 0), reverse=True)


class ExecutionMethodResolver:
    """Deterministically resolves a method from proposals and runtime policy."""

    DEFAULT_FALLBACKS = {
        "runtime_generated_tool": ["existing_tool", "api_call", "web_search"],
        "existing_tool": ["runtime_generated_tool", "api_call", "web_search"],
        "api_call": ["web_search", "runtime_generated_tool"],
        "web_search": ["api_call", "knowledge_base"],
        "knowledge_base": ["web_search", "model_knowledge"],
        "model_knowledge": ["knowledge_base"],
        "content_generation": ["model_knowledge"],
    }

    def resolve(
        self,
        *,
        proposals: list[dict[str, Any]],
        step: dict[str, Any],
        policy: dict[str, Any] | None = None,
    ) -> ExecutionMethodContract:
        policy = policy if isinstance(policy, dict) else {}
        step_policy = step.get("execution_method_policy") if isinstance(step.get("execution_method_policy"), dict) else {}
        policy = self._merge_policy(policy, step_policy)
        disabled = {str(x) for x in policy.get("disabled_methods", []) if str(x).strip()}
        preferred = [str(x) for x in policy.get("preferred_methods", []) if str(x).strip()]
        candidates = [p for p in proposals if str(p.get("method") or "") not in disabled]

        # Strong runtime hints can override weaker workflow proposals.  This is
        # the point where the system manages the model, rather than allowing a
        # model proposal to directly choose execution.
        if preferred:
            candidates.sort(key=lambda p: (preferred.index(p["method"]) if p.get("method") in preferred else 999, -float(p.get("confidence") or 0)))
        else:
            candidates.sort(key=lambda p: float(p.get("confidence") or 0), reverse=True)

        chosen = candidates[0] if candidates else {"method": "content_generation", "confidence": 0.4, "source": "runtime_default", "reason": "no candidate"}
        method = str(chosen.get("method") or "content_generation")
        fallback_allowed = bool(policy.get("fallback_allowed", True))
        fallback = [m for m in self.DEFAULT_FALLBACKS.get(method, []) if m not in disabled] if fallback_allowed else []
        return ExecutionMethodContract(
            method=method,
            confidence=float(chosen.get("confidence") or 0.5),
            cost_level=self._cost(method),
            latency_level=self._latency(method),
            input_schema=self._input_schema(step),
            output_schema=self._output_schema(),
            fallback=fallback,
            reason=str(chosen.get("reason") or ""),
            proposal_source=str(chosen.get("source") or "runtime"),
        )


    def _merge_policy(self, base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        merged = dict(base or {})
        for key, value in (override or {}).items():
            if isinstance(value, list):
                merged[key] = list(value)
            elif isinstance(value, dict) and isinstance(merged.get(key), dict):
                nested = dict(merged[key])
                nested.update(value)
                merged[key] = nested
            else:
                merged[key] = value
        return merged

    def _input_schema(self, step: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "object",
            "required": [],
            "properties": {
                "known": {"type": "object"},
                "parameters": {"type": "object"},
                "objective": {"type": "string"},
            },
            "source_step_id": step.get("step_id") or step.get("task_id"),
        }

    def _output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "data": {"type": "object"},
                "normalized_facts": {"type": "array"},
                "answer_material": {"type": "string"},
            },
        }

    def _cost(self, method: str) -> str:
        if method in {"runtime_generated_tool", "existing_tool", "knowledge_base", "model_knowledge", "content_generation"}:
            return "low"
        if method == "web_search":
            return "medium"
        return "variable"

    def _latency(self, method: str) -> str:
        if method in {"runtime_generated_tool", "existing_tool", "model_knowledge", "content_generation"}:
            return "low"
        if method == "knowledge_base":
            return "low_to_medium"
        return "medium_to_high"
