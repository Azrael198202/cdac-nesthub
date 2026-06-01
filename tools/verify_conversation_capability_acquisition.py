from __future__ import annotations

import asyncio
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_core.interaction.conversation_core_runtime import ConversationCoreRuntime

REQUEST = """Acquire runtime capability:

Basic SMTP mail sender.

Use runtime autonomous acquisition mode.

Constraints:
- Runtime language: Python
- Complexity level: basic
- Use Python standard library if possible
- Prefer smtplib and email.message
- Do not require external package installation
- Do not block on protocol or library selection
- Generate input schema
- Generate connection schema
- Generate secret schema
- Generate approval policy
- Store connection values through Agent Studio UI
- Store secret values in local runtime secret store
- Verify by running a dry-run or mock SMTP test
- Register the capability after sandbox validation

The capability acquisition is complete only after:
1. implementation generated
2. sandbox test passed
3. registry updated
4. verification run completed
"""


async def _run() -> dict:
    return await ConversationCoreRuntime().run(REQUEST)


def main() -> None:
    cleanup_runtime_capability_outputs(ROOT, "basic_smtp_mail_sender")
    try:
        result = asyncio.run(_run())
        execution = result.get("workflow_results", {}).get("execution", {})
        runtime_impl = execution.get("capability_implementation", {}).get("runtime_implementation", {})
        assert runtime_impl.get("status") == "implemented_tested_registered", runtime_impl
        stages = [(item.get("stage"), item.get("status")) for item in runtime_impl.get("pipeline", [])]
        required = [
            ("TemplateResolver", "template_not_found"),
            ("LLMCapabilityPlanner", "planned"),
            ("ArtifactGenerator", "completed"),
            ("SandboxValidator", "completed"),
            ("VerificationRun", "completed"),
            ("RegistryWriter", "completed"),
        ]
        for item in required:
            assert item in stages, stages
        tool_registry = json.loads((ROOT / "runtime/registry/tool_registry.json").read_text(encoding="utf-8") or "{}")
        record = tool_registry.get("basic_smtp_mail_sender")
        assert isinstance(record, dict), tool_registry
        assert record.get("connection_schema"), record
        assert record.get("secret_schema"), record
        assert record.get("approval_policy"), record
        print("Conversation capability acquisition e2e verification passed")
    finally:
        cleanup_runtime_capability_outputs(ROOT, "basic_smtp_mail_sender")


def cleanup_runtime_capability_outputs(root: Path, tool_id: str) -> None:
    for rel in [
        f"runtime/generated/tools/{tool_id}",
        f"runtime/generated/tests/{tool_id}",
        "runtime/generated/capability_templates/runtime_planned_capability_templates.json",
    ]:
        path = root / rel
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink()
    for rel in ["runtime/registry/tool_registry.json", "runtime/registry/module_registry.json"]:
        path = root / rel
        data = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8") or "{}")
            except Exception:
                data = {}
        if isinstance(data, dict):
            data.pop(tool_id, None)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
