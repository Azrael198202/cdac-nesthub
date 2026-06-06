from pathlib import Path
import importlib.util
import json
import os
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def test_console_ui_terminal_format():
    html = (ROOT / "apps" / "web" / "runtime_console.html").read_text(encoding="utf-8")
    assert "terminal format" in html
    assert "renderTerminal" in html
    assert "level-err" in html
    assert "Runtime Console" in html


def test_runtime_console_alias_route():
    server = (ROOT / "apps" / "api" / "server.py").read_text(encoding="utf-8")
    assert '@app.get("/runtime-console")' in server
    assert '@app.get("/runtime_console")' in server


def test_planner_reads_agent_studio_model_selection():
    cfg_dir = ROOT / "configs"
    cfg_dir.mkdir(exist_ok=True)
    path = cfg_dir / "model_selection.json"
    original = path.read_text(encoding="utf-8") if path.exists() else None
    try:
        path.write_text(json.dumps({
            "mode": "local_only",
            "selected_local_model_id": "test-local-model-from-ui",
            "initial_model_id": "fallback-model",
        }), encoding="utf-8")
        planner_path = ROOT / "runtime_assets" / "seeds" / "capability_planners" / "default_capability_planner.py"
        spec = importlib.util.spec_from_file_location("default_capability_planner_test", planner_path)
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        old = os.environ.pop("AI_CORE_CAPABILITY_PLANNER_MODEL", None)
        old2 = os.environ.pop("OLLAMA_MODEL", None)
        try:
            model, source = mod._resolve_planner_model()
        finally:
            if old is not None:
                os.environ["AI_CORE_CAPABILITY_PLANNER_MODEL"] = old
            if old2 is not None:
                os.environ["OLLAMA_MODEL"] = old2
        assert model == "test-local-model-from-ui", (model, source)
        assert source == "configs/model_selection.json", (model, source)
    finally:
        if original is None:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        else:
            path.write_text(original, encoding="utf-8")


if __name__ == "__main__":
    test_console_ui_terminal_format()
    test_runtime_console_alias_route()
    test_planner_reads_agent_studio_model_selection()
    print("OK")
