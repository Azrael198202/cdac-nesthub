class CapabilitySpecGenerator:
    def generate(self, capability_id: str, node_id: str, context: dict) -> dict:
        return {'capability_id':capability_id,'type':'unknown','description':f'Generated capability spec for node {node_id}.','detect':{},'install':{},'verify':{},'runtime_register':{'tool_name':capability_id},'security':{'approval_required':True,'risk_level':'unknown'}}
