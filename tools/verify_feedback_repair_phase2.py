from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_core.runtime.self_repair.repair_orchestrator import FeedbackRepairOrchestrator
from ai_core.runtime.self_repair.execution_failure_repair import ExecutionFailureRepairClassifier


def main() -> None:
    trace_dir = Path('runtime/traces/feedback_repair')
    if trace_dir.exists():
        shutil.rmtree(trace_dir)
    orch = FeedbackRepairOrchestrator()
    result = {
        'status': 'error',
        'error': {'code': 'tool_input_schema_validation_failed', 'message': 'required value is missing'},
    }
    proposal = orch.propose_for_tool_result(
        run_id='verify_feedback_repair_phase2',
        tool_id='generic_runtime_tool',
        profile_id='default',
        result=result,
        tool_spec={'tool_id': 'generic_runtime_tool', 'implementation': {'type': 'runtime_python'}},
        input_payload={},
        expected_contract={'input_schema': {'type': 'object', 'properties': {'target': {'type': 'string'}}, 'required': ['target']}},
        runtime_state={},
    )
    assert proposal['requires_user_confirmation'] is True
    assert proposal['diagnosis']['category'] == 'parameter_problem'
    apply = orch.apply(repair_id=proposal['repair_id'], approved=False)
    assert apply['status'] == 'repair_declined'
    trace = trace_dir / 'verify_feedback_repair_phase2.jsonl'
    assert trace.exists(), trace
    events = [json.loads(line) for line in trace.read_text(encoding='utf-8').splitlines() if line.strip()]
    stages = {e['stage'] for e in events}
    assert {'failure_received', 'failure_classified', 'repair_proposal_created', 'repair_confirmation'} <= stages

    secret = ExecutionFailureRepairClassifier().classify(
        result={'status': 'error', 'error': {'code': 'tool_execution_failed', 'message': 'authentication credential not accepted'}},
        tool_spec={},
    )
    assert secret.category == 'secret_problem'
    impl = ExecutionFailureRepairClassifier().classify(
        result={'status': 'error', 'error': {'code': 'tool_output_schema_validation_failed', 'message': 'additional property'}},
        tool_spec={'implementation': {'type': 'runtime_python'}},
    )
    assert impl.category in {'tool_implementation_problem', 'parameter_problem'}
    print('feedback repair phase2 verification passed')


if __name__ == '__main__':
    main()
