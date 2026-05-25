from ai_core.executors.tool_call_executor import ToolCallExecutor


def test_runtime_generated_source_detects_external_imports_without_replacing_source():
    source = "import pytz\nfrom datetime import datetime\nprint(datetime.now())"
    detected = ToolCallExecutor._source_external_imports(source)
    assert detected == ["pytz"]
    assert "import pytz" in source


def test_runtime_generated_source_ignores_standard_library_imports():
    source = "from datetime import datetime, timezone\nprint(datetime.now(timezone.utc).isoformat())"
    assert ToolCallExecutor._source_external_imports(source) == []


def test_missing_module_name_can_be_extracted_from_interpreter_error():
    stderr = "ModuleNotFoundError: No module named 'example_package'"
    assert ToolCallExecutor._missing_module_from_stderr(stderr) == "example_package"
