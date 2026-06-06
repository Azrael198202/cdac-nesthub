from typing import Tuple, Dict, Any
from ai_core.events.event_bus import event_bus
from ai_core.capabilities.capability_registry import CapabilityRegistry
from auxiliary_brain.capability_acquisition.blueprint_generator import CapabilitySpecGenerator
class CapabilityResolver:
    def __init__(self): self.registry=CapabilityRegistry(); self.generator=CapabilitySpecGenerator()
    async def ensure_capabilities(self, run_id: str, node_config: dict, context: dict)->Tuple[bool,Dict[str,Any]]:
        ready=[]
        for cap_id in node_config.get('capabilities',[]):
            await event_bus.emit(run_id, {'type':'CAPABILITY_ROUTE','title':'Checking capability','message':cap_id})
            spec=self.registry.find_spec(cap_id)
            if not spec:
                spec=self.generator.generate(cap_id,node_config.get('node_id','unknown'),context); self.registry.save_generated_spec(spec)
                return False, {'approval_required':True,'pending_kind':'capability_spec_review','capability_id':cap_id,'spec':spec,'message':f'Generated a new capability spec for {cap_id}.'}
            self.registry.mark_ready(cap_id,spec); await event_bus.emit(run_id, {'type':'CAPABILITY_READY','title':'Capability ready','message':cap_id}); ready.append({'capability_id':cap_id,'spec':spec})
        return True, {'ready_capabilities':ready}
    async def install_start_verify(self, run_id: str, spec: dict)->bool:
        self.registry.mark_ready(spec['capability_id'],spec); await event_bus.emit(run_id, {'type':'CAPABILITY_READY','title':'Capability registered','message':spec['capability_id'],'progress':100}); return True
