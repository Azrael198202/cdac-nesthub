from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import PROJECT_ROOT
from ai_core.validation.schema_validator import SchemaValidator
class ToolCallExecutor:
    def __init__(self): self.loader=ConfigLoader(); self.validator=SchemaValidator()
    async def execute(self, workflow_node, node_config, state, capability_result):
        schema=self.loader.load_json(PROJECT_ROOT/node_config['output_schema'])
        result={'_executor_type':'tool_call','_node_id':node_config.get('node_id'),'_status':'tool_call_ready','_note':'Tool behavior must be configured in runtime/generated/tools or node_config.'}
        self.validator.validate_data(result,schema); return result
