from ai_core.executors.llm_json_executor import LLMJsonExecutor
from ai_core.executors.generic_input_parsing_executor import GenericInputParsingExecutor
from ai_core.executors.tool_call_executor import ToolCallExecutor
from ai_core.executors.workflow_call_executor import WorkflowCallExecutor
from ai_core.executors.mcp_call_executor import MCPCallExecutor
from ai_core.executors.human_review_executor import HumanReviewExecutor
from ai_core.executors.python_plugin_executor import PythonPluginExecutor
from ai_core.executors.static_transform_executor import StaticTransformExecutor
from ai_core.executors.output_executor import OutputExecutor
class ExecutorRegistry:
    def __init__(self): self.executors={'llm_json':LLMJsonExecutor(),'generic_input_parsing':GenericInputParsingExecutor(),'tool_call':ToolCallExecutor(),'workflow_call':WorkflowCallExecutor(),'mcp_call':MCPCallExecutor(),'human_review':HumanReviewExecutor(),'python_plugin':PythonPluginExecutor(),'static_transform':StaticTransformExecutor(),'output':OutputExecutor()}
    def get(self, executor_type: str):
        if executor_type not in self.executors: raise ValueError(f'Unsupported executor_type: {executor_type}')
        return self.executors[executor_type]
