from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import CONFIGS_DIR, RUNTIME_GENERATED
from ai_core.events.event_bus import event_bus
from ai_core.runtime.bootstrap.model_requirement_generator import ModelRequirementGenerator
from ai_core.runtime.bootstrap.provider_discovery import ProviderDiscovery


class RuntimeBootstrapService:
    """Initializes runtime cognitive topology at process startup.

    The runtime first tries to let a strong configured model generate a topology
    from current feature/provider inventories. If unavailable, it writes a seed
    topology so execution can continue deterministically.
    """

    OUTPUT_DIR = RUNTIME_GENERATED / "system_topology"
    OUTPUT_PATH = OUTPUT_DIR / "runtime_governance_graph.json"

    def __init__(self) -> None:
        self.loader = ConfigLoader()
        self.discovery = ProviderDiscovery()
        self.generator = ModelRequirementGenerator()

    async def bootstrap(self, *, force: bool = False) -> dict[str, Any]:
        if self.OUTPUT_PATH.exists() and not force:
            try:
                return json.loads(self.OUTPUT_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        run_id = "runtime_bootstrap_" + uuid4().hex[:10]
        feature_inventory = self.loader.load_json(CONFIGS_DIR / "runtime_feature_inventory.json")
        provider_inventory = self.discovery.discover()
        seed_topology = self.loader.load_json(CONFIGS_DIR / "runtime_bootstrap_seed_topology.json")
        await event_bus.emit(run_id, {
            "type": "RUNTIME_BOOTSTRAP_START",
            "title": "Runtime bootstrap started",
            "message": "Generating or loading cognitive topology.",
        })
        generated: dict[str, Any] | None = None
        try:
            generated = await self.generator.generate(
                run_id=run_id,
                feature_inventory=feature_inventory,
                provider_inventory=provider_inventory,
                seed_topology=seed_topology,
            )
            source = "strong_model"
        except Exception as exc:
            generated = dict(seed_topology)
            generated["bootstrap_warning"] = str(exc)
            source = "seed_fallback"
        generated.setdefault("version", "2.8.15")
        generated["bootstrap_source"] = source
        generated["bootstrapped_at"] = datetime.now(timezone.utc).isoformat()
        generated["provider_inventory_snapshot"] = provider_inventory
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self.OUTPUT_PATH.write_text(json.dumps(generated, ensure_ascii=False, indent=2), encoding="utf-8")
        await event_bus.emit(run_id, {
            "type": "RUNTIME_BOOTSTRAP_DONE",
            "title": "Runtime bootstrap completed",
            "message": "Topology source=" + source,
        })
        return generated
