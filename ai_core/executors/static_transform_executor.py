from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import PROJECT_ROOT
from ai_core.validation.schema_validator import SchemaValidator
class StaticTransformExecutor:
    def __init__(self): self.loader=ConfigLoader(); self.validator=SchemaValidator()
    async def execute(self, workflow_node, node_config, state, capability_result):
        schema=self.loader.load_json(PROJECT_ROOT/node_config['output_schema'])
        result={'_executor_type':'static_transform','_node_id':node_config.get('node_id'),'_status':'executed','previous_result_keys':list(state.get('results',{}).keys())}
        self.validator.validate_data(result,schema); return result
