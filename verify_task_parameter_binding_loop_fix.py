from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from ai_core.artifacts.uploaded_artifact_contract import UploadedArtifactContractBuilder
from auxiliary_brain.delegation.delegation_runtime import AgentDelegationRuntime
from ai_core.agent_delegation import AgentExecutionResult


def assert_uploaded_artifact_reads_agent_request_parameters() -> None:
    builder = UploadedArtifactContractBuilder()
    state = {
        "run_id": "verify_run",
        "input": "AGENT_REQUEST=" + json.dumps({
            "participant_name": "Any Agent",
            "context": {
                "agent_parameters": {
                    "values": {
                        "city_name": "Fukuoka",
                        "date_str": "2026-06-06",
                    }
                }
            },
        }),
    }
    known = builder._known_values(state=state, step={})
    assert known.get("city_name") == "Fukuoka", known
    assert known.get("date_str") == "2026-06-06", known


def assert_resume_does_not_restart_completed_participants() -> None:
    runtime = AgentDelegationRuntime()
    run_payload = {
        "run_id": "delegation_run_verify",
        "pending_action": {"kind": "agent_parameter_collection"},
        "agent_results": [{"participant_id": "p1", "participant_name": "upstream", "status": "completed"}],
    }
    # With existing participant results, this must not take the fresh-restart branch.
    # It should proceed toward durable resume bookkeeping and fail only because no
    # paused participant checkpoint exists in this synthetic payload.
    class Store:
        def write_json(self, *args, **kwargs):
            return "unused"
        def read_json(self, *args, **kwargs):
            return {}
        def list_json(self, *args, **kwargs):
            return []
    runtime.store = Store()
    result = asyncio.run(runtime.resume_task(run_payload, {"task_name": "t"}, [], provided_inputs={"x": "y"}))
    assert result.get("message") == "No paused participant checkpoint was found for durable resume.", result


def assert_registered_tool_hydrates_task_runtime_values() -> None:
    with tempfile.TemporaryDirectory() as d:
        runtime = AgentDelegationRuntime()
        class Store:
            def __init__(self, root): self.root = Path(root)
            def read_json(self, path):
                if path == "generated/tasks/T.json":
                    return {"runtime_parameters": {
                        "to": "user@example.com",
                        "subject": "Subject",
                        "body": "Body",
                        "participant_x.subject": "Subject",
                    }}
                return {}
            def write_json(self, *args, **kwargs): return "unused"
            def list_json(self, *args, **kwargs): return []
        runtime.store = Store(d)
        participant = {"participant_id": "participant_x", "display_name": "Tool Agent", "runtime_parameters": {}}
        runtime._ensure_task_runtime_parameters_for_participant(participant=participant, task_name="T")
        assert participant["runtime_parameters"].get("subject") == "Subject", participant
        assert participant["runtime_parameters"].get("participant_x.subject") == "Subject", participant


if __name__ == "__main__":
    assert_uploaded_artifact_reads_agent_request_parameters()
    assert_resume_does_not_restart_completed_participants()
    assert_registered_tool_hydrates_task_runtime_values()
    print("task parameter binding loop fix verification passed")
