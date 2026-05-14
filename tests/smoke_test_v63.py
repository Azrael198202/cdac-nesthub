from ai_core.runtime.trace_writer import TraceWriter
from ai_core.execution.candidate_strategy_scorer import CandidateStrategyScorer
from ai_core.tools.generic_tool_runner import GenericToolRunner


def test_trace_writer_handles_circular(tmp_path, monkeypatch):
    import ai_core.runtime.trace_writer as tw
    monkeypatch.setattr(tw, 'RUNTIME_TRACES', tmp_path)
    obj = {'a': 1}
    obj['self'] = obj
    TraceWriter().write('run1', obj)
    assert list(tmp_path.glob('**/run1.jsonl'))


def test_scorer_scores_candidates_without_domain_logic():
    scorer = CandidateStrategyScorer()
    result = scorer.score_candidates([
        {'name': 'Example', 'url': 'not-a-url'},
    ])
    assert result and 'tool_type' in result[0]


def test_output_schema_validates_data_payload():
    # Private helper path: validate direct schema against wrapped data payload.
    runner = GenericToolRunner()
    output_schema = {'type': 'object', 'properties': {'x': {'type': 'number'}}, 'required': ['x']}
    wrapped = {'status': 'success', 'data': {'x': 1}, 'source': 'test'}
    direct = runner.schema_validator.validate_output(output_schema, wrapped)
    data = runner.schema_validator.validate_output(output_schema, wrapped['data'])
    assert not direct['valid']
    assert data['valid']
