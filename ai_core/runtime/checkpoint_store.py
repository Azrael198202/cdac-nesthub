import json
from typing import Dict, Any, Optional
from ai_core.config.paths import RUNTIME_CHECKPOINTS
class CheckpointStore:
    def save(self, run_id: str, data: Dict[str, Any]) -> None:
        RUNTIME_CHECKPOINTS.mkdir(parents=True, exist_ok=True)
        (RUNTIME_CHECKPOINTS / f"{run_id}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    def load(self, run_id: str) -> Optional[Dict[str, Any]]:
        p = RUNTIME_CHECKPOINTS / f"{run_id}.json"
        return json.loads(p.read_text(encoding='utf-8')) if p.exists() else None
    def delete(self, run_id: str) -> None:
        p = RUNTIME_CHECKPOINTS / f"{run_id}.json"
        if p.exists(): p.unlink()
