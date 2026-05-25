from pathlib import Path


def test_artifact_upload_json_endpoint_exists_and_frontend_fallback_present():
    server = Path('apps/api/server.py').read_text(encoding='utf-8')
    html = Path('apps/web/agent_studio.html').read_text(encoding='utf-8')
    assert '/api/agent-studio/artifacts-json' in server
    assert 'ArtifactUploadJsonRequest' in server
    assert 'base64.b64decode' in server
    assert "uploadArtifactsAsJson(files)" in html
    assert 'multipart upload unavailable; retrying with JSON fallback' in html
    assert 'parseUploadError' in html
