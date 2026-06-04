from auxiliary_brain.delegation.delegation_runtime import AgentDelegationRuntime
from ai_core.executors.llm_json_executor import LLMJsonExecutor

assert AgentDelegationRuntime is not None
assert hasattr(LLMJsonExecutor, "_merge_detected_structural_entities")
print("weather_dependency_imports_ok")
