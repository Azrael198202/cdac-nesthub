from typing import Dict, Any, Optional
from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import RUNTIME_CONFIGS,RUNTIME_GENERATED,RUNTIME_REGISTRY
class CapabilityRegistry:
    def __init__(self): self.loader=ConfigLoader()
    def find_spec(self, capability_id: str)->Optional[Dict[str,Any]]:
        for d in [RUNTIME_CONFIGS/'capabilities', RUNTIME_GENERATED/'capabilities']:
            for p in d.glob('*.yaml'):
                spec=self.loader.load_yaml(p)
                if spec.get('capability_id')==capability_id: spec['_path']=str(p); return spec
        return None
    def mark_ready(self, capability_id: str, spec: Dict[str,Any]):
        p=RUNTIME_REGISTRY/'installed_capabilities.json'; data=self.loader.load_json(p); data[capability_id]={'status':'ready','type':spec.get('type'),'spec_path':spec.get('_path','')}; self.loader.save_json(p,data)
    def save_generated_spec(self, spec: Dict[str,Any]): self.loader.save_yaml(RUNTIME_GENERATED/'capabilities'/f"{spec['capability_id']}.yaml", spec)
