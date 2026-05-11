import uuid
from typing import Dict, Any
from ai_core.config.paths import RUNTIME_CONFIGS
from ai_core.config.loader import ConfigLoader
from ai_core.events.event_bus import event_bus
from ai_core.runtime.bootstrap import RuntimeBootstrap
from ai_core.runtime.checkpoint_store import CheckpointStore
from ai_core.runtime.trace_writer import TraceWriter
from ai_core.environment.provider_manager import ProviderManager
from ai_core.llm.llm_client import LLMClient
from ai_core.memory.memory_manager import MemoryManager
from ai_core.knowledge.knowledge_service import KnowledgeService
from ai_core.evolution.finetune_dataset_builder import FinetuneDatasetBuilder


class WorkflowRuntime:
    def __init__(self) -> None:
        self.bootstrap = RuntimeBootstrap()
        self.loader = ConfigLoader()
        self.checkpoints = CheckpointStore()
        self.trace = TraceWriter()
        self.provider_manager = ProviderManager()
        self.llm = LLMClient()
        self.memory = MemoryManager()
        self.knowledge = KnowledgeService()
        self.dataset = FinetuneDatasetBuilder()

    def _load_workflow(self) -> Dict[str, Any]:
        p = RUNTIME_CONFIGS / "workflows" / "base_orchestration.yaml"
        return self.loader.load_yaml(p)

    def _total_weight(self, workflow: dict) -> int:
        return sum(int(n.get("progress_weight", 1)) for n in workflow.get("nodes", [])) or 1

    def _progress_before(self, workflow: dict, node_index: int) -> int:
        nodes = workflow.get("nodes", [])
        total = self._total_weight(workflow)
        done = sum(int(n.get("progress_weight", 1)) for n in nodes[:node_index])
        return int(done / total * 100)

    async def start(self, message: str) -> str:
        self.bootstrap.ensure()
        run_id = uuid.uuid4().hex[:12]
        workflow = self._load_workflow()
        state = {
            "run_id": run_id,
            "input": message,
            "node_index": 0,
            "workflow": workflow,
            "results": {},
            "progress": 0
        }
        await self._emit(run_id, {
            "type": "RUN_STARTED",
            "title": "Run started",
            "message": "Starting configurable orchestration.",
            "progress": 0
        })
        await self._continue(state)
        return run_id

    async def resume(self, run_id: str, decision: str = "approve") -> None:
        state = self.checkpoints.load(run_id)
        if not state:
            await self._emit(run_id, {
                "type": "RUN_FAILED",
                "title": "Resume failed",
                "message": "Checkpoint not found."
            })
            return

        pending = state.get("pending_action") or {}
        self.checkpoints.delete(run_id)

        if decision != "approve":
            await self._emit(run_id, {
                "type": "RUN_CANCELLED",
                "title": "Rejected",
                "message": "Human rejected the pending action."
            })
            return

        await self._emit(run_id, {
            "type": "RESUMED",
            "title": "Run resumed",
            "message": f"Continuing from node index {state.get('node_index', 0)}.",
            "progress": state.get("progress", 0)
        })

        if pending.get("kind") == "provider_fix":
            ok = await self.provider_manager.run_provider_fix(
                run_id=run_id,
                provider_name=pending["provider"],
                commands=pending.get("commands", [])
            )
            if not ok:
                await self._emit(run_id, {
                    "type": "RUN_FAILED",
                    "title": "Provider repair failed",
                    "message": "Could not repair provider."
                })
                return

        await self._continue(state)

    async def _continue(self, state: Dict[str, Any]) -> None:
        workflow = state["workflow"]
        nodes = workflow["nodes"]
        run_id = state["run_id"]

        while state["node_index"] < len(nodes):
            node = nodes[state["node_index"]]
            node_id = node["id"]
            node_type = node.get("type", "generic")
            progress = self._progress_before(workflow, state["node_index"])
            state["progress"] = progress

            await self._emit(run_id, {
                "type": "NODE_STARTED",
                "title": node_id,
                "message": f"Executing node type: {node_type}",
                "node_id": node_id,
                "progress": progress
            })

            ok, provider_result = await self.provider_manager.ensure_any_provider_ready(run_id, node_id)
            if not ok:
                if provider_result.get("approval_required"):
                    state["pending_action"] = {
                        "kind": "provider_fix",
                        "provider": provider_result["provider"],
                        "commands": provider_result.get("commands", [])
                    }
                    self.checkpoints.save(run_id, state)
                    await self._emit(run_id, {
                        "type": "HUMAN_REVIEW",
                        "title": "Approval required",
                        "message": provider_result["message"],
                        "commands": provider_result.get("commands", []),
                        "run_id": run_id,
                        "progress": progress
                    })
                    return
                await self._emit(run_id, {
                    "type": "PROVIDER_UNAVAILABLE",
                    "title": "Provider unavailable",
                    "message": provider_result.get("message", "Provider not ready."),
                    "progress": progress
                })
                return

            payload = {
                "input": state.get("input"),
                "context": self.memory.build_context(state.get("input", "")),
                "knowledge_hits": self.knowledge.search(state.get("input", "")),
                "previous_results": state.get("results", {})
            }
            result = await self.llm.generate_json(provider_result, prompt=node_id, payload=payload)
            result.update({
                "node_id": node_id,
                "node_type": node_type,
                "status": "completed"
            })
            state["results"][node_id] = result

            node_done_progress = min(99, self._progress_before(workflow, state["node_index"] + 1))
            await self._emit(run_id, {
                "type": "NODE_RESULT",
                "title": f"{node_id} result",
                "message": "Node completed.",
                "result": result,
                "progress": node_done_progress
            })

            if node.get("review_required"):
                state["node_index"] += 1
                state["progress"] = node_done_progress
                state["pending_action"] = {"kind": "node_review", "node_id": node_id}
                self.checkpoints.save(run_id, state)
                await self._emit(run_id, {
                    "type": "HUMAN_REVIEW",
                    "title": "Human review required",
                    "message": f"Review result for node '{node_id}' before continuing.",
                    "run_id": run_id,
                    "progress": node_done_progress
                })
                return

            state["node_index"] += 1
            state["progress"] = node_done_progress

        self.knowledge.save_success_case(run_id, state.get("results", {}))
        self.dataset.append_case(
            input_text=state.get("input", ""),
            output_text="Workflow completed.",
            metadata={"run_id": run_id, "results": state.get("results", {})}
        )
        await self._emit(run_id, {
            "type": "RUN_COMPLETED",
            "title": "Final output",
            "message": "Workflow completed. Results were saved to runtime knowledge and finetune dataset.",
            "results": state.get("results", {}),
            "progress": 100
        })

    async def _emit(self, run_id: str, event: dict) -> None:
        self.trace.write(run_id, event)
        await event_bus.emit(run_id, event)
