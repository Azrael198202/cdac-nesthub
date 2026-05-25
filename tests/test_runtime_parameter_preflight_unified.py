from pathlib import Path


def test_runtime_parameter_preflight_runs_before_reuse_and_uses_unified_pending_action():
    source = Path('auxiliary_brain/studio/service.py').read_text(encoding='utf-8')
    execute_start = source.index('async def execute_task')
    execute_body = source[execute_start:source.index('async def resume_run', execute_start)]
    assert execute_body.index('_preflight_runtime_parameters') < execute_body.index('_try_reused_task_execution')
    assert 'studio_pre_execution_runtime_parameters' in source
    assert 'Runtime parameter values are required before task execution.' in source


def test_runtime_parameter_preflight_aggregates_artifact_fields_and_leaves_agent_fields_to_node_runtime():
    source = Path('auxiliary_brain/studio/service.py').read_text(encoding='utf-8')
    helper_start = source.index('def _preflight_runtime_parameters')
    helper_body = source[helper_start:source.index('def _preflight_uploaded_artifact_parameters', helper_start)]
    assert '_preflight_uploaded_artifact_parameters' in helper_body
    assert '_collect_missing_agent_parameter_fields' not in helper_body
    assert '_runtime_field_key' in helper_body
