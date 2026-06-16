from pathlib import Path


def test_agent_studio_message_defaults_to_isolated_worker() -> None:
    source = Path('apps/api/server.py').read_text(encoding='utf-8')
    assert 'def _agent_studio_message_should_run_isolated' in source
    assert 'return True' in source
    assert 'async_requested = _agent_studio_message_should_run_isolated(req)' in source
    assert 'asyncio.to_thread(self._run_runner_in_private_loop, runner)' in Path('ai_core/runtime/async_jobs.py').read_text(encoding='utf-8')


def test_agent_studio_operation_uses_fresh_service_instance() -> None:
    source = Path('apps/api/server.py').read_text(encoding='utf-8')
    assert 'operation_studio_service = AgentStudioService()' in source
    assert 'payload = await operation_studio_service.handle_message(' in source
    assert 'payload = await studio_service.handle_message(' not in source
