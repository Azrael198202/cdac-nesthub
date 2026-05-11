import uuid
import yaml
from typing import Dict, Any, Optional
from ai_core.config.paths import RUNTIME_CONFIGS
from ai_core.events.event_bus import event_bus
from ai_core.runtime.bootstrap import RuntimeBootstrap
from ai_core.runtime.checkpoint_store import CheckpointStore
from ai_core.environment.provider_manager import ProviderManager


class WorkflowRuntime:
    def __init__(self) -> None:
        self.bootstrap = RuntimeBootstrap()
        self.checkpoints = CheckpointStore()
        self.provider_manager = ProviderManager()

    def _load_workflow(self) -> Dict[str, Any]:
        p = RUNTIME_CONFIGS / "workflows" / "base_orchestration.yaml"
        return yaml.safe_load(p.read_text(encoding="utf-8"))

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
        }
        await event_bus.emit(run_id, {
            "type": "RUN_STARTED",
            "title": "Run started",
            "message": "Starting configurable orchestration.",
            "run_id": run_id,
        })
        await self._continue(state)
        return run_id

    async def resume(self, run_id: str, decision: str = "approve") -> None:
        state = self.checkpoints.load(run_id)
        if not state:
            await event_bus.emit(run_id, {
                "type": "RUN_FAILED",
                "title": "Resume failed",
                "message": "Checkpoint not found.",
            })
            return

        pending = state.get("pending_action") or {}
        self.checkpoints.delete(run_id)

        if decision != "approve":
            await event_bus.emit(run_id, {
                "type": "RUN_FAILED",
                "title": "Rejected",
                "message": "Human rejected the pending action.",
            })
            return

        await event_bus.emit(run_id, {
            "type": "RESUMED",
            "title": "Run resumed",
            "message": f"Continuing from node index {state.get('node_index', 0)}.",
        })

        if pending.get("kind") == "provider_fix":
            ok = await self.provider_manager.run_provider_fix(
                run_id=run_id,
                provider_name=pending["provider"],
                commands=pending.get("commands", []),
            )
            if not ok:
                await event_bus.emit(run_id, {
                    "type": "RUN_FAILED",
                    "title": "Provider repair failed",
                    "message": "Could not repair provider.",
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
            await event_bus.emit(run_id, {
                "type": "NODE_STARTED",
                "title": node_id,
                "message": "Executing node.",
                "node_id": node_id,
            })

            ready, provider_result = await self.provider_manager.ensure_provider_ready(run_id, "ollama")
            if not ready:
                if provider_result.get("approval_required"):
                    state["pending_action"] = {
                        "kind": "provider_fix",
                        "provider": provider_result["provider"],
                        "commands": provider_result.get("commands", []),
                    }
                    self.checkpoints.save(run_id, state)
                    await event_bus.emit(run_id, {
                        "type": "HUMAN_REVIEW",
                        "title": "Approval required",
                        "message": provider_result["message"],
                        "commands": provider_result.get("commands", []),
                        "run_id": run_id,
                    })
                    return
                await event_bus.emit(run_id, {
                    "type": "PROVIDER_UNAVAILABLE",
                    "title": "Provider unavailable",
                    "message": provider_result.get("message", "Provider not ready."),
                })
                return

            # No local-rule fake result. If provider is not really available, execution pauses/fails.
            result = {
                "node_id": node_id,
                "status": "completed",
                "provider": provider_result.get("provider", "ollama"),
                "note": "Provider is ready. Node execution placeholder waits for configured prompt/tool implementation.",
            }
            state["results"][node_id] = result

            await event_bus.emit(run_id, {
                "type": "NODE_RESULT",
                "title": f"{node_id} result",
                "message": "Node completed.",
                "result": result,
            })

            if node.get("review_required"):
                state["node_index"] += 1
                state["pending_action"] = {"kind": "node_review", "node_id": node_id}
                self.checkpoints.save(run_id, state)
                await event_bus.emit(run_id, {
                    "type": "HUMAN_REVIEW",
                    "title": "Human review required",
                    "message": f"Review result for node '{node_id}' before continuing.",
                    "run_id": run_id,
                })
                return

            state["node_index"] += 1

        await event_bus.emit(run_id, {
            "type": "RUN_COMPLETED",
            "title": "Final output",
            "message": "Workflow completed. All approved nodes have been executed.",
            "results": state.get("results", {}),
        })
