from pathlib import Path


def test_missing_input_hint_deduplicates_message_and_description():
    html = Path('apps/web/agent_studio.html').read_text(encoding='utf-8')
    assert 'normalizedDescription !== normalizedMessage' in html
    assert "f.question||f.prompt||f.message||f.label" in html
    assert "f.question||f.prompt||f.message||f.description||f.label" not in html
