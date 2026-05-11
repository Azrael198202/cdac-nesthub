from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import PROJECT_ROOT
from ai_core.executors.template_engine import TemplateEngine
from ai_core.validation.schema_validator import SchemaValidator
class LLMJsonExecutor:
    def __init__(self): self.loader=ConfigLoader(); self.template=TemplateEngine(); self.validator=SchemaValidator()
    async def execute(self, workflow_node: dict, node_config: dict, state: dict, capability_result: dict) -> dict:
        prompt=self.loader.load_yaml(PROJECT_ROOT/node_config['prompt']); schema=self.loader.load_json(PROJECT_ROOT/node_config['output_schema'])
        _=self.template.render(prompt.get('user_template',''), {'user_input':state.get('input',''),'previous_results':state.get('results',{}),'capability_result':capability_result})
        result=self._schema_shaped(node_config,schema,state,prompt); self.validator.validate_data(result,schema); return result
    def _schema_shaped(self,node_config,schema,state,prompt):
        result={'_executor_type':'llm_json','_node_id':node_config.get('node_id'),'_prompt_id':prompt.get('id'),'_status':'executed_by_generic_llm_json_executor','_note':'ai_core contains no task logic; replace this adapter via runtime provider config.'}
        props=schema.get('properties',{})
        for key in schema.get('required',[]):
            typ=props.get(key,{}).get('type')
            if key=='original_input': result[key]=state.get('input','')
            elif typ=='array': result[key]=[]
            elif typ=='number': result[key]=0.0
            elif typ=='boolean': result[key]=False
            else: result[key]='generated_by_runtime_prompt'
        return result
