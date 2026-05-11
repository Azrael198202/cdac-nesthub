import importlib
class PythonPluginExecutor:
    async def execute(self, workflow_node, node_config, state, capability_result):
        plugin=node_config.get('plugin')
        if not plugin: return {'_executor_type':'python_plugin','_status':'missing_plugin'}
        module_name, func_name = plugin.rsplit(':',1); module=importlib.import_module(module_name); return getattr(module,func_name)(workflow_node=workflow_node,node_config=node_config,state=state,capability_result=capability_result)
