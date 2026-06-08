from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ai_core.llm.provider_router import ProviderRouter


class RuntimeSemanticPlanner:
    """Runtime semantic decomposition facade.

    Source code stays vocabulary-free: no operation dictionaries, no domain
    terms, and no language-specific marker lists.  A model/provider converts the
    raw instruction into a normalized graph.  If no provider is available, the
    caller receives an empty plan and the workflow planner falls back to safe
    structural participant mapping.
    """

    def __init__(self) -> None:
        self.router = ProviderRouter()

    def build_plan(self, *, instruction: str, participants: list[dict[str, Any]], run_id: str) -> dict[str, Any]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._build_plan_async(instruction=instruction, participants=participants, run_id=run_id))
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(lambda: asyncio.run(self._build_plan_async(instruction=instruction, participants=participants, run_id=run_id)))
        try:
            return future.result(timeout=150)
        except TimeoutError:
            future.cancel()
            return {"steps": [], "coverage_notes": ["semantic_provider_timeout"]}
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    async def _build_plan_async(self, *, instruction: str, participants: list[dict[str, Any]], run_id: str) -> dict[str, Any]:
        participant_refs = []
        for item in participants:
            if not isinstance(item, dict):
                continue
            participant_refs.append({
                "participant_id": item.get("participant_id") or item.get("id") or item.get("name"),
                "display_name": item.get("display_name") or item.get("agent_name") or item.get("name"),
            })
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": True,
                        "properties": {
                            "id": {"type": "string"},
                            "label": {"type": "string"},
                            "objective": {"type": "string"},
                            "instruction_fragment": {"type": "string"},
                            "executable": {"type": "boolean"},
                            "depends_on": {"type": "array", "items": {"type": "string"}},
                            "route": {
                                "type": "object",
                                "additionalProperties": True,
                                "properties": {
                                    "participant_id": {"type": "string"},
                                    "participant_name": {"type": "string"},
                                    "requires_generated_step": {"type": "boolean"},
                                },
                            },
                        },
                        "required": ["id", "objective", "depends_on", "route"],
                    },
                },
                "coverage_notes": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["steps"],
        }
        prompt = {
            "system": (
                "Return only JSON. Decompose the user instruction into the work graph that should run after the task exists. "
                "Represent every requested executable action, modifier, post-process, and dependency as a step. "
                "Do not create executable steps for the command wrapper that only names, registers, or initializes the task itself. "
                "If a parsed fragment is only task-management metadata, include it only when needed with executable=false. "
                "Use a participant route only when the step should be executed by one of the declared participants. "
                "For any executable step not owned by a declared participant, set route.requires_generated_step=true. "
                "Do not omit independent parallel steps or dependent follow-up steps."
            )
        }
        rendered = {
            "instruction": instruction,
            "declared_participants": participant_refs,
            "output_contract": schema,
        }
        try:
            result = await self.router.generate_json(
                run_id=run_id,
                node_id="semantic_task_graph_planning",
                adapter={"provider_timeout_seconds": 90, "max_provider_attempts": 1, "provider_options": {"temperature": 0}},
                prompt=prompt,
                rendered_user_prompt=str(rendered),
                schema=schema,
            )
            if isinstance(result, dict) and isinstance(result.get("steps"), list):
                return result
            if isinstance(result, dict) and isinstance(result.get("data"), dict):
                data = result.get("data")
                if isinstance(data.get("steps"), list):
                    return data
        except Exception:
            return {"steps": [], "coverage_notes": ["semantic_provider_unavailable"]}
        return {"steps": [], "coverage_notes": ["semantic_provider_returned_no_graph"]}
