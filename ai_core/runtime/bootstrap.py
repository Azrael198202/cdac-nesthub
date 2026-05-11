from ai_core.config.paths import RUNTIME_DIR,RUNTIME_CONFIGS,RUNTIME_CHECKPOINTS,RUNTIME_TRACES,RUNTIME_KNOWLEDGE,RUNTIME_DATASETS,RUNTIME_GENERATED,RUNTIME_REGISTRY
from ai_core.config.loader import ConfigLoader
class RuntimeBootstrap:
    def __init__(self): self.loader = ConfigLoader()
    def ensure(self):
        for d in [RUNTIME_DIR,RUNTIME_CONFIGS,RUNTIME_CONFIGS/'capabilities',RUNTIME_CONFIGS/'environment',RUNTIME_CONFIGS/'workflows',RUNTIME_CHECKPOINTS,RUNTIME_TRACES,RUNTIME_KNOWLEDGE,RUNTIME_DATASETS,RUNTIME_GENERATED/'capabilities',RUNTIME_GENERATED/'nodes',RUNTIME_GENERATED/'prompts',RUNTIME_GENERATED/'schemas',RUNTIME_GENERATED/'workflows',RUNTIME_GENERATED/'tools',RUNTIME_REGISTRY]: d.mkdir(parents=True, exist_ok=True)
        self._workflow(); self._nodes(); self._prompts(); self._schemas(); self._capabilities(); self._env(); self._registry(); self._datasets()
    def _workflow(self):
        p=RUNTIME_CONFIGS/'workflows'/'base_orchestration.yaml'
        if not p.exists(): self.loader.save_yaml(p, {'workflow_id':'base_orchestration','name':'Base Config Driven Orchestration','nodes':[{'id':n,'node_config':f'runtime/generated/nodes/{n}.yaml'} for n in ['input_parsing','intent_recognition','context_awareness','workflow_planning','execution','feedback_learning','output']]})
    def _nodes(self):
        specs=[('input_parsing','llm_json',['text_understanding'],True,15),('intent_recognition','llm_json',['text_understanding'],True,15),('context_awareness','static_transform',['local_knowledge_store'],False,10),('workflow_planning','llm_json',['workflow_generation'],True,20),('execution','tool_call',['generic_tool_execution'],True,25),('feedback_learning','static_transform',['local_knowledge_store'],False,10),('output','static_transform',['response_generation'],False,5)]
        for node, ex, caps, review, weight in specs:
            p=RUNTIME_GENERATED/'nodes'/f'{node}.yaml'
            if not p.exists(): self.loader.save_yaml(p, {'node_id':node,'executor_type':ex,'prompt':f'runtime/generated/prompts/{node}.yaml','output_schema':f'runtime/generated/schemas/{node}.schema.json','capabilities':caps,'review_required':review,'progress_weight':weight})
    def _prompts(self):
        for node in ['input_parsing','intent_recognition','context_awareness','workflow_planning','execution','feedback_learning','output']:
            p=RUNTIME_GENERATED/'prompts'/f'{node}.yaml'
            if not p.exists(): self.loader.save_yaml(p, {'id':f'{node}_prompt','version':'1.0','system':'Runtime-generated prompt placeholder. Replace with LLM-generated prompt.','user_template':'User input: {{ user_input }}\nPrevious results: {{ previous_results }}','output_contract':{}})
    def _schemas(self):
        schemas={'input_parsing':{'type':'object','required':['original_input','required_capabilities'],'properties':{'original_input':{'type':'string'},'required_capabilities':{'type':'array'}}},'intent_recognition':{'type':'object','required':['confidence'],'properties':{'confidence':{'type':'number'}}},'workflow_planning':{'type':'object','required':['planned_steps'],'properties':{'planned_steps':{'type':'array'}}}}
        for node in ['input_parsing','intent_recognition','context_awareness','workflow_planning','execution','feedback_learning','output']:
            p=RUNTIME_GENERATED/'schemas'/f'{node}.schema.json'
            if not p.exists(): self.loader.save_json(p, schemas.get(node, {'type':'object'}))
    def _capabilities(self):
        for cap in ['text_understanding','workflow_generation','local_knowledge_store','generic_tool_execution','response_generation']:
            p=RUNTIME_CONFIGS/'capabilities'/f'{cap}.yaml'
            if not p.exists(): self.loader.save_yaml(p, {'capability_id':cap,'type':'generic_capability','description':'Generic runtime capability.','detect':{},'install':{},'verify':{},'runtime_register':{'tool_name':cap},'security':{'approval_required':False,'risk_level':'low'}})
    def _env(self):
        p=RUNTIME_CONFIGS/'environment'/'auto_answers.yaml'
        if not p.exists(): self.loader.save_yaml(p, {'enabled':True,'rules':[{'match':'Do you agree','answer':'Y'}]})
        p=RUNTIME_CONFIGS/'environment'/'command_profiles.yaml'
        if not p.exists(): self.loader.save_yaml(p, {'default':{'timeout_seconds':1200,'retries':1,'use_pty':False,'auto_answer':True},'profiles':[]})
    def _registry(self):
        for name in ['installed_capabilities.json','tool_registry.json','provider_registry.json']:
            p=RUNTIME_REGISTRY/name
            if not p.exists(): self.loader.save_json(p,{})
    def _datasets(self):
        for name in ['finetune.jsonl','eval_cases.jsonl']:
            p=RUNTIME_DATASETS/name
            if not p.exists(): p.write_text('', encoding='utf-8')
