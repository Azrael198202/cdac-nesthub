from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from runtime_assets.service_lifecycle import DynamicGeneratedServiceLoader


def test_loader_loads_service_created_after_runtime_start() -> None:
    async def main() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            services_dir = root / "runtime" / "generated" / "services"
            trace_dir = root / "runtime" / "traces" / "service_lifecycle"
            registry_path = root / "runtime" / "registry" / "service_registry.json"
            calls = []

            loader = DynamicGeneratedServiceLoader(services_dir=services_dir, trace_dir=trace_dir, registry_path=registry_path)
            loader.start(context={"calls": calls}, scan_seconds=1)

            service_dir = services_dir / "sample_service"
            service_dir.mkdir(parents=True)
            (service_dir / "service.py").write_text(
                "from __future__ import annotations\n"
                "async def start(context):\n"
                "    context['calls'].append('started')\n"
                "    return {'status':'started'}\n"
                "async def stop(start_result=None):\n"
                "    return {'status':'stopped'}\n"
                "async def health(context=None):\n"
                "    return {'status':'ok'}\n",
                encoding="utf-8",
            )
            (service_dir / "service_manifest.json").write_text(json.dumps({
                "service_id": "sample_service",
                "enabled": True,
                "entrypoint": {"module": "service.py", "start": "start", "stop": "stop", "health": "health"},
            }), encoding="utf-8")

            await asyncio.sleep(1.5)
            await loader.stop()
            assert calls == ["started"]
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            assert "sample_service" in registry["services"]
            assert (trace_dir / "dynamic_service_loader.jsonl").exists()

    asyncio.run(main())


if __name__ == "__main__":
    test_loader_loads_service_created_after_runtime_start()
    print("dynamic generated service lifecycle verification passed")
