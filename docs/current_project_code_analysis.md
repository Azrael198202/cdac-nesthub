# 当前工程代码分析报告
生成日期：2026-06-05

## 分析范围
- 已排除根目录下的 `runtime/`，该目录被视为运行时生成物、缓存、注册表、日志、上传文件和外部运行环境，不作为源码架构分析对象。
- 已排除 `.venv/`、`.git/`、`__pycache__/`。
- `ai_core/runtime/` 是源码包的一部分，不等同于根目录 `runtime/`，本报告纳入分析。
- 纳入 Python 文件数：398；源码行数约：67719。

## 1. 项目总体说明与目标判断
从 README、包命名、配置文件和代码边界看，`cdac-nesthub` 的目标不是实现某个固定业务系统，而是构建一个通用 AI 运行内核与辅助编排层。系统把用户输入解析、意图契约、工作流规划、能力发现、工具/模块生成、沙箱验证、执行、证据归约、自修复、最终合成等步骤拆成明确阶段，并通过运行时注册表和配置来接入具体能力。

项目核心约束是：核心源码保持通用，不把具体业务词、固定业务流程或一次性用户值硬写进 `ai_core`；具体能力应进入根目录 `runtime/` 下的注册表、生成物、配置或运行时资源。换句话说，该工程想做的是“可扩展、可验证、可自修复的 AI 任务运行平台”。

主要运行链路可概括为：用户输入进入 `apps/api` 或 `auxiliary_brain/studio`，辅助脑创建参与者/任务图并补齐参数，主运行脑 `ai_core` 负责解析、规划、选择能力、执行工具或模型、验证结果、必要时自修复，最后由展示/合成层输出用户可读结果。

## 2. 代码结构与功能说明

### 顶层结构
- `main.py`：FastAPI/uvicorn 启动入口，加载 `apps.api.server:app`。
- `apps/`：HTTP API 与静态 Web 页面，承接 Studio、运行监控、知识库、控制台等界面。
- `ai_core/`：主运行脑，包含阶段契约、执行器、LLM 路由、工具/模块生成、运行时能力、证据、语义约束、自修复、模型治理等通用能力。
- `auxiliary_brain/`：辅助脑，负责 Agent Studio、任务图、参数契约、委托主运行脑、运行时代码分析和能力获取辅助。
- `configs/`：静态种子配置，包含模型路由、能力模板、权限策略、参数契约、命令集等。
- `schema/`：运行契约 JSON Schema。
- `runtime_assets/`：打包随源码提供的运行时种子资产，例如默认能力规划器。
- `tools/`、`scripts/`、`tests/`：验证脚本、维护脚本和少量测试入口。
- `docs/verification/`：历史验证报告。

### 包级职责
- `ai_core/agent_delegation/`：主运行脑委托客户端，接收辅助脑请求、执行/恢复参与者请求、合成委托结果。
- `ai_core/approval/`：通用人工审批门，用文件记录高风险操作的审批请求和结果。
- `ai_core/artifacts/`：上传文件注册、引用解析、编辑提案、可调用文件参数契约构建。
- `ai_core/capabilities/`：运行时能力注册与调度，按配置和规则匹配能力而非硬编码业务。
- `ai_core/commands/`：Studio 命令集默认值、运行时覆盖和命令注册表管理。
- `ai_core/config/`：JSON/YAML 配置读写与路径常量。
- `ai_core/connections/`：运行时连接资料和秘密引用管理。
- `ai_core/context/`：会话记忆、向量记忆、上下文裁剪、提示预算、执行复用和证据降噪。
- `ai_core/dependencies/`：声明式 Python 依赖安装与缺失 import 修复。
- `ai_core/environment/`：系统二进制解析、Docker 预检查。
- `ai_core/events/`：内部事件总线和缺能力事件。
- `ai_core/evolution/`：审批、修正、反馈等运行学习数据收集。
- `ai_core/execution/`：执行过程中的候选策略、参数解析、证据质量、结果分类、继续执行判断。
- `ai_core/executors/`：工具、MCP、工作流、静态转换、Python 插件、LLM JSON、人审、输出等执行器。
- `ai_core/graph/`：任务图契约、自检、调度、可视化快照。
- `ai_core/input_parsing/`：结构化实体抽取。
- `ai_core/interaction/`：对话运行时、自然对话、交互契约生成与校验、问题生成。
- `ai_core/knowledge/`：文档处理、知识库服务、嵌入索引。
- `ai_core/llm/`：模型提供方处理器、路由、安装、缓存、token 记录、升级策略。
- `ai_core/media/`：图片/视频生成服务和通用文本动画提供器。
- `ai_core/models/`：模型下载、生命周期、基准和路由注册。
- `ai_core/modules/`：运行时生成模块的生成、验证、加载、安装和注册。
- `ai_core/nodes/`：节点配置加载和节点运行。
- `ai_core/orchestration/`：工作流运行时与阶段契约。
- `ai_core/pipeline/`：核心阶段边界定义。
- `ai_core/presentation/`：结果清洗、材料构建、事实规范化、最终答案合成。
- `ai_core/providers/`：运行时 provider 注册、调用和生命周期。
- `ai_core/research/`：外部方案发现、API/端点发现与验证、Web/深度研究、模型候选评估。
- `ai_core/roles/`：运行角色契约、角色 Profile 选择和上下文裁剪。
- `ai_core/runtime/`：源码级运行时操作系统：能力、模型、证据、语义、治理、环境、浏览器、调度、自修复、观测等。
- `ai_core/sandbox/`：验证过的沙箱运行时。
- `ai_core/secrets/`：本地秘密存储抽象。
- `ai_core/security/`：依赖扫描和仓库依赖门。
- `ai_core/tools/`：运行时工具蓝图、代码生成请求、产物校验、工具注册、通用运行器。
- `ai_core/utils/`：安全 JSON 与安全子进程工具。
- `ai_core/validation/`：Schema 校验、自动修复、语义边界扫描和可恢复错误。
- `ai_core/web_evidence_optimizer/`：Web 证据查询规划和证据压缩优化。
- `ai_core/workflow/`：工作流契约构建、规范化、状态合并、执行状态修复和计划恢复。
- `auxiliary_brain/capability_acquisition/`：辅助侧能力获取流水线：蓝图、代码生成、验证、注册、修复协调。
- `auxiliary_brain/delegation/`：辅助侧任务图委托运行时，把任务图分发给主运行脑并处理恢复。
- `auxiliary_brain/parameters/`：参与者参数契约构建、缺参判断和值应用。
- `auxiliary_brain/protocols/`：辅助脑与主运行脑之间的请求/策略协议。
- `auxiliary_brain/runtime_codegen/`：动态值硬编码检测与运行时变量推断。
- `auxiliary_brain/storage/`：JSON 文件存储。
- `auxiliary_brain/studio/`：Agent Studio 服务、命令路由、语义规划、结构化步骤规划和工作流规划。

### Python 文件与内部方法清单
说明：下表按文件列出主要类、函数、方法。缩进两个空格的方法属于上方 class。空白说明表示源码中没有 docstring，功能按类/文件上下文理解。

#### .

- `main.py`（4 行）：/main.py 模块，围绕 main 提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `validate_source_package.py`（42 行）：/validate_source_package.py 模块，围绕 validate source package 提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `verify_agent_capability_binding_preservation.py`（35 行）：/verify_agent_capability_binding_preservation.py 模块，围绕 verify agent capability binding preservation 提供结构化运行、配置、验证或桥接能力。
  - L4 `def main`

- `verify_step_template_binding.py`（31 行）：/verify_step_template_binding.py 模块，围绕 verify step template binding 提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `verify_task_parameter_binding_loop_fix.py`（83 行）：/verify_task_parameter_binding_loop_fix.py 模块，围绕 verify task parameter binding loop fix 提供结构化运行、配置、验证或桥接能力。
  - L13 `def assert_uploaded_artifact_reads_agent_request_parameters`
  - L34 `def assert_resume_does_not_restart_completed_participants`
  - L56 `def assert_registered_tool_hydrates_task_runtime_values`

#### ai_core

- `ai_core/__init__.py`（0 行）：ai_core/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/agent_delegation/__init__.py`（3 行）：agent_delegation/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/agent_delegation/primary_brain_client.py`（1481 行）：agent_delegation/primary_brain_client.py 模块，围绕 primary brain client 提供结构化运行、配置、验证或桥接能力。
  - L19 `class AgentExecutionRequest`
  - L30 `class AgentExecutionResult`
  - L42 `class PrimaryBrainDelegationClient`：Delegates role work to the primary runtime.
  - L59 `  def __init__`
  - L63 `  async def execute_agent_request`
  - L128 `  def _try_self_contained_runtime_observation`：Answer self-contained runtime-state participant requests without LLM.
  - L166 `  async def execute_intermediate_step`：Execute a generated dataflow step with the smallest safe prompt.
  - L277 `  def _recover_public_answer_from_invalid_json`
  - L281 `  def _recover_public_answer_from_provider_error`
  - L288 `  def _recover_public_answer_from_text`
  - L307 `  def _normalize_public_step_answer`
  - L333 `  def _compact_declared_inputs`
  - L361 `  def _compact_text`
  - L368 `  def _build_lean_step_prompt`
  - L376 `  def _project_single_upstream_result_if_possible`
  - L390 `  async def resume_agent_request`：Resume a paused primary-runtime participant run from its saved checkpoint.
  - L443 `  async def _resume_state_direct`：Continue a saved primary-runtime state without restarting earlier nodes.
  - L546 `  async def _run_runtime_with_timeout`
  - L574 `  def _compute_primary_runtime_timeout_seconds`：Compute a whole-run timeout from generic runtime structure.
  - L602 `  def _clean_runtime_inputs`
  - L615 `  def _find_workflow_node_index`
  - L623 `  def _clear_waiting_state`
  - L629 `  def _merge_human_inputs_into_result`：Merge form values into a JSON-like node result without domain rules.
  - L651 `  def _assign_path_value`
  - L687 `  def _collect_null_paths`
  - L705 `  def _build_resume_modified_result`
  - L720 `  async def synthesize_delegated_results`：Create the final delegated answer inside the primary runtime boundary.
  - L763 `  def _should_attempt_direct_public_answer`：Use a small direct-answer fallback only for non-artifact participants.
  - L795 `  def _results_show_runtime_execution_path`：Return True once the primary runtime has entered a planned execution path.
  - L808 `  def _results_contain_blocking_execution_failure`：Return True when primary execution explicitly rejected its material.
  - L846 `  def _shared_context_has_missing_required_inputs`：Return True when the selected execution context still needs user input.
  - L869 `  def _public_runtime_inputs`：Keep only user-confirmed scalar/list/dict inputs for direct material fallback.
  - L903 `  async def _direct_public_answer_fallback`：Ask the configured model for one concise public answer.
  - L963 `  def _build_agent_message`
  - L986 `  def _usable_agent_results`
  - L1011 `  async def _compose_or_escalate_delegated_final_answer`
  - L1077 `  def _answer_has_result_material`：Return True only when a participant answer contains user-facing material.
  - L1144 `  def _compose_delegated_final_answer`
  - L1184 `  def _clean_participant_answer`
  - L1196 `  def _build_synthesis_message`
  - L1220 `  def _extract_investigation_report_answer`：Extract a safe user-facing answer from generic runtime results.
  - L1282 `  def _extract_final_answer`
  - L1319 `  def _extract_public_answer_material`
  - L1359 `  def _extract_status`
  - L1378 `  def _extract_missing_inputs`

- `ai_core/approval/__init__.py`（1 行）：Generic human approval gates for runtime operations.
  - 无显式顶层类/函数。

- `ai_core/approval/human_approval_gate.py`（78 行）：approval/human_approval_gate.py 模块，围绕 human approval gate 提供结构化运行、配置、验证或桥接能力。
  - L13 `class ApprovalDecision`
  - L22 `class HumanApprovalGate`：File-based approval gate for risky runtime operations.
  - L31 `  def __init__`
  - L35 `  def request`
  - L57 `  def check`
  - L75 `  def _request_id`

- `ai_core/artifacts/__init__.py`（2 行）：artifacts/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/artifacts/artifact_edit_service.py`（332 行）：artifacts/artifact_edit_service.py 模块，围绕 artifact edit service 提供结构化运行、配置、验证或桥接能力。
  - L18 `class ArtifactEditProposal`
  - L27 `class ArtifactEditService`：Create reviewable edited copies of uploaded artifacts.
  - L36 `  def __init__`
  - L43 `  def list_artifacts`
  - L46 `  def get_artifact`
  - L53 `  async def propose_edit`
  - L105 `  def confirm`
  - L125 `  def cancel`
  - L134 `  def _mark_registry_replacement`
  - L143 `  def _try_deterministic_edit`：Apply small, safe structural edits without asking the LLM.
  - L258 `  async def _generate_edit`
  - L298 `  def _proposal_meta_path`
  - L302 `  def _read_meta`
  - L312 `  def _safe_path`
  - L328 `  def _read_text`
  - L331 `  def _now`

- `ai_core/artifacts/artifact_registry.py`（160 行）：artifacts/artifact_registry.py 模块，围绕 artifact registry 提供结构化运行、配置、验证或桥接能力。
  - L12 `class UploadedArtifactRegistry`：Generic registry for user-uploaded runtime artifacts.
  - L21 `  def __init__`
  - L24 `  def ensure`
  - L30 `  def list`
  - L38 `  def write`
  - L42 `  def register_file`
  - L63 `  def normalize_records`
  - L87 `  def resolve_reference`
  - L109 `  def resolve_from_text`
  - L139 `  def bind_for_instruction`
  - L146 `  def _normalize_one`

- `ai_core/artifacts/uploaded_artifact_contract.py`（563 行）：artifacts/uploaded_artifact_contract.py 模块，围绕 uploaded artifact contract 提供结构化运行、配置、验证或桥接能力。
  - L15 `class UploadedArtifactRef`
  - L23 `class UploadedArtifactContractBuilder`：Build execution contracts for user-provided artifacts.
  - L31 `  def __init__`
  - L39 `  def collect_refs`
  - L61 `  def build_contract`
  - L90 `  def _step_requests_uploaded_artifact`
  - L109 `  def inspect_ref`
  - L127 `  def write_manifest`
  - L135 `  def _containers`
  - L149 `  def _joined_text`
  - L170 `  def _iter_nested`
  - L181 `  def _coerce_refs`
  - L213 `  def _safe_path`
  - L235 `  def _inspect_python`
  - L276 `  def _schema_from_annotation`：Map Python type annotations to a small JSON-schema shape.
  - L298 `  def _annotation_text`
  - L310 `  def _extract_argparse_required`
  - L331 `  def _known_values`
  - L353 `  def _merge_known_mapping`
  - L360 `  def _agent_request_envelopes`
  - L405 `  def _leading_json_object`
  - L429 `  def _known_mappings_from_agent_request`
  - L445 `  def _is_usable_runtime_value`：Return True only for concrete user/runtime values.
  - L474 `  def _missing_inputs`：Return UI fields for missing callable inputs.
  - L506 `  def _parameter_field`
  - L526 `  def _known_value_for_required_field`
  - L538 `  def _aliases_for_required_field`
  - L548 `  def _snake_to_camel`
  - L554 `  def _normalize_key`
  - L557 `  def _human_label`
  - L561 `  def _safe_name`

- `ai_core/capabilities/__init__.py`（0 行）：capabilities/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/capabilities/capability_dispatcher.py`（148 行）：capabilities/capability_dispatcher.py 模块，围绕 capability dispatcher 提供结构化运行、配置、验证或桥接能力。
  - L13 `class CapabilityDispatcher`：Dispatch direct user requests to runtime capabilities.
  - L22 `  def __init__`
  - L30 `  async def dispatch`
  - L56 `  def match`
  - L85 `  def _rules`
  - L98 `  def _score`
  - L112 `  def _excluded`
  - L122 `  def _token_matches`
  - L130 `  def _contract_text`

- `ai_core/capabilities/capability_registry.py`（14 行）：capabilities/capability_registry.py 模块，围绕 capability registry 提供结构化运行、配置、验证或桥接能力。
  - L4 `class CapabilityRegistry`
  - L5 `  def __init__`
  - L6 `  def find_spec`
  - L12 `  def mark_ready`
  - L14 `  def save_generated_spec`

- `ai_core/commands/__init__.py`（3 行）：commands/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/commands/command_set_service.py`（321 行）：commands/command_set_service.py 模块，围绕 command set service 提供结构化运行、配置、验证或桥接能力。
  - L12 `class CommandSetService`：Manage default and runtime-customized Studio command sets.
  - L21 `  def __init__`
  - L29 `  def get_default`
  - L36 `  def get_runtime_override`
  - L39 `  def get_effective`
  - L43 `  def list_commands`
  - L54 `  def update_runtime`
  - L69 `  def update_from_instruction`：Apply a small generic instruction grammar for command-set changes.
  - L122 `  def _add_command`
  - L147 `  def _add_phrase`
  - L177 `  def _remove_phrase`
  - L190 `  def get_registry`：Return normalized command registry entries sorted by priority.
  - L199 `  def _normalize_registry`
  - L232 `  def _migrate_legacy_update`：Convert legacy command_phrases payloads into commands[] entries.
  - L282 `  def _read_json`
  - L291 `  def _merge`
  - L306 `  def _extract_json_object`

- `ai_core/commands/default_command_set.py`（262 行）：commands/default_command_set.py 模块，围绕 default command set 提供结构化运行、配置、验证或桥接能力。
  - L6 `def default_command_set`：Return the built-in Studio command registry.

- `ai_core/config/__init__.py`（0 行）：config/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/config/loader.py`（17 行）：config/loader.py 模块，围绕 loader 提供结构化运行、配置、验证或桥接能力。
  - L5 `class ConfigLoader`
  - L6 `  def load_yaml`
  - L9 `  def save_yaml`
  - L12 `  def load_json`
  - L15 `  def save_json`

- `ai_core/config/paths.py`（17 行）：config/paths.py 模块，围绕 paths 提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/connections/__init__.py`（3 行）：connections/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/connections/connection_profile_store.py`（178 行）：connections/connection_profile_store.py 模块，围绕 connection profile store 提供结构化运行、配置、验证或桥接能力。
  - L12 `class ConnectionProfileStore`：Generic runtime connection profile persistence.
  - L22 `  def __init__`
  - L26 `  def upsert_profile`
  - L66 `  def get_profile`
  - L83 `  def list_profiles`
  - L103 `  def missing_requirements`
  - L136 `  def runtime_context_for`
  - L146 `  def public_profile`
  - L158 `  def _profile_path`
  - L161 `  def _secret_ref`
  - L164 `  def _schema_fields`
  - L170 `  def _schema_required_fields`
  - L176 `  def _safe_id`

- `ai_core/context/__init__.py`（0 行）：context/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/context/evidence_noise_reducer.py`（303 行）：context/evidence_noise_reducer.py 模块，围绕 evidence noise reducer 提供结构化运行、配置、验证或桥接能力。
  - L10 `class EvidenceNoiseReducer`：Domain-neutral evidence cleaner and selector.
  - L30 `  def reduce`：Generic compact evidence reducer used by role-scoped prompts.
  - L61 `  def compact_generation_request`
  - L101 `  def compact_discovery`
  - L121 `  def extract_required_terms`
  - L146 `  def extract_evidence_items`
  - L180 `  def score_evidence_item`
  - L220 `  def clean_text`
  - L238 `  def _compact_step`
  - L243 `  def _compact_semantics`
  - L246 `  def _compact_constraints`
  - L250 `  def _compact_endpoint_verification`
  - L265 `  def _compact_failed_verification`
  - L270 `  def _compact_candidate`
  - L275 `  def _aliases`
  - L301 `  def _truncate`

- `ai_core/context/execution_capability.py`（116 行）：context/execution_capability.py 模块，围绕 execution capability 提供结构化运行、配置、验证或桥接能力。
  - L10 `class ExecutionCapability`：Generic capability detected from a reusable execution asset.
  - L28 `class ExecutionCapabilityResolver`：Resolve how a saved asset should be reused.
  - L42 `  def resolve`
  - L77 `  def _existing_executable_paths`
  - L87 `  def _select_callable`
  - L100 `  def public_functions`

- `ai_core/context/execution_reuse_store.py`（754 行）：context/execution_reuse_store.py 模块，围绕 execution reuse store 提供结构化运行、配置、验证或桥接能力。
  - L23 `class ReuseDecision`
  - L30 `class ExecutionReuseStore`：Durable execution reuse registry.
  - L40 `  def __init__`
  - L47 `  def register_success`
  - L104 `  def get_asset`
  - L121 `  def decide`
  - L140 `  def _has_usable_required_contract_value`
  - L157 `  def missing_inputs`
  - L179 `  async def execute_reused_asset`
  - L215 `  async def _execute_python_artifact`
  - L256 `  async def _run_python_artifact_bounded`
  - L296 `  def _decode_timeout_stream`
  - L303 `  def _normalize_process_output`
  - L338 `  def _compact_repeated_segments`
  - L354 `  def _lines_are_redundant`
  - L368 `  def _line_signature`
  - L375 `  def _select_artifact_function`
  - L388 `  def _build_function_runner`
  - L404 `  async def _execute_llm_generation`
  - L465 `  def save_short_answer`
  - L481 `  def get_short_answer`
  - L495 `  def _init_sqlite`
  - L530 `  def _collect_artifact_parameter_schema`
  - L554 `  def _public_python_functions`
  - L572 `  def _annotation_to_input_type`
  - L584 `  def _collect_parameter_schema`
  - L606 `  def _normalize_field`
  - L622 `  def _collect_artifact_paths`
  - L647 `  def _maybe_add_path`
  - L658 `  def _is_llm_generation_profile`
  - L666 `  def _extract_final_answer`
  - L672 `  def compact_final_answer`
  - L687 `  def _mark_used`
  - L699 `  def _append_jsonl`
  - L704 `  def _normalize_query`
  - L709 `  def record_repair_candidate`：Record user feedback as a generic self-repair candidate.
  - L739 `  def latest_repair_candidate`
  - L753 `  def _now`

- `ai_core/context/llm_stage_input_slimmer.py`（329 行）：context/llm_stage_input_slimmer.py 模块，围绕 llm stage input slimmer 提供结构化运行、配置、验证或桥接能力。
  - L7 `class LLMStageInputSlimmer`：Build compact, stage-scoped LLM input without domain/business rules.
  - L84 `  def slim_user_input`
  - L97 `  def slim_previous_results`
  - L110 `  def slim_runtime_context`
  - L119 `  def _compact_input_payload`
  - L153 `  def _compact_stage_goal_payload`
  - L171 `  def _compact_input_context`
  - L197 `  def _compact_runtime_context`
  - L209 `  def _allowed_previous_nodes`
  - L220 `  def _keep_known_result_fields`
  - L248 `  def _compact_value`
  - L267 `  def _trim_obj`
  - L273 `  def _trim`
  - L278 `  def _parse_json`
  - L303 `  def _extract_last_json_object`

- `ai_core/context/prompt_budget_manager.py`（51 行）：context/prompt_budget_manager.py 模块，围绕 prompt budget manager 提供结构化运行、配置、验证或桥接能力。
  - L9 `class PromptBudgetResult`
  - L16 `class PromptBudgetManager`：Generic prompt budget manager.
  - L24 `  def __init__`
  - L27 `  def budget_for`
  - L40 `  def fit_text`

- `ai_core/context/runtime_context_reducer.py`（66 行）：context/runtime_context_reducer.py 模块，围绕 runtime context reducer 提供结构化运行、配置、验证或桥接能力。
  - L6 `class RuntimeContextReducer`：Domain-neutral reducer for prompt-bound runtime context.
  - L19 `  def reduce_results`
  - L26 `  def reduce_capability_result`
  - L29 `  def _reduce_value`
  - L55 `  def _summarize_dict`
  - L63 `  def _truncate`

- `ai_core/context/session_memory_store.py`（371 行）：context/session_memory_store.py 模块，围绕 session memory store 提供结构化运行、配置、验证或桥接能力。
  - L16 `class ContextWindow`
  - L24 `class SessionMemoryStore`：Generic conversation/session persistence.
  - L32 `  def __init__`
  - L39 `  def start_or_get_session`
  - L62 `  def append_turn`
  - L110 `  def load_context_window`
  - L143 `  def save_summary`
  - L165 `  def record_feedback`
  - L187 `  def boundary_status`
  - L199 `  def list_sessions`：Return recently active sessions for UI navigation.
  - L245 `  def get_session_snapshot`
  - L256 `  def rename_session`
  - L271 `  def _init_sqlite`
  - L311 `  def _init_postgres_if_available`
  - L352 `  def _pg_execute`
  - L365 `  def _append_jsonl`
  - L370 `  def _now`

- `ai_core/context/token_estimator.py`（27 行）：context/token_estimator.py 模块，围绕 token estimator 提供结构化运行、配置、验证或桥接能力。
  - L7 `class TokenEstimator`：Small, dependency-free token estimator for runtime budgeting.
  - L17 `  def estimate_text`
  - L22 `  def estimate_obj`

- `ai_core/context/vector_memory_store.py`（153 行）：context/vector_memory_store.py 模块，围绕 vector memory store 提供结构化运行、配置、验证或桥接能力。
  - L14 `class VectorMemoryStore`：Small vector-like memory layer with optional Chroma support.
  - L22 `  def __init__`
  - L29 `  def add_text`
  - L53 `  def search`
  - L74 `  def _open_chroma_collection`
  - L82 `  def _chroma_add`
  - L97 `  def _chroma_search`
  - L124 `  def _read_records`
  - L137 `  def _embed`
  - L150 `  def _cosine`

- `ai_core/dependencies/__init__.py`（3 行）：dependencies/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/dependencies/runtime_dependency_installer.py`（183 行）：dependencies/runtime_dependency_installer.py 模块，围绕 runtime dependency installer 提供结构化运行、配置、验证或桥接能力。
  - L15 `class DependencyInstallResult`
  - L25 `  def to_dict`
  - L38 `class RuntimeDependencyInstaller`：Safe, generic Python dependency self-healing helper.
  - L56 `  def __init__`
  - L59 `  def missing_import_from_exception`
  - L75 `  def install_for_missing_import`
  - L89 `  def install_declared_dependencies`
  - L106 `  def install_package`
  - L138 `  def _package_for_import`
  - L157 `  def _import_guess_from_package`
  - L161 `  def _safe_package_spec`

- `ai_core/environment/binary_resolver.py`（36 行）：environment/binary_resolver.py 模块，围绕 binary resolver 提供结构化运行、配置、验证或桥接能力。
  - L7 `class BinaryResolver`
  - L8 `  def system_key`
  - L18 `  def resolve`
  - L31 `  def quote`

- `ai_core/environment/docker_precheck.py`（83 行）：environment/docker_precheck.py 模块，围绕 docker precheck 提供结构化运行、配置、验证或桥接能力。
  - L10 `class DockerPrecheckResult`
  - L21 `class DockerPrecheck`：Generic Docker precheck check used before isolated runtime execution.
  - L29 `  def check`
  - L73 `  def _run`

- `ai_core/events/__init__.py`（0 行）：events/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/events/event_bus.py`（33 行）：events/event_bus.py 模块，围绕 event bus 提供结构化运行、配置、验证或桥接能力。
  - L7 `class EventBus`
  - L8 `  def __init__`
  - L11 `  def queue`
  - L16 `  async def emit`
  - L24 `  async def stream`

- `ai_core/events/need_capability_event.py`（42 行）：events/need_capability_event.py 模块，围绕 need capability event 提供结构化运行、配置、验证或桥接能力。
  - L12 `class NeedCapabilityEvent`：Generic ai_core -> auxiliary_brain capability request event.
  - L29 `  def to_dict`

- `ai_core/evolution/__init__.py`（0 行）：evolution/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/evolution/approval_learning.py`（91 行）：evolution/approval_learning.py 模块，围绕 approval learning 提供结构化运行、配置、验证或桥接能力。
  - L11 `class ApprovalLearningService`
  - L12 `  def __init__`
  - L19 `  def record_approval`
  - L51 `  def build_prompt_reinforcement`
  - L67 `  def _retrieve`
  - L88 `  def _append_jsonl`

- `ai_core/evolution/correction_learning.py`（96 行）：evolution/correction_learning.py 模块，围绕 correction learning 提供结构化运行、配置、验证或桥接能力。
  - L7 `class CorrectionLearningService`：Runtime learning service for human JSON correction.
  - L12 `  def __init__`
  - L18 `  def record_correction`
  - L52 `  def retrieve_similar`
  - L77 `  def build_prompt_reinforcement`

- `ai_core/evolution/finetune_dataset_builder.py`（6 行）：evolution/finetune_dataset_builder.py 模块，围绕 finetune dataset builder 提供结构化运行、配置、验证或桥接能力。
  - L3 `class FinetuneDatasetBuilder`
  - L4 `  def append_case`

- `ai_core/evolution/runtime_learning.py`（175 行）：evolution/runtime_learning.py 模块，围绕 runtime learning 提供结构化运行、配置、验证或桥接能力。
  - L11 `class RuntimeLearningService`：Generic runtime learning service.
  - L22 `  def __init__`
  - L30 `  def record_reject_feedback`
  - L60 `  def record_correction`
  - L96 `  def retrieve_similar_corrections`
  - L130 `  def build_prompt_reinforcement`
  - L157 `  def _score`
  - L162 `  def _recommendation_from_feedback`
  - L172 `  def _append_jsonl`

- `ai_core/execution/__init__.py`（0 行）：execution/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/execution/answer_sufficiency_evaluator.py`（431 行）：execution/answer_sufficiency_evaluator.py 模块，围绕 answer sufficiency evaluator 提供结构化运行、配置、验证或桥接能力。
  - L9 `class RuntimeSemanticSignalEvaluator`：Language-neutral semantic signal scorer for answer evidence.
  - L21 `  def extract_query_terms`
  - L35 `  def _extract_embedded_objective`
  - L39 `  def _flatten_values`
  - L53 `  def semantic_signal`
  - L64 `  def factual_density`
  - L82 `  def answer_structure_signal`
  - L92 `  def looks_like_reference_document`
  - L102 `  def _lexical_overlap`
  - L114 `  def _tokens`
  - L122 `  def _normalize`
  - L125 `  def _dedupe_keep_order`
  - L135 `class AnswerSufficiencyEvaluator`：Decide whether generic web evidence can answer the user's request.
  - L149 `  def __init__`
  - L152 `  def evaluate`
  - L239 `  def _clean_known`
  - L267 `  def _evidence_text`
  - L294 `  def _coverage`
  - L319 `  def _variants`
  - L352 `  def _partial_variants`
  - L374 `  def _needs_fetch`
  - L385 `  def _aggregate_is_only_search_snippets`
  - L396 `  def _has_fetched_body`
  - L413 `  def _public_evidence`
  - L430 `  def _normalize`

- `ai_core/execution/candidate_extractor.py`（154 行）：execution/candidate_extractor.py 模块，围绕 candidate extractor 提供结构化运行、配置、验证或桥接能力。
  - L6 `class CandidateExtractor`：Extract retry candidates from generic discovery/tool metadata.
  - L13 `  def extract`
  - L19 `  def _collect`
  - L135 `  def _candidate`
  - L145 `  def _dedupe`

- `ai_core/execution/candidate_result_synthesizer.py`（63 行）：execution/candidate_result_synthesizer.py 模块，围绕 candidate result synthesizer 提供结构化运行、配置、验证或桥接能力。
  - L8 `class CandidateResultSynthesizer`：Select or synthesize the best result from multiple candidate attempts.
  - L16 `  def choose`
  - L32 `  def _attempt_score`
  - L51 `  def _compact`

- `ai_core/execution/candidate_strategy_scorer.py`（125 行）：execution/candidate_strategy_scorer.py 模块，围绕 candidate strategy scorer 提供结构化运行、配置、验证或桥接能力。
  - L10 `class CandidateStrategyScorer`：Score API/Web/browser extraction candidates with real light verification.
  - L22 `  def __init__`
  - L25 `  def score_candidates`
  - L33 `  def score_candidate`
  - L120 `  def _html_tool_type`

- `ai_core/execution/capability_resolution_decision.py`（66 行）：execution/capability_resolution_decision.py 模块，围绕 capability resolution decision 提供结构化运行、配置、验证或桥接能力。
  - L6 `class CapabilityResolutionDecision`：Decide how to resolve a missing capability without domain knowledge.
  - L14 `  def decide`
  - L52 `  def _has_api_or_web_evidence`
  - L63 `  def _has_external_evidence`

- `ai_core/execution/continuation_engine.py`（169 行）：execution/continuation_engine.py 模块，围绕 continuation engine 提供结构化运行、配置、验证或桥接能力。
  - L9 `class ContinuationEngine`：Decides how a workflow should pause or continue after an execution result.
  - L12 `  def __init__`
  - L16 `  def build_pending_action`
  - L79 `  def _runtime_parameter_request`：Preserve runtime parameter contracts generated by validation/execution.
  - L131 `  def _build_optional_credential_request`
  - L161 `  def _detect_language`

- `ai_core/execution/evidence_direct_answer.py`（456 行）：execution/evidence_direct_answer.py 模块，围绕 evidence direct answer 提供结构化运行、配置、验证或桥接能力。
  - L11 `class EvidenceDirectAnswerBuilder`：Build a reusable, domain-neutral result from verified evidence.
  - L22 `  def build`
  - L139 `  def _known_parameters`
  - L179 `  def _candidate_text`
  - L223 `  def _coverage_score`
  - L240 `  def _variants`
  - L279 `  def _has_measurement_signal`
  - L286 `  def _build_answer_material`
  - L304 `  def _extract_structured_records`
  - L324 `  def _candidate_blocks`
  - L332 `  def _extract_generic_fields`
  - L356 `  def _extract_attributes`
  - L364 `  def _extract_numbers_with_context`
  - L369 `  def _compact_text`
  - L387 `  def _strip_markup`
  - L393 `  def _looks_like_markup`
  - L397 `  def _normalize_text`
  - L400 `  def _looks_like_date`
  - L404 `  def _looks_like_url`
  - L407 `  def _contains_alpha`
  - L410 `  def _matched_value`
  - L417 `  def _label`
  - L420 `  def _dedupe_keep_order`
  - L430 `  def _dedupe_records`
  - L440 `  def _compact_attempts`

- `ai_core/execution/evidence_quality_validator.py`（151 行）：execution/evidence_quality_validator.py 模块，围绕 evidence quality validator 提供结构化运行、配置、验证或桥接能力。
  - L12 `class EvidenceQualityResult`
  - L22 `class EvidenceQualityValidator`：Validate whether extracted answer material is tied to runtime input.
  - L35 `  def validate_result`
  - L65 `  def required_terms`
  - L77 `  def _known`
  - L94 `  def _aliases`
  - L118 `  def _material_text`
  - L136 `  def _looks_like_example_material`

- `ai_core/execution/evidence_satisfied_short_circuit.py`（104 行）：execution/evidence_satisfied_short_circuit.py 模块，围绕 evidence satisfied short circuit 提供结构化运行、配置、验证或桥接能力。
  - L6 `class EvidenceSatisfiedShortCircuit`：Decide whether collected evidence is already sufficient.
  - L16 `  def should_bypass_generated_execution`
  - L23 `  def _source_is_sufficient`
  - L51 `  def _sufficiency_result_passed`
  - L67 `  def _evidence_list_is_sufficient`
  - L81 `  def _has_answer_material`
  - L100 `  def _float`

- `ai_core/execution/execution_continuation_coordinator.py`（50 行）：execution/execution_continuation_coordinator.py 模块，围绕 execution continuation coordinator 提供结构化运行、配置、验证或桥接能力。
  - L6 `class ExecutionContinuationCoordinator`：Generic continuation policy after an execution candidate is rejected.
  - L24 `  def should_continue_with_evidence`
  - L38 `  def has_evidence_candidates`

- `ai_core/execution/execution_method_contract.py`（261 行）：execution/execution_method_contract.py 模块，围绕 execution method contract 提供结构化运行、配置、验证或桥接能力。
  - L8 `class ExecutionMethodContract`：Runtime execution method contract.
  - L28 `  def to_dict`
  - L36 `class ExecutionMethodProposalEngine`：Builds generic execution method proposals.
  - L78 `  def propose`
  - L127 `  def _explicit_proposals`
  - L144 `  def _strategy_values`
  - L150 `  def _dedupe`
  - L161 `class ExecutionMethodResolver`：Deterministically resolves a method from proposals and runtime policy.
  - L174 `  def resolve`
  - L213 `  def _merge_policy`
  - L226 `  def _input_schema`
  - L238 `  def _output_schema`
  - L249 `  def _cost`
  - L256 `  def _latency`

- `ai_core/execution/generated_result_verifier.py`（141 行）：execution/generated_result_verifier.py 模块，围绕 generated result verifier 提供结构化运行、配置、验证或桥接能力。
  - L6 `class GeneratedResultVerifier`：Validates that generated execution output is backed by runtime evidence.
  - L24 `  def verify`
  - L49 `  def enforce`
  - L73 `  def _has_positive_execution_claims`
  - L89 `  def _has_source_reference`
  - L102 `  def _non_empty_reference`
  - L119 `  def _has_quality_confirmation`
  - L137 `  def _passed`
  - L140 `  def _failed`

- `ai_core/execution/parameter_resolution.py`（128 行）：execution/parameter_resolution.py 模块，围绕 parameter resolution 提供结构化运行、配置、验证或桥接能力。
  - L12 `class PreflightResolutionContext`：Typed result for pre-execution requirement resolution.
  - L29 `  def requires_input`
  - L32 `  def to_analysis`
  - L43 `class ParameterResolutionPipeline`：Resolve pre-execution requirements without flattening all context.
  - L52 `  def build_context`
  - L83 `  def _append_missing_field`
  - L88 `  def _normalize_field`
  - L106 `  def _dedupe_fields`
  - L120 `  def field_key`
  - L127 `  def _clean_mapping`

- `ai_core/execution/provider_reliability.py`（34 行）：execution/provider_reliability.py 模块，围绕 provider reliability 提供结构化运行、配置、验证或桥接能力。
  - L12 `class ProviderReliabilityTracker`：Record lightweight provider reliability observations.
  - L18 `  def __init__`
  - L22 `  def record_attempt`

- `ai_core/execution/result_classifier.py`（72 行）：execution/result_classifier.py 模块，围绕 result classifier 提供结构化运行、配置、验证或桥接能力。
  - L6 `class ResultClassifier`：Classify generic runtime execution results for retry/fallback routing.
  - L37 `  def classify`
  - L60 `  def _message`

- `ai_core/execution/runtime_strategy_memory.py`（39 行）：execution/runtime_strategy_memory.py 模块，围绕 runtime strategy memory 提供结构化运行、配置、验证或桥接能力。
  - L11 `class RuntimeStrategyMemory`：Append-only memory for successful runtime execution strategies.
  - L18 `  def __init__`
  - L22 `  def record_success`

- `ai_core/execution/state_consistency_validator.py`（94 行）：execution/state_consistency_validator.py 模块，围绕 state consistency validator 提供结构化运行、配置、验证或桥接能力。
  - L7 `class ExecutionStateConsistencyValidator`：Validate and repair generic execution-state inconsistencies.
  - L15 `  def repair_step`
  - L44 `  def should_request_human_information`
  - L55 `  def should_request_confirmation`
  - L58 `  def missing_fields`
  - L80 `  def requires_confirmation`
  - L89 `  def _has_fields`

- `ai_core/executors/__init__.py`（0 行）：executors/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/executors/executor_registry.py`（14 行）：executors/executor_registry.py 模块，围绕 executor registry 提供结构化运行、配置、验证或桥接能力。
  - L10 `class ExecutorRegistry`
  - L11 `  def __init__`
  - L12 `  def get`

- `ai_core/executors/generic_input_parsing_executor.py`（137 行）：executors/generic_input_parsing_executor.py 模块，围绕 generic input parsing executor 提供结构化运行、配置、验证或桥接能力。
  - L14 `class GenericInputParsingExecutor`：Deterministic first-stage parser.
  - L31 `  def __init__`
  - L36 `  async def execute`
  - L59 `  def _try_parse_json`
  - L72 `  def _extract_text_fields`
  - L84 `  def _build_parsed_entities`
  - L103 `  def _extract_constraints`
  - L113 `  def _extract_temporal_expressions`
  - L132 `  def _detect_language`

- `ai_core/executors/human_review_executor.py`（3 行）：executors/human_review_executor.py 模块，围绕 human review executor 提供结构化运行、配置、验证或桥接能力。
  - L1 `class HumanReviewExecutor`
  - L2 `  async def execute`

- `ai_core/executors/llm_json_executor.py`（1208 行）：executors/llm_json_executor.py 模块，围绕 llm json executor 提供结构化运行、配置、验证或桥接能力。
  - L26 `class LLMJsonExecutor`：Runtime-configured LLM JSON executor.
  - L33 `  def __init__`
  - L54 `  async def execute`
  - L591 `  def _postprocess_stage_result`
  - L603 `  def _ensure_main_workflow_only`：Normalize main workflow without final execution action selection.
  - L648 `  def _ensure_agent_action_plan`：Normalize planner-LLM action decisions into locked executable steps.
  - L671 `  def _merge_detected_structural_entities`：Merge structurally detected entities without domain assumptions.
  - L723 `  def _ensure_input_carry_forward`
  - L745 `  def _ensure_intent_carry_forward`
  - L761 `  def _action_type_from_text`：Return only an explicit fixed action type.
  - L772 `  def _execution_decision_from_plan`
  - L794 `  def _selected_action_type`
  - L807 `  def _method_from_action_type`
  - L810 `  def _steps_from_execution_plan_action`
  - L846 `  def _ensure_executable_workflow`
  - L858 `  def _generic_locked_step_from_state`
  - L933 `  def _normalize_generated_step`
  - L970 `  def _build_agent_graph`
  - L984 `  def _generic_capability_from_state`
  - L993 `  def _recover_stage_result_after_provider_error`：Generic last-resort recovery for local JSON stage failures.
  - L1012 `  def _deterministic_intent_for_clear_runtime_reference`：Resolve unambiguous uploaded-artifact requests without a heavy JSON LLM.
  - L1045 `  def _recover_intent_recognition`
  - L1071 `  def _recover_input_parsing`
  - L1100 `  def _recover_main_workflow_planning`
  - L1117 `  def _recover_workflow_planning`
  - L1172 `  def _recover_agent_action_planning`：Recover action selection from already-normalized upstream contracts.
  - L1187 `  def _loads_json_obj`
  - L1194 `  def _build_runtime_context`：Build generic runtime context for prompts.

- `ai_core/executors/mcp_call_executor.py`（3 行）：executors/mcp_call_executor.py 模块，围绕 mcp call executor 提供结构化运行、配置、验证或桥接能力。
  - L1 `class MCPCallExecutor`
  - L2 `  async def execute`

- `ai_core/executors/output_executor.py`（361 行）：executors/output_executor.py 模块，围绕 output executor 提供结构化运行、配置、验证或桥接能力。
  - L14 `class OutputExecutor`：Builds a user-facing final response from generic runtime results.
  - L32 `  def __init__`
  - L40 `  async def execute`
  - L53 `  async def _build`
  - L161 `  def _is_public_answer_text`
  - L172 `  def _answer_material_from_execution_steps`：Extract public generated answer material from execution results.
  - L224 `  def _save_verified_answer_to_knowledge`
  - L238 `  def _ui_requests_from_blocked_steps`
  - L257 `  def _optional_upgrade_request`
  - L283 `  def _trust_summary`
  - L322 `  def _format_data_result`
  - L325 `  def _waiting_message`
  - L342 `  def _summarize_tool_result`

- `ai_core/executors/python_plugin_executor.py`（6 行）：executors/python_plugin_executor.py 模块，围绕 python plugin executor 提供结构化运行、配置、验证或桥接能力。
  - L2 `class PythonPluginExecutor`
  - L3 `  async def execute`

- `ai_core/executors/static_transform_executor.py`（816 行）：executors/static_transform_executor.py 模块，围绕 static transform executor 提供结构化运行、配置、验证或桥接能力。
  - L16 `class StaticTransformExecutor`：Deterministic stage executor for non-LLM pipeline layers.
  - L27 `  def __init__`
  - L32 `  async def execute`
  - L49 `  def _requirement_completion`
  - L74 `  def _context_awareness`
  - L101 `  def _locked_action_plan`
  - L118 `  def _promote_deep_action_plan`
  - L153 `  def _iter_nested_dicts`
  - L164 `  def _execution_preparation`
  - L187 `  def _pre_execution_validation`
  - L245 `  def _result_verification`
  - L281 `  def _feedback_repair`
  - L302 `  def _generic_record`
  - L307 `  def _reference_has_placeholder`
  - L328 `  def _reference_requires_credential`：Detect credential placeholders without hard-coding any provider or domain.
  - L352 `  def _filter_credential_required_references`
  - L364 `  def _filter_preparable_references`
  - L376 `  def _prepared_step`
  - L512 `  def _extract_execution_references`：Collect generic external references selected during action planning.
  - L595 `  def _prepared_resource_ok`
  - L620 `  def _prepared_uploaded_artifact_ok`
  - L631 `  def _prepared_credential_required`
  - L648 `  def _prepared_credential_request`
  - L669 `  def _stage_payload`
  - L683 `  def _merge_known`
  - L701 `  def _known_parameter_candidates`
  - L722 `  def _collect_missing`
  - L749 `  def _allows_research_to_resolve_missing`
  - L759 `  def _action_type_for_method`
  - L765 `  def _execution_method`
  - L791 `  def _write_runtime_artifact`
  - L799 `  def _validate_if_possible`
  - L809 `  def _results`
  - L812 `  def _first_non_empty`

- `ai_core/executors/template_engine.py`（8 行）：executors/template_engine.py 模块，围绕 template engine 提供结构化运行、配置、验证或桥接能力。
  - L2 `class TemplateEngine`
  - L3 `  def render`

- `ai_core/executors/tool_call_executor.py`（5440 行）：executors/tool_call_executor.py 模块，围绕 tool call executor 提供结构化运行、配置、验证或桥接能力。
  - L68 `class ToolCallExecutor`：Generic tool-call executor.
  - L78 `  def __init__`
  - L125 `  async def execute`
  - L140 `  async def run`
  - L1382 `  def _locked_step_method`
  - L1404 `  def _runtime_native_allowed_for_locked_step`
  - L1416 `  def _force_method_contract`
  - L1432 `  def _prepared_resource_for_step`
  - L1443 `  def _selected_prepared_external_url`
  - L1462 `  async def _execute_prepared_external_resource`：Execute the exact external URL approved by execution_preparation.
  - L1538 `  def _interaction_requests_from_validation`：Extract UI/runtime input requests from validation output.
  - L1571 `  async def _execute_uploaded_artifact`
  - L1641 `  def _normalize_uploaded_artifact_call_values`
  - L1652 `  def _run_uploaded_python_artifact`
  - L1681 `  def _prepared_resource_allows_method`
  - L1713 `  def _enforce_intent_execution_contract`：Final runtime guard between planning and execution.
  - L1785 `  def _step_has_runtime_native_temporal_contract`：Detect generic runtime-native temporal observations.
  - L1814 `  def _contract_allows_external_fallback`
  - L1818 `  async def _try_autonomous_codegen_and_execute`：Generate, sandbox-verify, enable, and execute a pending module.
  - L1893 `  def _codegen_request_path`
  - L1918 `  async def _try_runtime_generated_tool_execution`：Generate, persist, map, and execute a runtime source artifact.
  - L2023 `  async def _generate_runtime_source_code`
  - L2096 `  def _runtime_generated_source_fallback`
  - L2108 `  def _source_external_imports`：Return non-stdlib top-level imports used by generated source.
  - L2142 `  def _missing_module_from_stderr`
  - L2152 `  def _runtime_install_allowed`
  - L2158 `  def _prepare_python_dependencies_for_source`：Install missing external Python modules for a generated script.
  - L2176 `  def _install_python_module`
  - L2205 `  def _write_generated_source_artifact`
  - L2220 `  def _normalize_generated_process_output`
  - L2245 `  def _execute_python_artifact`
  - L2310 `  def _runtime_agent_identity`
  - L2323 `  def _mapping_keys_for_identity`
  - L2334 `  def _generated_artifact_map_path`
  - L2338 `  def _load_generated_artifact_map`
  - L2350 `  def _lookup_generated_artifact`
  - L2361 `  def _record_generated_artifact_mapping`
  - L2374 `  def _safe_artifact_name`
  - L2380 `  def _executor_generation_instruction`：Build a generic final-deliverable instruction for content generation.
  - L2408 `  def _generation_output_contract`：Return a compact, domain-neutral output contract for generation.
  - L2428 `  def _runtime_generation_public_brief`：Return the confirmed user-facing brief for model generation.
  - L2489 `  def _render_generation_brief_payload`
  - L2502 `  async def _try_model_generation_execution`：Generate original output with the configured model.
  - L2683 `  def _generated_answer_quality`：Generic guard against returning planning/request summaries as final content.
  - L2794 `  def _render_confirmed_parameters_for_generation`：Render confirmed runtime parameters as generic executor constraints.
  - L2810 `  async def _try_local_knowledge_execution`
  - L2902 `  def _required_terms_from_tool_input`
  - L2924 `  def _value_aliases`
  - L2941 `  async def _execute_registered_module`：Load and execute an already-registered runtime module by capability.
  - L3034 `  def _normalize_runtime_execution_result`：Normalize runtime tool/module outputs into a generic success/error contract.
  - L3090 `  def _is_success_result`
  - L3093 `  def _result_error_message`
  - L3106 `  def _build_tool_input`：Build a generic, schema-friendly tool input object.
  - L3180 `  def _execution_strategy`：Return a normalized, domain-neutral execution strategy.
  - L3206 `  def _strategy_prefers`
  - L3217 `  async def _try_strategy_web_evidence_execution`：Execute the generic web-evidence branch before generated components.
  - L3392 `  async def _try_generate_executable_module`
  - L3518 `  async def _try_generate_executable_tool`：Ask the runtime intelligence layer to generate a reusable tool artifact.
  - L3784 `  async def _try_generate_web_extraction_fallback_tool`：Generate a generic extraction fallback when a JSON/API tool fails.
  - L3918 `  async def _build_and_verify_generic_web_extract_tool`：Build a deterministic generic HTML/text extraction tool and verify it.
  - L3986 `  def _select_generic_web_candidate`
  - L4014 `  def _build_generic_web_extract_artifact`
  - L4042 `  def _candidate_evidence_text`
  - L4059 `  async def _try_repair_executable_tool`：Repair a generated runtime tool once when execution fails.
  - L4164 `  async def _try_answer_evidence_fallback_after_module_failure`：Try direct answer evidence after a registered module fails.
  - L4258 `  async def _try_direct_evidence_execution_from_discovery`：Execute the evidence pipeline before generated components.
  - L4475 `  async def _fetch_selected_pages_for_evidence`
  - L4550 `  def _runtime_known_parameters`：Collect runtime parameters without dropping arrays or normalized objects.
  - L4598 `  def _compact_runtime_value`
  - L4614 `  def _evidence_url`
  - L4629 `  def _compact_sufficiency_for_event`
  - L4647 `  def _compact_direct_result_for_event`
  - L4660 `  async def _try_multi_candidate_fallback_execution`：Parallel candidate verification and result synthesis.
  - L4869 `  async def _attempt_runtime_candidate`
  - L4996 `  def _credential_skip_attempt`
  - L5005 `  def _compact_candidate_for_interaction`
  - L5029 `  def _artifact_has_valid_contract_shape`
  - L5038 `  def _enforce_evidence_quality`：Convert low-quality success payloads into retryable structured errors.
  - L5068 `  def _candidate_requires_credential`
  - L5088 `  def _compact_attempts`：Return non-recursive attempt summaries safe for result/provenance output.
  - L5121 `  def _requires_confirmation`
  - L5148 `  def _has_executable_implementation`
  - L5164 `  def _public_tool_spec`
  - L5176 `  def _execute_runtime_observation_code`：Run a tiny generated local program for generic runtime observation.
  - L5205 `  def _try_runtime_native_observation`：Execute a generic native-observation step when the runtime plan asks for it.
  - L5268 `  def _step_requests_runtime_native`
  - L5283 `  def _generic_contract_text`
  - L5295 `  def _repair_single_step_before_execution`：Last-chance generic repair for one runtime-generated step.
  - L5314 `  def _capability_name`
  - L5324 `  def _normalize_human_interaction`
  - L5350 `  def _missing_fields`
  - L5353 `  def _build_credential_interaction_payload`：Build an English UI contract for optional credential input.
  - L5414 `  def _execution_budget_exhausted`
  - L5421 `  def _overall_status`

- `ai_core/executors/workflow_call_executor.py`（3 行）：executors/workflow_call_executor.py 模块，围绕 workflow call executor 提供结构化运行、配置、验证或桥接能力。
  - L1 `class WorkflowCallExecutor`
  - L2 `  async def execute`

- `ai_core/feedback_repair/__init__.py`（18 行）：Compatibility namespace for the generic feedback-repair layer.
  - 无显式顶层类/函数。

- `ai_core/graph/__init__.py`（12 行）：graph/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/graph/edge_scheduler.py`（129 行）：graph/edge_scheduler.py 模块，围绕 edge scheduler 提供结构化运行、配置、验证或桥接能力。
  - L8 `class SchedulerState`
  - L19 `class EdgeDrivenScheduler`：Schedules executable nodes by dataflow edges.
  - L27 `  def create_state`
  - L33 `  def ready_nodes`
  - L46 `  def mark_started`
  - L53 `  def bind_output`
  - L75 `  def mark_failed`
  - L96 `  def is_terminal`
  - L99 `  def summary`
  - L114 `  def upstream_ids`
  - L117 `  def downstream_ids`
  - L120 `  def _nodes`
  - L124 `  def _edges`
  - L128 `  def _node_id`

- `ai_core/graph/graph_contract.py`（133 行）：graph/graph_contract.py 模块，围绕 graph contract 提供结构化运行、配置、验证或桥接能力。
  - L8 `class GraphPartition`：Domain-neutral graph partitions for runtime coordination.
  - L22 `class GraphBoundaryNormalizer`：Separates planning metadata from executable runtime graph.
  - L50 `  def normalize`
  - L110 `  def _is_executable`
  - L119 `  def _node_id`
  - L123 `  def _normalize_edge`
  - L132 `  def _as_list`

- `ai_core/graph/graph_self_check.py`（89 行）：graph/graph_self_check.py 模块，围绕 graph self check 提供结构化运行、配置、验证或桥接能力。
  - L6 `class GraphSelfCheck`：Validates graph completion using structural evidence, not status alone.
  - L11 `  def validate`
  - L57 `  def _repair_plan`
  - L75 `  def _request_constraints`
  - L81 `  def _final_text`

- `ai_core/graph/graph_visualization.py`（536 行）：graph/graph_visualization.py 模块，围绕 graph visualization 提供结构化运行、配置、验证或桥接能力。
  - L9 `class GraphVisualState`：UI-ready graph state for runtime visualization.
  - L22 `class GraphVisualStateBuilder`：Builds a domain-neutral DAG snapshot for UI rendering.
  - L35 `  def from_partition`
  - L53 `  def from_snapshot`
  - L62 `  def from_graph`
  - L103 `  def to_dict`
  - L116 `  def _extract_nodes`
  - L134 `  def _task_as_node`
  - L145 `  def _capability_projection`：Project declared runtime capabilities as graph nodes.
  - L200 `  def _extract_edges`
  - L220 `  def _visual_node`
  - L234 `  def _display_label`：Return a short UI label without leaking long instruction text.
  - L258 `  def _compact_label`
  - L267 `  def _visual_edge`
  - L289 `  def _status_by_node`：Resolve node status from graph, scheduler summary, and live run payload.
  - L368 `  def _node_ids_by_participant_index`
  - L375 `  def _event_target_node_ids`
  - L418 `  def _topological_lanes`
  - L440 `  def _overall_status`
  - L454 `  def _events`
  - L465 `  def _repair_plan`
  - L471 `  def _summary_from_run`
  - L478 `  def _self_check_from_run`
  - L485 `  def _select_graph`
  - L493 `  def _select_run`：Select only the run that belongs to the selected graph.
  - L511 `  def _graph_id`
  - L514 `  def _node_id`
  - L517 `  def _normalize_status`
  - L535 `  def _as_list`

- `ai_core/input_parsing/__init__.py`（5 行）：Generic input parsing utilities.
  - 无显式顶层类/函数。

- `ai_core/input_parsing/structured_entity_extractor.py`（170 行）：input_parsing/structured_entity_extractor.py 模块，围绕 structured entity extractor 提供结构化运行、配置、验证或桥接能力。
  - L9 `class ExtractedEntity`
  - L16 `  def to_dict`
  - L25 `class StructuredEntityExtractor`：Extract generic structural entities from raw user material.
  - L50 `  def extract`
  - L72 `  def first_electronic_address`
  - L76 `  def is_electronic_address`
  - L81 `  def extract_electronic_address_values`
  - L93 `  def _extract_electronic_addresses`
  - L99 `  def _extract_uris`
  - L105 `  def duration_to_seconds`
  - L123 `  def extract_duration_seconds_values`
  - L135 `  def _extract_durations`
  - L141 `  def _dedupe`
  - L152 `  def _flatten_text`

- `ai_core/interaction/__init__.py`（0 行）：interaction/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/interaction/conversation_core_runtime.py`（1497 行）：interaction/conversation_core_runtime.py 模块，围绕 conversation core runtime 提供结构化运行、配置、验证或桥接能力。
  - L22 `class ConversationCoreRuntime`：Generic AI-core conversation pipeline for non-delegated messages.
  - L31 `  def __init__`
  - L41 `  async def run`
  - L132 `  async def _input_parsing`：Deterministic, compact input normalization.
  - L161 `  async def _intent_recognition`
  - L316 `  def _context_awareness`
  - L332 `  def _build_need_capability_payload`：Build the ai_core -> auxiliary_brain capability contract.
  - L402 `  async def _workflow_planning`
  - L593 `  async def _execution`
  - L802 `  async def _output`
  - L867 `  def _capability_gap_resolution_artifact`：Create a generic, non-executing capability implementation record.
  - L913 `  def _capability_gap_answer_material`
  - L975 `  def _implementation_requested`
  - L987 `  def _external_retrieval_failure_material`
  - L1006 `  def _selected_step`
  - L1021 `  def _result_verification`
  - L1050 `  async def _web_answer_material`：Create concise user-facing material from web evidence.
  - L1132 `  def _compact_web_evidence_material`：Fallback material that is readable without model synthesis.
  - L1169 `  def _query_terms`
  - L1183 `  def _generic_external_signal`
  - L1186 `  def _external_information_signals`
  - L1204 `  def _generic_capability_gap_signal`
  - L1231 `  def _capability_gap_query`：Build a compact evidence query for capability acquisition.
  - L1260 `  async def _direct_answer`
  - L1293 `  def _stage_llm_limits`：Small per-stage budgets for weak local machines.
  - L1320 `  def _compact_stage_payload`
  - L1346 `  def _compact_value`
  - L1367 `  async def _json_stage`
  - L1418 `  def _persist_conversation_turn`
  - L1444 `  def _compact_summary_text`
  - L1448 `  def _write_stage_trace`
  - L1469 `  def _event`
  - L1476 `  def _write_trace`
  - L1485 `  def _guess_language`
  - L1488 `  def _safe_fallback_answer`

- `ai_core/interaction/interaction_contract_generator.py`（319 行）：interaction/interaction_contract_generator.py 模块，围绕 interaction contract generator 提供结构化运行、配置、验证或桥接能力。
  - L11 `class InteractionContractGenerator`：Build frontend interaction contracts from runtime-generated metadata.
  - L24 `  def __init__`
  - L27 `  def build_request`
  - L86 `  def _runtime_contract_from_interaction`：Return a runtime/LLM-generated interaction contract when available.
  - L100 `  def _collect_raw_fields`：Collect raw required-field metadata without interpreting meaning.
  - L118 `  def _dedupe_raw_fields`
  - L126 `  def _normalize_field`：Normalize field metadata without domain-specific inference.
  - L172 `  def _attach_merge_metadata`：Attach generic merge metadata for resume.
  - L220 `  def _field_mapping`
  - L234 `  def _unique_texts`
  - L247 `  def _field_name`
  - L252 `  def _first_text`
  - L259 `  def _text_or`
  - L262 `  def _safe_field_id`
  - L267 `  def _generic_label`
  - L272 `  def _generic_question`
  - L276 `  def _generic_placeholder`
  - L280 `  def _generic_description`
  - L286 `  def _write_generation_request`

- `ai_core/interaction/interaction_contract_validator.py`（20 行）：interaction/interaction_contract_validator.py 模块，围绕 interaction contract validator 提供结构化运行、配置、验证或桥接能力。
  - L6 `class InteractionContractValidator`：Validate frontend interaction contracts without domain knowledge.
  - L9 `  def is_actionable`
  - L19 `  def validate_or_none`

- `ai_core/interaction/natural_conversation.py`（141 行）：interaction/natural_conversation.py 模块，围绕 natural conversation 提供结构化运行、配置、验证或桥接能力。
  - L14 `class NaturalConversationService`：Natural conversation path for Agent Studio.
  - L22 `  def __init__`
  - L28 `  def needs_core_conversation_pipeline`：Return whether this message should bypass feedback routing and enter the generic conversation pipeline.
  - L43 `  async def reply`
  - L61 `  def _payload`
  - L75 `  async def _model_answer`
  - L132 `  def _safe_fallback_answer`

- `ai_core/interaction/question_generator.py`（25 行）：interaction/question_generator.py 模块，围绕 question generator 提供结构化运行、配置、验证或桥接能力。
  - L8 `class QuestionGenerator`：Compatibility wrapper for the v39 interaction contract generator.
  - L11 `  def __init__`
  - L14 `  def build_request`

- `ai_core/knowledge/__init__.py`（0 行）：knowledge/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/knowledge/document_processor.py`（270 行）：knowledge/document_processor.py 模块，围绕 document processor 提供结构化运行、配置、验证或桥接能力。
  - L22 `class ExtractedDocument`
  - L28 `class DocumentTextExtractor`：Domain-neutral file text extraction for runtime knowledge ingestion.
  - L31 `  def supported_extensions`
  - L34 `  def extract`
  - L74 `  def _extract_csv`
  - L81 `  def _extract_json`
  - L89 `  def _extract_html`
  - L95 `  def _extract_pdf`
  - L113 `  def _extract_docx`
  - L131 `  def _extract_xlsx`
  - L147 `  def _extract_pptx`
  - L167 `  def _normalize_text`
  - L174 `class DocumentChunker`：Generic chunking independent of document domain.
  - L177 `  def chunk`
  - L224 `  def _make_chunk`
  - L237 `  def _link_chunks`
  - L242 `  def _split_large_unit`
  - L256 `  def _token_estimate`
  - L263 `  def _paragraph_units`

- `ai_core/knowledge/embedding_index.py`（204 行）：knowledge/embedding_index.py 模块，围绕 embedding index 提供结构化运行、配置、验证或桥接能力。
  - L14 `class EmbeddingRecord`
  - L22 `class LocalTextEmbedder`：Deterministic local text embedder for offline runtime retrieval.
  - L30 `  def __init__`
  - L34 `  def embed`
  - L47 `  def _features`
  - L67 `class LocalVectorIndex`：JSONL-backed vector index with deterministic scoring.
  - L76 `  def __init__`
  - L87 `  def upsert_texts`
  - L113 `  def search`
  - L141 `  def stats`
  - L151 `  def _write_embedding_cache`
  - L156 `  def _write_manifest`
  - L172 `  def _read_vector_rows`
  - L185 `  def _matches_filters`
  - L193 `  def _lexical_overlap`
  - L201 `  def _cosine`

- `ai_core/knowledge/knowledge_service.py`（799 行）：knowledge/knowledge_service.py 模块，围绕 knowledge service 提供结构化运行、配置、验证或桥接能力。
  - L19 `class KnowledgeService`：Local runtime knowledge service with chunk and embedding lifecycles.
  - L53 `  def __init__`
  - L56 `  def ingest_file`
  - L180 `  def list_documents`
  - L190 `  def search_documents`
  - L217 `  def rag_query`
  - L249 `  async def rag_answer`：Retrieve local evidence and synthesize a grounded answer.
  - L298 `  async def _synthesize_grounded_answer`
  - L360 `  def _prepare_evidence_for_synthesis`
  - L376 `  def _render_synthesis_prompt`
  - L401 `  def _clean_response_profile`：Return generic, user-facing synthesis instructions.
  - L432 `  def search`
  - L467 `  def best_covered`
  - L481 `  def best_hint`
  - L488 `  def classify_record`
  - L515 `  def save_answer_result`
  - L530 `  def answer_from_knowledge`
  - L540 `  def status`
  - L574 `  def save_success_case`
  - L579 `  def _keyword_search_documents`
  - L602 `  def _knowledge_files`
  - L613 `  def _document_root`
  - L616 `  def _vector_index`
  - L619 `  def _knowledge_base_ids`
  - L626 `  def _processing_state`
  - L631 `  def _update_registry`
  - L648 `  def _safe_id`
  - L653 `  def _append_jsonl`
  - L660 `  def _write_jsonl`
  - L667 `  def _write_json`
  - L671 `  def _compact_excerpt`
  - L677 `  def _read_jsonl`
  - L694 `  def _score`
  - L706 `  def _coverage`
  - L722 `  def _terms`
  - L725 `  def _flatten_text`
  - L746 `  def _memory_type`
  - L756 `  def _looks_like_runtime_structure`
  - L781 `  def _has_user_answer_payload`

- `ai_core/llm/__init__.py`（0 行）：llm/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/llm/escalation_policy.py`（91 行）：llm/escalation_policy.py 模块，围绕 escalation policy 提供结构化运行、配置、验证或桥接能力。
  - L6 `class ModelEscalationPolicy`：Config-driven escalation policy.
  - L29 `  def should_escalate`
  - L79 `  def preferred_route`

- `ai_core/llm/model_capability_matcher.py`（96 行）：llm/model_capability_matcher.py 模块，围绕 model capability matcher 提供结构化运行、配置、验证或桥接能力。
  - L6 `class ModelCapabilityMatcher`：Rank provider routes using runtime model tags/capabilities.
  - L35 `  def rank_route`
  - L52 `  def _required_capabilities`
  - L60 `  def _score_provider`

- `ai_core/llm/model_response_cache.py`（43 行）：llm/model_response_cache.py 模块，围绕 model response cache 提供结构化运行、配置、验证或桥接能力。
  - L11 `class ModelResponseCache`：Generic model response cache for any provider/model/protocol.
  - L14 `  def __init__`
  - L18 `  def build_key`
  - L32 `  def get`
  - L41 `  def set`

- `ai_core/llm/prompt_io_recorder.py`（45 行）：llm/prompt_io_recorder.py 模块，围绕 prompt io recorder 提供结构化运行、配置、验证或桥接能力。
  - L12 `class PromptIORecorder`：Persist LLM stage prompt/response material for runtime debugging.
  - L20 `  def __init__`
  - L23 `  def record`
  - L34 `  def _safe_name`
  - L38 `  def _json_safe`

- `ai_core/llm/provider_command_runner.py`（66 行）：llm/provider_command_runner.py 模块，围绕 provider command runner 提供结构化运行、配置、验证或桥接能力。
  - L6 `class ProviderCommandRunner`
  - L7 `  async def run`

- `ai_core/llm/provider_handler_registry.py`（28 行）：llm/provider_handler_registry.py 模块，围绕 provider handler registry 提供结构化运行、配置、验证或桥接能力。
  - L5 `class ProviderHandlerRegistry`：Protocol-driven provider registry.
  - L13 `  def __init__`
  - L22 `  def get`

- `ai_core/llm/provider_handlers/__init__.py`（0 行）：provider_handlers/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/llm/provider_handlers/base.py`（47 行）：provider_handlers/base.py 模块，围绕 base 提供结构化运行、配置、验证或桥接能力。
  - L5 `class ProviderUnavailableError`
  - L10 `class ProviderCommandResult`
  - L17 `  def stdout_text`
  - L21 `  def stderr_text`
  - L24 `  def summary`
  - L33 `class ProviderHandler`
  - L36 `  async def generate_json`

- `ai_core/llm/provider_handlers/ollama_handler.py`（255 行）：provider_handlers/ollama_handler.py 模块，围绕 ollama handler 提供结构化运行、配置、验证或桥接能力。
  - L10 `class OllamaProviderHandler`
  - L13 `  def __init__`
  - L17 `  async def generate_json`
  - L52 `  def _format_command`
  - L58 `  async def _call_chat_endpoint`
  - L89 `  async def _call_generate_endpoint`
  - L117 `  async def _ensure_service`
  - L165 `  async def _try_tags`
  - L174 `  async def _emit_health_ok`
  - L183 `  async def _ensure_model_with_fallbacks`
  - L248 `  def _model_exists`

- `ai_core/llm/provider_handlers/universal_model_handler.py`（926 行）：provider_handlers/universal_model_handler.py 模块，围绕 universal model handler 提供结构化运行、配置、验证或桥接能力。
  - L28 `class UniversalModelProviderHandler`：Protocol-driven model provider handler.
  - L44 `  def __init__`
  - L51 `  async def generate_json`
  - L76 `  def _fit_payload_to_budget`
  - L100 `  def _is_local_openai_compatible`
  - L104 `  async def _start_openai_compatible_service`
  - L134 `  def _missing_python_module_for_command`
  - L147 `  async def _wait_openai_compatible_ready`
  - L163 `  async def _call_chat_completions`
  - L266 `  async def _ensure_ollama_model_ready`：Ensure an Ollama model is available using runtime config.
  - L357 `  async def _ollama_tags`
  - L366 `  def _ollama_model_exists`
  - L374 `  def _format_provider_command`
  - L380 `  async def _start_ollama_service`
  - L395 `  async def _pull_ollama_model`
  - L443 `  def _safe_model_file_stem`
  - L446 `  def _ollama_gguf_entry`
  - L460 `  def _ollama_gguf_entry_has_configured_source`
  - L470 `  async def _import_ollama_model_from_gguf`：Import a missing Ollama model from a runtime-configured GGUF file.
  - L556 `  async def _resolve_ollama_gguf_path`
  - L597 `  def _download_file_sync`
  - L605 `  def _verify_file_sha256`
  - L612 `  def _render_ollama_modelfile`
  - L630 `  async def _call_ollama`
  - L732 `  async def _parse_or_retry_json`
  - L790 `  async def _retry_json_repair`
  - L891 `  def _apply_auth`
  - L907 `  def _log_usage`
  - L922 `def json_dumps_compact`

- `ai_core/llm/provider_handlers/utils.py`（138 行）：provider_handlers/utils.py 模块，围绕 utils 提供结构化运行、配置、验证或桥接能力。
  - L9 `class LLMJSONParseError`：Raised when a model response cannot be parsed as JSON.
  - L17 `  def __init__`
  - L23 `def build_system_prompt`
  - L35 `def parse_json_content`
  - L60 `def _strip_wrappers`
  - L70 `def _candidate_json_strings`
  - L91 `def _extract_first_balanced_object`
  - L95 `def _extract_first_balanced_array`
  - L99 `def _extract_balanced`
  - L128 `def _light_repair`

- `ai_core/llm/provider_installer.py`（77 行）：llm/provider_installer.py 模块，围绕 provider installer 提供结构化运行、配置、验证或桥接能力。
  - L7 `class ProviderInstaller`
  - L8 `  def __init__`
  - L12 `  async def ensure_binary`

- `ai_core/llm/provider_router.py`（454 行）：llm/provider_router.py 模块，围绕 provider router 提供结构化运行、配置、验证或桥接能力。
  - L17 `class ProviderRouter`：Generic LLM provider router.
  - L24 `  def __init__`
  - L37 `  def _canonical_stage_node`
  - L50 `  def _apply_stage_prompt_guard`：Apply generic per-stage LLM budgets before provider routing.
  - L86 `  def _compact_rendered_prompt`：Shrink LLM prompts without relying on business vocabulary.
  - L128 `  def _config`
  - L133 `  def _apply_local_model_switch`：Apply the canonical runtime execution switch.
  - L144 `  def _apply_stage_provider_overrides`：Apply generic stage-level request controls from runtime adapter.
  - L174 `  def _provider_is_local`
  - L177 `  def _apply_runtime_model_override`：Apply user-selected local model to generic local providers only.
  - L218 `  async def generate_json`
  - L430 `  async def _emit_missing_secret_interaction`

- `ai_core/llm/token_usage_logger.py`（26 行）：llm/token_usage_logger.py 模块，围绕 token usage logger 提供结构化运行、配置、验证或桥接能力。
  - L11 `class TokenUsageLogger`：Provider-neutral token/latency logger.
  - L14 `  def __init__`
  - L18 `  def log`

- `ai_core/media/__init__.py`（6 行）：Generic media capability services.
  - 无显式顶层类/函数。

- `ai_core/media/image_generation_service.py`（1219 行）：media/image_generation_service.py 模块，围绕 image generation service 提供结构化运行、配置、验证或桥接能力。
  - L25 `class ImageGenerationService`：Provider-routed image generation capability.
  - L34 `  def __init__`
  - L40 `  async def generate`
  - L80 `  def _provider_config`
  - L90 `  def _ensure_runtime_image_config`：Materialize a runtime-editable image capability config from the seed.
  - L106 `  def _image_seed_config`
  - L118 `  def _merge_provider_config`
  - L135 `  def _route`
  - L161 `  def _media_provider_allowed`
  - L170 `  def _rank_route_by_observations`：Reorder equivalent providers using runtime observations.
  - L195 `  def _provider_observations`
  - L225 `  def _provider_can_generate_image`
  - L231 `  def _attempt_record`
  - L243 `  def _setup_message`
  - L253 `  def _setup_actions`
  - L281 `  async def _call_provider`
  - L293 `  def _call_comfyui`
  - L319 `  def _runtime_settings`
  - L323 `  def _effective_generation_timeout`
  - L347 `  def _provider_temp_dir`
  - L352 `  def _ensure_comfyui_runtime`
  - L424 `  def _comfyui_runtime_integrity`
  - L433 `  def _repair_incomplete_runtime_root`
  - L455 `  def _comfy_logs_dir`
  - L460 `  def _comfy_bootstrap_log_path`
  - L463 `  def _comfy_named_log_path`
  - L466 `  def _append_text_log`
  - L477 `  def _log_comfy_bootstrap_event`
  - L494 `  def _tail_file`
  - L503 `  def _process_alive`
  - L512 `  def _resolve_runtime_root`
  - L518 `  def _runtime_python`
  - L533 `  def _venv_python_path`
  - L539 `  def _ensure_runtime_python`
  - L552 `  def _run_comfyui_preflight`：Validate the Python runtime before starting ComfyUI.
  - L653 `  def _repair_comfyui_preflight_failure`
  - L673 `  def _repair_torch_installation`
  - L714 `  def _install_runtime`
  - L788 `  def _should_force_comfyui_cpu`
  - L801 `  def _comfyui_startup_env`
  - L841 `  def _start_runtime_process`
  - L881 `  def _comfy_healthy`
  - L888 `  def _ensure_model_assets`
  - L916 `  def _asset_target`
  - L927 `  def _resolve_config_value`
  - L936 `  def _download_file`
  - L943 `  def _render_workflow`
  - L966 `  def _replace_placeholders`
  - L978 `  def _comfy_post_json`
  - L983 `  def _wait_comfy_history`
  - L997 `  def _extract_comfy_image`
  - L1023 `  def _call_python_function`
  - L1042 `  def _call_local_command`
  - L1060 `  def _call_http_json`
  - L1089 `  def _render_payload`
  - L1118 `  def _normalize_provider_result`
  - L1145 `  def _download_remote_image`
  - L1163 `  def _metrics_path`
  - L1168 `  def _record_execution_event`
  - L1189 `  def _persist_image`

- `ai_core/media/providers/__init__.py`（0 行）：providers/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/media/providers/generic_text_animation_provider.py`（366 行）：providers/generic_text_animation_provider.py 模块，围绕 generic text animation provider 提供结构化运行、配置、验证或桥接能力。
  - L25 `def generate_text_animation`：Generate a local animated preview artifact from text.
  - L101 `def _generate_with_pillow`
  - L137 `def _requested_frame_count`
  - L153 `def _effective_max_frames`
  - L168 `def _available_memory_gb`
  - L180 `def _inspect_gif_frame_count`
  - L189 `def _int_value`
  - L196 `def _font`
  - L209 `def _draw_grid`
  - L221 `def _draw_orbit_nodes`
  - L240 `def _analyze_prompt_visual_intent`：Convert text into generic visual instructions for the zero-config preview.
  - L267 `def _prompt_title`
  - L274 `def _camera_offset`
  - L280 `def _draw_task_graph_scene`
  - L301 `def _draw_agent_characters`
  - L333 `def _draw_routing_pulses`
  - L345 `def _draw_prompt_badge`
  - L359 `def _draw_center_panel`

- `ai_core/media/video_generation_service.py`（1078 行）：media/video_generation_service.py 模块，围绕 video generation service 提供结构化运行、配置、验证或桥接能力。
  - L25 `class VideoGenerationService`：Provider-routed video generation capability.
  - L36 `  async def generate`
  - L172 `  def _provider_config`
  - L182 `  def _ensure_runtime_video_config`
  - L198 `  def _video_seed_config`
  - L207 `  def _route`
  - L250 `  def _provider_can_generate_video`
  - L277 `  async def _call_provider_with_dependency_recovery`
  - L307 `  async def _call_provider`
  - L319 `  def _call_comfyui_video`
  - L345 `  def _extract_comfy_video`
  - L380 `  def _render_workflow`
  - L397 `  def _provider_with_video_workflow_values`
  - L419 `  def _bootstrap_video_workflow_template`：Resolve/download a ComfyUI video workflow template using runtime config.
  - L461 `  def _workflow_template_target_dir`
  - L468 `  def _discover_existing_workflow_template`
  - L496 `  def _download_workflow_template_from_config`
  - L527 `  def _clone_workflow_template_repo`
  - L549 `  def _ensure_model_assets`：Ensure model assets and custom nodes described by runtime manifest.
  - L585 `  def _load_video_model_dependency_manifest`
  - L634 `  def _normalize_manifest_asset`
  - L646 `  def _ensure_comfyui_custom_nodes`
  - L692 `  def _install_manifest_python_packages`
  - L708 `  def _asset_target`
  - L722 `  def _download_file`
  - L728 `  def _provider_secret`
  - L740 `  def _missing_secret_interaction`
  - L758 `  def _first_missing_secret_action`
  - L771 `  def _missing_endpoint_interaction`
  - L802 `  def _redact_url`
  - L805 `  def _call_local_command`
  - L823 `  def _call_http_json`
  - L852 `  def _normalize_provider_result`
  - L880 `  def _download_remote_video`
  - L898 `  def _effective_generation_timeout`
  - L916 `  def _setup_message`
  - L927 `  def _setup_actions`
  - L968 `  def _diagnostic_log_path`
  - L973 `  def _record_diagnostic_event`：Write traceable diagnostics for video generation failures.
  - L1002 `  def _attempt_record`
  - L1011 `  def _metrics_path`
  - L1016 `  def _record_execution_event`
  - L1037 `  def _persist_video`

- `ai_core/media/video_generation_setup_wizard.py`（211 行）：media/video_generation_setup_wizard.py 模块，围绕 video generation setup wizard 提供结构化运行、配置、验证或桥接能力。
  - L13 `class VideoGenerationSetupWizard`：Runtime setup wizard for video_generation providers.
  - L24 `  def __init__`
  - L30 `  def ensure_runtime_config`
  - L36 `  def interaction_request`
  - L113 `  def apply_inputs`
  - L161 `  def _first_text`
  - L171 `  def _apply_workflow_source`
  - L194 `  def _save_setup_sidecar`
  - L203 `  def _looks_like_url`
  - L206 `  def _looks_like_git_repo`
  - L210 `  def _redact`

- `ai_core/models/__init__.py`（1 行）：Generic runtime model management utilities.
  - 无显式顶层类/函数。

- `ai_core/models/model_benchmark.py`（91 行）：models/model_benchmark.py 模块，围绕 model benchmark 提供结构化运行、配置、验证或桥接能力。
  - L16 `class ModelBenchmarkResult`
  - L26 `class RuntimeModelBenchmark`：Run a minimal benchmark before model route registration.
  - L34 `  def __init__`
  - L38 `  def benchmark`
  - L80 `  def _bench_ollama`
  - L90 `  def _safe`

- `ai_core/models/model_downloader.py`（218 行）：models/model_downloader.py 模块，围绕 model downloader 提供结构化运行、配置、验证或桥接能力。
  - L20 `class ModelDownloadResult`
  - L32 `class RuntimeModelDownloader`：Download or prepare model candidates for benchmark.
  - L45 `  def __init__`
  - L50 `  def download`
  - L70 `  def _candidate_has_gguf`
  - L77 `  def _prepare_ollama_gguf`
  - L114 `  def _resolve_or_download_gguf`
  - L140 `  def _sha256_ok`
  - L147 `  def _download_ollama`
  - L171 `  def _download_huggingface`
  - L193 `  def _infer_runtime`
  - L199 `  def _safe`
  - L202 `  def _result`

- `ai_core/models/model_lifecycle.py`（79 行）：models/model_lifecycle.py 模块，围绕 model lifecycle 提供结构化运行、配置、验证或桥接能力。
  - L17 `class ModelLifecycleResult`
  - L29 `class RuntimeModelLifecycle`：Orchestrate model approval, download, benchmark, route registration, and knowledge recording.
  - L32 `  def __init__`
  - L41 `  def process_candidate`
  - L75 `  def _finish`

- `ai_core/models/model_route_registry.py`（103 行）：models/model_route_registry.py 模块，围绕 model route registry 提供结构化运行、配置、验证或桥接能力。
  - L14 `class ModelRouteRegistrationResult`
  - L24 `class RuntimeModelRouteRegistry`：Register benchmark-approved models into runtime model routes.
  - L31 `  def __init__`
  - L40 `  def register_after_benchmark`
  - L73 `  def _provider_name`
  - L76 `  def _provider_config`
  - L96 `  def _load_json`
  - L102 `  def _safe`

- `ai_core/modules/__init__.py`（0 行）：modules/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/modules/autonomous_codegen_executor.py`（337 行）：modules/autonomous_codegen_executor.py 模块，围绕 autonomous codegen executor 提供结构化运行、配置、验证或桥接能力。
  - L17 `class AutonomousCodegenExecutor`：Autonomous runtime code-generation executor.
  - L30 `  def __init__`
  - L40 `  async def execute_request_file`
  - L66 `  async def execute_request`
  - L197 `  async def execute_latest_pending_for_capability`
  - L217 `  def find_pending_requests`
  - L233 `  def _to_generation_request`
  - L266 `  def _default_test_input`
  - L281 `  def _source_step`
  - L286 `  def _uses_network`
  - L291 `  def _mark_request`
  - L316 `  def _write_success_knowledge`
  - L320 `  def _default_runtime_interface`
  - L323 `  def _default_input_schema`
  - L326 `  def _default_output_schema`
  - L329 `  def _default_safety_policy`
  - L336 `  def _safe_name`

- `ai_core/modules/module_artifact_generator.py`（130 行）：modules/module_artifact_generator.py 模块，围绕 module artifact generator 提供结构化运行、配置、验证或桥接能力。
  - L13 `class RuntimeModuleArtifactGenerator`：Generic executable module artifact generator.
  - L21 `  def __init__`
  - L26 `  async def generate_artifact`
  - L83 `  def _json_dumps`
  - L86 `  def _code_generation_route`
  - L94 `  def artifact_schema`

- `ai_core/modules/module_artifact_validator.py`（86 行）：modules/module_artifact_validator.py 模块，围绕 module artifact validator 提供结构化运行、配置、验证或桥接能力。
  - L12 `class RuntimeModuleArtifactValidator`：Domain-neutral validation for generated runtime modules.
  - L17 `  def validate_python_file`
  - L78 `  def _assigned_names`

- `ai_core/modules/module_builder.py`（221 行）：modules/module_builder.py 模块，围绕 module builder 提供结构化运行、配置、验证或桥接能力。
  - L12 `class RuntimeModuleBuilder`：Generic runtime module builder.
  - L32 `  def __init__`
  - L38 `  def ensure_module_for_capability`
  - L60 `  def create_module_blueprint`
  - L125 `  def _extract_metadata`
  - L143 `  def _default_input_schema`
  - L154 `  def _default_output_schema`
  - L166 `  def _default_runtime_interface`
  - L176 `  def _default_safety_policy`
  - L185 `  def _default_implementation_plan`
  - L194 `  def _placeholder_module_py`
  - L212 `  def _readme`
  - L220 `  def _safe_name`

- `ai_core/modules/module_codegen_request.py`（64 行）：modules/module_codegen_request.py 模块，围绕 module codegen request 提供结构化运行、配置、验证或桥接能力。
  - L10 `class ModuleCodeGenerationRequestBuilder`：Creates a strong-model code generation request for a runtime module.
  - L18 `  def __init__`
  - L22 `  def create_request`
  - L63 `  def _safe_name`

- `ai_core/modules/module_loader.py`（83 行）：modules/module_loader.py 模块，围绕 module loader 提供结构化运行、配置、验证或桥接能力。
  - L15 `class RuntimeModuleLoader`：Generic runtime module loader.
  - L28 `  def __init__`
  - L32 `  def load_by_capability`
  - L45 `  def _load_module_with_recovery`
  - L57 `  def _load_module`
  - L65 `  def _missing_module_name`
  - L72 `  def _install_python_package`

- `ai_core/modules/module_registry.py`（101 行）：modules/module_registry.py 模块，围绕 module registry 提供结构化运行、配置、验证或桥接能力。
  - L11 `class RuntimeModuleRegistry`：Generic runtime module registry.
  - L19 `  def __init__`
  - L25 `  def load`
  - L31 `  def save`
  - L34 `  def register`
  - L61 `  def find_by_capability`
  - L86 `  def find_all_by_capability`
  - L90 `  def update_status`

- `ai_core/modules/runtime_generated_module_installer.py`（93 行）：modules/runtime_generated_module_installer.py 模块，围绕 runtime generated module installer 提供结构化运行、配置、验证或桥接能力。
  - L13 `class RuntimeGeneratedModuleInstaller`：Installs executable runtime-generated modules and registers them.
  - L16 `  def __init__`
  - L22 `  def install_artifact`
  - L86 `  def _safe_child_path`
  - L92 `  def _safe_name`

- `ai_core/nodes/__init__.py`（0 行）：nodes/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/nodes/node_config_loader.py`（10 行）：nodes/node_config_loader.py 模块，围绕 node config loader 提供结构化运行、配置、验证或桥接能力。
  - L3 `class NodeConfigLoader`
  - L4 `  def __init__`
  - L5 `  def load`

- `ai_core/nodes/node_runner.py`（9 行）：nodes/node_runner.py 模块，围绕 node runner 提供结构化运行、配置、验证或桥接能力。
  - L3 `class NodeRunner`：Generic node entry point.
  - L5 `  def __init__`
  - L6 `  async def run`

- `ai_core/orchestration/__init__.py`（0 行）：orchestration/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/orchestration/langgraph_stage_contract.py`（59 行）：orchestration/langgraph_stage_contract.py 模块，围绕 langgraph stage contract 提供结构化运行、配置、验证或桥接能力。
  - L12 `class RuntimeGraphState`
  - L36 `def build_stage_graph`：Build a LangGraph StateGraph from the fixed stage contract.

- `ai_core/orchestration/workflow_runtime.py`（979 行）：orchestration/workflow_runtime.py 模块，围绕 workflow runtime 提供结构化运行、配置、验证或桥接能力。
  - L26 `class WorkflowRuntime`
  - L27 `  def __init__`
  - L46 `  def _load_workflow`
  - L49 `  def _progress`
  - L59 `  async def prepare`
  - L86 `  async def run_prepared`
  - L98 `  async def start`
  - L103 `  async def resume`
  - L477 `  async def _continue`
  - L937 `  def _attempt_number`
  - L944 `  def _begin_retry_attempt`
  - L951 `  def _node_index_by_id`
  - L957 `  def add_event_listener`
  - L960 `  def remove_event_listener`
  - L967 `  async def _emit`

- `ai_core/pipeline/__init__.py`（3 行）：pipeline/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/pipeline/stage_contract.py`（195 行）：pipeline/stage_contract.py 模块，围绕 stage contract 提供结构化运行、配置、验证或桥接能力。
  - L8 `class StageContract`
  - L117 `class PipelineStageContract`
  - L118 `  def __init__`
  - L122 `  def ordered_stage_ids`
  - L125 `  def default_workflow_nodes`
  - L131 `  def node_config`
  - L152 `  def generic_schema`
  - L168 `  def prompt_template`

- `ai_core/presentation/__init__.py`（1 行）：Generic result presentation helpers.
  - 无显式顶层类/函数。

- `ai_core/presentation/date_aligned_record_extractor.py`（324 行）：presentation/date_aligned_record_extractor.py 模块，围绕 date aligned record extractor 提供结构化运行、配置、验证或桥接能力。
  - L11 `class TargetRecord`
  - L16 `class DateAlignedRecordExtractor`：Extract compact records aligned to runtime target dates.
  - L40 `  def __init__`
  - L43 `  def extract`
  - L77 `  def _targets`
  - L106 `  def _find_records`
  - L118 `  def _alias_pattern`
  - L126 `  def _records_after_alias`
  - L142 `  def _cut_at_next_record`
  - L184 `  def _trim_before_separator_word`
  - L197 `  def _looks_like_calendar_or_menu_fragment`
  - L214 `  def _looks_like_embedded_measure`
  - L219 `  def _looks_like_record_start`
  - L228 `  def _record_quality_score`
  - L257 `  def _display_record`
  - L273 `  def _trim_dangling_connector`
  - L279 `  def _cut_at_embedded_later_anchor`
  - L292 `  def _cut_noise_tail`
  - L296 `  def _best_alias_prefix`
  - L304 `  def _dedupe_candidates`
  - L315 `  def _dedupe_best`

- `ai_core/presentation/final_answer_synthesizer.py`（423 行）：presentation/final_answer_synthesizer.py 模块，围绕 final answer synthesizer 提供结构化运行、配置、验证或桥接能力。
  - L12 `class FinalAnswerSynthesizer`：Creates final user-facing answers from normalized facts only.
  - L50 `  def __init__`
  - L56 `  async def synthesize`
  - L107 `  def _direct_generated_answer_material`：Return user-facing generated content when it is the planned deliverable.
  - L152 `  def _model_synthesis_enabled`
  - L159 `  async def _try_model_synthesis`
  - L210 `  def _deterministic_summary`
  - L288 `  def _source_report_from_materials`
  - L351 `  def _best_aligned_records`
  - L366 `  def _friendly_label`
  - L372 `  def _clean_sentence`
  - L382 `  def _assert_no_debug_material_in_final_answer`
  - L391 `  def _compact_trust`
  - L396 `  def _original_input`
  - L415 `  def _language`

- `ai_core/presentation/result_material.py`（26 行）：presentation/result_material.py 模块，围绕 result material 提供结构化运行、配置、验证或桥接能力。
  - L8 `class ResultMaterial`：Generic runtime material collected before final user-facing synthesis.
  - L18 `  def to_dict`

- `ai_core/presentation/result_material_builder.py`（165 行）：presentation/result_material_builder.py 模块，围绕 result material builder 提供结构化运行、配置、验证或桥接能力。
  - L8 `class ResultMaterialBuilder`：Collects generic execution outputs as intermediate material.
  - L42 `  def from_execution_step`
  - L54 `  def _quality`
  - L62 `  def _content`
  - L103 `  def _source_documents`：Extract public document excerpts from nested research evidence.
  - L159 `  def _metadata`

- `ai_core/presentation/result_presenter.py`（168 行）：presentation/result_presenter.py 模块，围绕 result presenter 提供结构化运行、配置、验证或桥接能力。
  - L8 `class ResultPresenter`：Turns generic runtime result dictionaries into user-facing text.
  - L31 `  def present_tool_result`
  - L51 `  def present_data`
  - L73 `  def evidence_quality_passed`
  - L86 `  def _format_value`
  - L93 `  def _format_dict`
  - L111 `  def _format_list`
  - L130 `  def _compact_dict`
  - L141 `  def _label`
  - L147 `  def _scalar`
  - L157 `  def _looks_like_raw_markup`
  - L161 `  def _markup_preview`

- `ai_core/presentation/result_sanitizer.py`（180 行）：presentation/result_sanitizer.py 模块，围绕 result sanitizer 提供结构化运行、配置、验证或桥接能力。
  - L10 `class _GenericMarkupParser`：Small, dependency-free extractor for visible text and repeated rows.
  - L13 `  def __init__`
  - L21 `  def handle_starttag`
  - L39 `  def handle_endtag`
  - L52 `  def handle_data`
  - L62 `  def _add_text`
  - L69 `  def _compact_text`
  - L73 `class ResultSanitizer`：Removes raw transport/source payloads and keeps compact evidence material.
  - L90 `  def sanitize_materials`
  - L93 `  def sanitize_material`
  - L98 `  def sanitize_value`
  - L107 `  def _sanitize_dict`
  - L125 `  def _sanitize_text`
  - L132 `  def _looks_like_markup`
  - L136 `  def _extract_from_markup`
  - L152 `  def _dedupe_rows`
  - L163 `  def _strip_markup`
  - L169 `  def _material_to_text`

- `ai_core/presentation/structured_fact_normalizer.py`（466 行）：presentation/structured_fact_normalizer.py 模块，围绕 structured fact normalizer 提供结构化运行、配置、验证或桥接能力。
  - L23 `class NormalizedFact`
  - L33 `  def to_dict`
  - L37 `class StructuredFactNormalizer`：Converts intermediate extraction artifacts into normalized facts.
  - L49 `  def __init__`
  - L53 `  def normalize`
  - L67 `  def reject_debug_text`
  - L71 `  def _facts_from_value`
  - L83 `  def _facts_from_dict`
  - L149 `  def _facts_from_source_text_carriers`
  - L191 `  def _facts_from_selected_blocks`
  - L211 `  def _flatten_text`
  - L220 `  def _facts_from_text`
  - L278 `  def _fact_from_aligned_record`
  - L290 `  def _signal_windows`：Find generic windows with measurement-like signal.
  - L310 `  def _is_source_backed_statement`
  - L317 `  def _statement_from_window`
  - L334 `  def _looks_like_navigation_or_date_only`
  - L360 `  def _relevant_windows`
  - L377 `  def _mentions_runtime_value`
  - L384 `  def _confidence`
  - L392 `  def _trim_context`
  - L395 `  def _label_from_context`
  - L418 `  def _runtime_variables`
  - L422 `  def _source_url`
  - L440 `  def _coerce_fact`
  - L455 `  def _dedupe`

- `ai_core/providers/__init__.py`（0 行）：providers/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/providers/runtime_provider_invoker.py`（194 行）：providers/runtime_provider_invoker.py 模块，围绕 runtime provider invoker 提供结构化运行、配置、验证或桥接能力。
  - L14 `class RuntimeProviderInvoker`：Invoke a registered provider artifact with schema-checked input/output.
  - L17 `  def invoke`
  - L43 `  def _invoke_ollama`
  - L73 `  def _invoke_chat_completions`
  - L99 `  def _invoke_http_json`
  - L121 `  def _invoke_command`
  - L133 `  def _invoke_python_function`
  - L150 `  def _apply_auth`
  - L167 `  def _validate`
  - L173 `  def _normalize`
  - L180 `  def _error`
  - L183 `  def _try_json`

- `ai_core/providers/runtime_provider_lifecycle.py`（29 行）：providers/runtime_provider_lifecycle.py 模块，围绕 runtime provider lifecycle 提供结构化运行、配置、验证或桥接能力。
  - L9 `class RuntimeProviderLifecycle`：Prepare, register, and return executable provider artifacts.
  - L12 `  def __init__`
  - L16 `  def prepare_and_register`

- `ai_core/providers/runtime_provider_registry.py`（115 行）：providers/runtime_provider_registry.py 模块，围绕 runtime provider registry 提供结构化运行、配置、验证或桥接能力。
  - L16 `class RuntimeProviderRegistrationResult`
  - L25 `class RuntimeProviderRegistry`：Register runtime provider usage methods.
  - L33 `  def __init__`
  - L44 `  def load_templates`
  - L47 `  def register`
  - L78 `  def get`
  - L89 `  def validate`
  - L108 `  def _read_json`
  - L114 `  def _safe_id`

- `ai_core/research/__init__.py`（6 行）：Generic runtime research/discovery utilities.
  - 无显式顶层类/函数。

- `ai_core/research/api_discovery.py`（553 行）：research/api_discovery.py 模块，围绕 api discovery 提供结构化运行、配置、验证或桥接能力。
  - L17 `class ApiDiscoveryEngine`：Domain-neutral runtime API discovery and documentation understanding.
  - L26 `  def __init__`
  - L37 `  async def discover`
  - L129 `  def _build_request`
  - L161 `  def _extract_runtime_semantics`
  - L176 `  def _search_queries`
  - L199 `  async def _collect_web_evidence`
  - L225 `  def _infer_request_mode`
  - L244 `  def _evaluate_answer_sufficiency`
  - L254 `  async def _emit_answer_sufficiency`
  - L263 `  async def _fetch_answer_evidence`
  - L306 `  async def _fetch_documentation_evidence`
  - L342 `  async def _try_model_discovery`
  - L380 `  def _route`
  - L391 `  def _usable_discovery`
  - L406 `  def _finalize_answer_sufficient`
  - L446 `  def _finalize`
  - L470 `  async def _emit_done`
  - L490 `  def _dedupe_by_url`
  - L502 `  def discovery_schema`

- `ai_core/research/deep_web_research.py`（657 行）：research/deep_web_research.py 模块，围绕 deep web research 提供结构化运行、配置、验证或桥接能力。
  - L35 `class DeepSearchTrace`
  - L42 `  def to_dict`
  - L48 `class DeepSearchWhiteboxTrace`：Append-only white-box trace for layered web evidence processing.
  - L56 `  def __init__`
  - L67 `  def record`
  - L85 `  def summary`
  - L97 `  def _compact`
  - L120 `class WebContentExtractor`：Generic multi-layer web content extractor.
  - L129 `  def extract`
  - L212 `  def _table_text`
  - L223 `  def _rank_blocks`
  - L238 `  def _dedupe_text`
  - L253 `class DeepWebResearchPipeline`：DeepSearch/DeepResearch-style web evidence pipeline.
  - L261 `  def __init__`
  - L274 `  async def run`
  - L408 `  def _consensus_snapshot`
  - L430 `  def _consensus_should_stop`
  - L440 `  def _apply_consensus_to_reduced`
  - L474 `  def _mark_reduced_as_not_converged`
  - L514 `  def _materialize_browser_document`
  - L565 `  def _merge_materialized_browser_doc`
  - L598 `  def _dedupe_facts`
  - L609 `  def _join_materials`
  - L624 `  def _candidate_preview`
  - L638 `  def _url`
  - L650 `  def _queries_from_candidates`

- `ai_core/research/endpoint_resolver.py`（155 行）：research/endpoint_resolver.py 模块，围绕 endpoint resolver 提供结构化运行、配置、验证或桥接能力。
  - L12 `class ResolvedEndpoint`
  - L19 `class EndpointResolver`：Resolve executable network endpoints from documentation evidence.
  - L31 `  def resolve_from_discovery`
  - L57 `  def resolve_value`
  - L73 `  def resolve_text`
  - L87 `  def _relative_endpoint_variants`
  - L100 `  def _document_pages`
  - L121 `  def _dedupe_pages`
  - L132 `  def _dedupe`
  - L144 `  def _normalize`
  - L153 `  def _looks_executable`

- `ai_core/research/endpoint_verifier.py`（200 行）：research/endpoint_verifier.py 模块，围绕 endpoint verifier 提供结构化运行、配置、验证或桥接能力。
  - L18 `class EndpointCheck`
  - L31 `class EndpointVerifier`：Verify discovered network candidates with real HTTP responses.
  - L40 `  def __init__`
  - L45 `  def verify_discovery`
  - L81 `  def verify_url`
  - L125 `  def _candidate_urls`
  - L168 `  def _dedupe_urls`
  - L179 `  def _normalize_url`
  - L185 `  def _is_json_response`
  - L195 `  def _looks_like_html`
  - L199 `  def _safe_sample`

- `ai_core/research/external_solution_discovery.py`（394 行）：research/external_solution_discovery.py 模块，围绕 external solution discovery 提供结构化运行、配置、验证或桥接能力。
  - L21 `class CandidateRiskAssessment`
  - L28 `class ExternalSolutionDiscoveryEngine`：Generic external capability discovery for runtime self-extension.
  - L41 `  def __init__`
  - L53 `  async def discover`
  - L105 `  def _build_request`
  - L136 `  def _queries`：Return compact evidence queries generated by WebEvidenceOptimizer.
  - L158 `  async def _search_general_web`
  - L184 `  async def _fetch_candidate_documents`
  - L204 `  async def _search_repositories`
  - L252 `  async def _search_model_catalogs`
  - L300 `  def _assess_repository`
  - L320 `  def _assess_document`
  - L337 `  def _finalize`
  - L384 `  def _dedupe_by_url`

- `ai_core/research/model_candidate_evaluator.py`（99 行）：research/model_candidate_evaluator.py 模块，围绕 model candidate evaluator 提供结构化运行、配置、验证或桥接能力。
  - L8 `class ModelCandidateEvaluation`
  - L19 `class ModelCandidateEvaluator`：Evaluate model candidates for runtime routing and download planning.
  - L27 `  def evaluate`
  - L47 `  def _use_cases`
  - L68 `  def _hardware_estimate`
  - L85 `  def _download_strategy`

- `ai_core/research/repository_analyzer.py`（150 行）：research/repository_analyzer.py 模块，围绕 repository analyzer 提供结构化运行、配置、验证或桥接能力。
  - L18 `class RepositoryAnalysisResult`
  - L32 `class GitHubRepositoryAnalyzer`：Clone and analyze external repositories as untrusted runtime evidence.
  - L40 `  def __init__`
  - L46 `  def analyze`
  - L123 `  def _is_allowed_repository_url`
  - L127 `  def _target_path`
  - L135 `  def _read_text_summary`
  - L143 `  def _count_files`

- `ai_core/research/structured_provider_executor.py`（511 行）：research/structured_provider_executor.py 模块，围绕 structured provider executor 提供结构化运行、配置、验证或桥接能力。
  - L18 `class StructuredProviderExecutor`：Generic structured-provider executor.
  - L29 `  def __init__`
  - L35 `  async def execute`
  - L153 `  def _load_policies`
  - L182 `  def _rank_candidates`
  - L205 `  def _advisory_names`
  - L220 `  async def _execute_provider`
  - L252 `  def _extract_material`
  - L312 `  def _records_from_columnar`
  - L328 `  def _fuse_materials`
  - L357 `  def _known_parameters`
  - L362 `  def _render_url`
  - L373 `  def _headers`
  - L383 `  def _body`
  - L395 `  def _http_json`
  - L406 `  def _value_at`
  - L426 `  def _format_value`
  - L433 `  def _requires_secret`
  - L436 `  def _credential_option`
  - L444 `  def _material_is_usable`
  - L450 `  def _enough_material`
  - L454 `  def _write_trace`
  - L459 `  def _investigated_sources`
  - L472 `  def _safe_provider_summary`
  - L482 `  def _compact_result`
  - L493 `  def _preview`
  - L500 `  def _redact_url`
  - L503 `  async def _emit`

- `ai_core/research/web_research_tool.py`（320 行）：research/web_research_tool.py 模块，围绕 web research tool 提供结构化运行、配置、验证或桥接能力。
  - L20 `class WebResearchResult`
  - L32 `class GenericWebResearchTool`：Generic web research capability for runtime discovery.
  - L41 `  def __init__`
  - L45 `  async def search`：Best-effort generic web search with structured evidence output.
  - L106 `  def _search_provider_urls`
  - L113 `  def _extract_search_results`
  - L148 `  def _is_search_navigation_url`
  - L154 `  def _http_headers`
  - L161 `  async def fetch`
  - L201 `  def _extract_html_excerpt`：Return a compact, attribute-preserving HTML evidence excerpt.
  - L232 `  def _extract_dom_evidence_items`：Extract generic DOM evidence from text and useful attributes.
  - L275 `  def _record`
  - L289 `  def _normalize_search_url`
  - L307 `  def _safe_http_url`
  - L314 `  def _clean`
  - L319 `  def _now`

- `ai_core/roles/__init__.py`（12 行）：roles/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/roles/prompt_pack_loader.py`（83 行）：roles/prompt_pack_loader.py 模块，围绕 prompt pack loader 提供结构化运行、配置、验证或桥接能力。
  - L9 `class PromptPackLoader`：Load role-scoped prompt packs from runtime configuration.
  - L65 `  def __init__`
  - L68 `  def load`

- `ai_core/roles/role_profile_selector.py`（219 行）：roles/role_profile_selector.py 模块，围绕 role profile selector 提供结构化运行、配置、验证或桥接能力。
  - L8 `class RoleProfile`：A compact, domain-neutral runtime role profile.
  - L22 `  def to_dict`
  - L26 `class RoleProfileSelector`：Select a compact role profile from runtime state.
  - L157 `  def select`
  - L191 `  def _profile`
  - L202 `  def _collect_signals`
  - L218 `  def _contains_any`

- `ai_core/roles/role_scoped_context_reducer.py`（167 行）：roles/role_scoped_context_reducer.py 模块，围绕 role scoped context reducer 提供结构化运行、配置、验证或桥接能力。
  - L9 `class RoleScopedContextReducer`：Reduce runtime context according to the selected role profile.
  - L59 `  def __init__`
  - L62 `  def reduce_state`
  - L91 `  def _compact_value`
  - L108 `  def _build_evidence_summary`
  - L128 `  def _extract_known_parameters`
  - L151 `  def _collect_evidence_objects`

- `ai_core/roles/runtime_role_contract.py`（78 行）：roles/runtime_role_contract.py 模块，围绕 runtime role contract 提供结构化运行、配置、验证或桥接能力。
  - L8 `class RuntimeRoleContract`：Neutral role contract for the runtime operating system.
  - L20 `  def to_dict`
  - L73 `def runtime_role_contracts`

- `ai_core/runtime/__init__.py`（0 行）：runtime/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/runtime/adaptation/__init__.py`（5 行）：adaptation/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/runtime/adaptation/feedback_classifier.py`（73 行）：adaptation/feedback_classifier.py 模块，围绕 feedback classifier 提供结构化运行、配置、验证或桥接能力。
  - L10 `class FeedbackClassifier`：Classify studio messages as generic runtime feedback.
  - L17 `  def __init__`
  - L21 `  def classify`
  - L51 `  def _load_config`
  - L60 `  def _extract_task_name`

- `ai_core/runtime/adaptation/model_upgrade_controller.py`（29 行）：adaptation/model_upgrade_controller.py 模块，围绕 model upgrade controller 提供结构化运行、配置、验证或桥接能力。
  - L8 `class ModelUpgradeController`：Records generic feedback signals that cause model-route escalation.
  - L11 `  def __init__`
  - L14 `  def record_upgrade_request`

- `ai_core/runtime/adaptation/rerun_strategy.py`（24 行）：adaptation/rerun_strategy.py 模块，围绕 rerun strategy 提供结构化运行、配置、验证或桥接能力。
  - L6 `class RerunStrategy`：Selects a generic rerun boundary for feedback-driven adaptation.
  - L9 `  def choose`

- `ai_core/runtime/approval_policy_store.py`（147 行）：runtime/approval_policy_store.py 模块，围绕 approval policy store 提供结构化运行、配置、验证或桥接能力。
  - L11 `class RuntimeApprovalPolicyStore`：Generic persistent approval policy store for runtime-registered operations.
  - L22 `  def __init__`
  - L25 `  def get_state`
  - L34 `  def set_tool_policy`
  - L62 `  def get_tool_policy`
  - L83 `  def list_policies`
  - L96 `  def is_auto_approved`
  - L105 `  def record_confirmation`
  - L138 `  def _write`
  - L142 `  def _safe`
  - L146 `  def _now`

- `ai_core/runtime/bootstrap/__init__.py`（4 行）：bootstrap/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/runtime/bootstrap/core_bootstrap.py`（1100 行）：bootstrap/core_bootstrap.py 模块，围绕 core bootstrap 提供结构化运行、配置、验证或桥接能力。
  - L14 `class RuntimeBootstrap`
  - L15 `  def __init__`
  - L22 `  def ensure`
  - L82 `  def _ensure_model_topology`
  - L86 `  def _ensure_model_stage_policy`
  - L90 `  def _ensure_provider_runtime_templates`
  - L99 `  def _ensure_runtime_capability_inference`
  - L108 `  def _ensure_runtime_primitive_tool_templates`：Ensure the runtime-owned primitive template location exists.
  - L121 `  def _ensure_model_providers`：Ensure provider config prefers the local default model qwen3.5:2b.
  - L137 `  def _default_model_providers_config`
  - L539 `  def _merge_model_provider_defaults`
  - L588 `  def _ensure_workflow`
  - L606 `  def _ensure_node_configs`
  - L688 `  def _ensure_runtime_templates`
  - L701 `  def _ensure_prompts`
  - L800 `  def _ensure_schemas`
  - L904 `  def _ensure_adapters`
  - L962 `  def _ensure_capability_routes`
  - L968 `  def _ensure_base_capabilities`
  - L990 `  def _ensure_environment`
  - L1003 `  def _ensure_registry`
  - L1009 `  def _ensure_datasets`
  - L1022 `def _v41_stage_contract`
  - L1030 `def _v41_ensure_workflow`
  - L1041 `def _v41_ensure_node_configs`
  - L1048 `def _v41_ensure_runtime_templates`
  - L1054 `def _v41_ensure_prompts`
  - L1061 `def _v41_ensure_schemas`
  - L1068 `def _v41_ensure_adapters`

- `ai_core/runtime/bootstrap/model_requirement_generator.py`（74 行）：bootstrap/model_requirement_generator.py 模块，围绕 model requirement generator 提供结构化运行、配置、验证或桥接能力。
  - L9 `class ModelRequirementGenerator`：Optionally asks a strong external model to build runtime topology.
  - L17 `  def __init__`
  - L20 `  async def generate`

- `ai_core/runtime/bootstrap/provider_discovery.py`（42 行）：bootstrap/provider_discovery.py 模块，围绕 provider discovery 提供结构化运行、配置、验证或桥接能力。
  - L9 `class ProviderDiscovery`：Reads currently configured model providers.
  - L16 `  def __init__`
  - L19 `  def discover`

- `ai_core/runtime/bootstrap/runtime_bootstrap_service.py`（105 行）：bootstrap/runtime_bootstrap_service.py 模块，围绕 runtime bootstrap service 提供结构化运行、配置、验证或桥接能力。
  - L17 `class RuntimeBootstrapService`：Initializes runtime cognitive topology at process startup.
  - L28 `  def __init__`
  - L34 `  async def bootstrap`：Bootstrap runtime topology without blocking API startup.

- `ai_core/runtime/browser/__init__.py`（13 行）：browser/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/runtime/browser/browser_network_observer.py`（236 行）：browser/browser_network_observer.py 模块，围绕 browser network observer 提供结构化运行、配置、验证或桥接能力。
  - L13 `class ObservedNetworkResponse`
  - L27 `  def to_dict`
  - L36 `class BrowserObservationResult`
  - L48 `  def to_document`
  - L67 `class BrowserNetworkObserver`：Browser observability layer based on Playwright/CDP-style network capture.
  - L79 `  def __init__`
  - L84 `  async def observe`
  - L212 `  def _should_keep`
  - L221 `  def _try_parse_json`
  - L227 `  def _dedupe_responses`

- `ai_core/runtime/browser/browser_runtime_adapter.py`（72 行）：browser/browser_runtime_adapter.py 模块，围绕 browser runtime adapter 提供结构化运行、配置、验证或桥接能力。
  - L10 `class BrowserFetchResult`：Result returned by a browser-capable document fetch operation.
  - L20 `  def to_evidence`
  - L32 `class BrowserRuntimeAdapter`：Domain-neutral browser evidence adapter.
  - L43 `  def extract_from_markup`
  - L57 `  def _extract_visible_text`
  - L64 `  def _extract_attribute_text`

- `ai_core/runtime/browser/dom_relation_extractor.py`（227 行）：browser/dom_relation_extractor.py 模块，围绕 dom relation extractor 提供结构化运行、配置、验证或桥接能力。
  - L15 `class DomRelationExtractionResult`
  - L21 `  def to_dict`
  - L25 `class DomRelationExtractor`：Extract relation-like cells from rendered DOM without domain rules.
  - L35 `  def extract`
  - L59 `  def _extract_tables`
  - L92 `  def _extract_dense_sequences`
  - L106 `  def _facts_from_text`
  - L144 `  def _headers`
  - L157 `  def _attrs`
  - L164 `  def _context`
  - L169 `  def _informative`
  - L177 `  def _known_values`
  - L196 `  def _matched_known`
  - L202 `  def _label`
  - L208 `  def _dedupe`
  - L219 `  def _material`

- `ai_core/runtime/browser/embedded_structure_extractor.py`（218 行）：browser/embedded_structure_extractor.py 模块，围绕 embedded structure extractor 提供结构化运行、配置、验证或桥接能力。
  - L16 `class EmbeddedStructureResult`
  - L22 `  def to_dict`
  - L26 `class EmbeddedStructureExtractor`：Extract structured payloads embedded in rendered markup.
  - L39 `  def extract`
  - L69 `  def _collect_payloads`
  - L107 `  def _parse_jsonish`
  - L121 `  def _parse_scalar_sequence`
  - L129 `  def _walk`
  - L142 `  def _fact`
  - L169 `  def _known_values`
  - L188 `  def _matched_known`
  - L194 `  def _label`
  - L199 `  def _dedupe`
  - L210 `  def _material`

- `ai_core/runtime/browser/structured_response_extractor.py`（195 行）：browser/structured_response_extractor.py 模块，围绕 structured response extractor 提供结构化运行、配置、验证或桥接能力。
  - L10 `class StructuredExtractionResult`
  - L17 `  def to_dict`
  - L21 `class StructuredResponseExtractor`：Extract compact facts from browser-captured structured responses.
  - L31 `  def extract`
  - L83 `  def _walk_json`
  - L100 `  def _to_fact`
  - L137 `  def _known_values`
  - L157 `  def _alignment_score`
  - L164 `  def _matched_known`
  - L170 `  def _label_from_path`
  - L175 `  def _dedupe_facts`
  - L186 `  def _material`

- `ai_core/runtime/capability/__init__.py`（4 行）：capability/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/runtime/capability/acquisition_gate.py`（281 行）：capability/acquisition_gate.py 模块，围绕 acquisition gate 提供结构化运行、配置、验证或桥接能力。
  - L11 `class AcquisitionGateDecision`：Domain-neutral decision for runtime-generated capability activation.
  - L22 `  def to_dict`
  - L26 `class RuntimeCapabilityAcquisitionGate`：Single registration gate for runtime-generated capabilities.
  - L41 `  def evaluate_before_validation`
  - L90 `  def evaluate_before_registration`
  - L161 `  def verify_capability_match`
  - L228 `  def write_report`
  - L238 `  def _artifact_text`
  - L276 `  def _reason`

- `ai_core/runtime/capability/capability_discovery_service.py`（67 行）：capability/capability_discovery_service.py 模块，围绕 capability discovery service 提供结构化运行、配置、验证或桥接能力。
  - L12 `class CapabilityDiscoveryService`：Discovers missing capabilities through MCP manifests and strong models.
  - L22 `  def __init__`
  - L26 `  async def discover`
  - L57 `  def _persist`

- `ai_core/runtime/capability/capability_inference.py`（146 行）：capability/capability_inference.py 模块，围绕 capability inference 提供结构化运行、配置、验证或桥接能力。
  - L10 `class CapabilityInference`：Infers a generic capability from runtime policy files.
  - L17 `  def infer`
  - L46 `  def apply_to_step`
  - L67 `  def _rules`
  - L84 `  def _score`
  - L98 `  def _excluded`
  - L108 `  def _merge_params`
  - L128 `  def _contract_text`

- `ai_core/runtime/capability/capability_router.py`（24 行）：capability/capability_router.py 模块，围绕 capability router 提供结构化运行、配置、验证或桥接能力。
  - L10 `class CapabilityRouter`：Coordinates generic execution source routing.
  - L13 `  def __init__`
  - L18 `  def select_mode`
  - L21 `  def try_runtime_native`

- `ai_core/runtime/capability/execution_mode_selector.py`（297 行）：capability/execution_mode_selector.py 模块，围绕 execution mode selector 提供结构化运行、配置、验证或桥接能力。
  - L12 `class ExecutionModeSelector`：Selects a generic execution source mode from runtime contracts.
  - L43 `  def __init__`
  - L47 `  def select`
  - L103 `  def _locked_mode`
  - L122 `  def _mode_from_source_policy`
  - L152 `  def _mode_from_strategy`
  - L169 `  def _mode_allowed`
  - L172 `  def _runtime_native_denied`
  - L187 `  def _strategy_values`
  - L205 `  def _mode_from_category`
  - L224 `  def policy_for`
  - L235 `  def _explicit_mode`
  - L251 `  def _load_policy_files`
  - L268 `  def _merge`
  - L279 `  def _contract_text`

- `ai_core/runtime/capability/fallback_policy.py`（17 行）：capability/fallback_policy.py 模块，围绕 fallback policy 提供结构化运行、配置、验证或桥接能力。
  - L6 `class FallbackPolicy`：Generic fallback decision helper.
  - L9 `  def allowed`

- `ai_core/runtime/capability/registered_tool_agent_binder.py`（211 行）：capability/registered_tool_agent_binder.py 模块，围绕 registered tool agent binder 提供结构化运行、配置、验证或桥接能力。
  - L11 `class RegisteredToolAgentBinder`：Bind reusable agent profiles to already-registered runtime capabilities.
  - L20 `  def __init__`
  - L23 `  def bind`
  - L57 `  def _candidate_tools`
  - L69 `  def _load_registry`
  - L78 `  def _is_executable`
  - L89 `  def _score`
  - L119 `  def _tokens`
  - L124 `  def _tool_summary`
  - L137 `  def _parameter_contract_from_input_schema`
  - L200 `  def _execution_policy`
  - L210 `  def _safe_name`

- `ai_core/runtime/capability/registered_tool_parameter_bridge.py`（290 行）：capability/registered_tool_parameter_bridge.py 模块，围绕 registered tool parameter bridge 提供结构化运行、配置、验证或桥接能力。
  - L10 `class RegisteredToolParameterBridge`：Bridge participant/task parameter values into a registered-tool payload.
  - L21 `  def __init__`
  - L24 `  def build_invocation`
  - L58 `  def input_fields_from_schema`：Return UI-ready fields from a registered tool input schema.
  - L91 `  def _input_schema`
  - L99 `  def _merged_value_sources`
  - L123 `  def _repair_or_supply_structural_value`：Use exact structural tokens from original text when the schema asks for one.
  - L152 `  def _expects_electronic_address`
  - L176 `  def _structural_electronic_address_candidates`
  - L193 `  def _collect_structural_values`
  - L204 `  def _lookup_field_value`
  - L227 `  def _normalize_for_schema`
  - L239 `  def _normalize_scalar_or_object`
  - L259 `  def _as_list`
  - L280 `  def _is_empty`
  - L283 `  def _participant_id`
  - L286 `  def _participant_name`
  - L289 `  def _safe_key`

- `ai_core/runtime/capability/runtime_capability_template_store.py`（70 行）：capability/runtime_capability_template_store.py 模块，围绕 runtime capability template store 提供结构化运行、配置、验证或桥接能力。
  - L10 `class RuntimeCapabilityTemplateStore`：Load runtime capability acquisition templates from runtime-owned areas.
  - L19 `  def __init__`
  - L26 `  def candidate_paths`
  - L47 `  def load_templates`
  - L60 `  def _load_templates_from_path`

- `ai_core/runtime/capability/runtime_native_provider.py`（54 行）：capability/runtime_native_provider.py 模块，围绕 runtime native provider 提供结构化运行、配置、验证或桥接能力。
  - L7 `class RuntimeNativeProvider`：Returns observations from the local runtime.
  - L14 `  def execute`

- `ai_core/runtime/capability/semantic/__init__.py`（0 行）：semantic/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/runtime/capability/semantic/semantic_capability_classifier.py`（83 行）：semantic/semantic_capability_classifier.py 模块，围绕 semantic capability classifier 提供结构化运行、配置、验证或桥接能力。
  - L10 `class SemanticCapabilityClassifier`：Classifies a capability into generic source categories.
  - L17 `  def __init__`
  - L20 `  def classify`
  - L37 `  def _explicit_category`
  - L52 `  def _load_graph`
  - L69 `  def _text`

- `ai_core/runtime/capability/source_priority_engine.py`（28 行）：capability/source_priority_engine.py 模块，围绕 source priority engine 提供结构化运行、配置、验证或桥接能力。
  - L6 `class SourcePriorityEngine`：Ranks execution modes using runtime-provided policy.
  - L16 `  def order`
  - L23 `  def rank`

- `ai_core/runtime/capability/structured_provider_router.py`（23 行）：capability/structured_provider_router.py 模块，围绕 structured provider router 提供结构化运行、配置、验证或桥接能力。
  - L6 `class StructuredProviderRouter`：Generic placeholder for runtime-generated structured providers.
  - L13 `  def has_provider`
  - L17 `  def select`

- `ai_core/runtime/checkpoint_store.py`（13 行）：runtime/checkpoint_store.py 模块，围绕 checkpoint store 提供结构化运行、配置、验证或桥接能力。
  - L4 `class CheckpointStore`
  - L5 `  def save`
  - L8 `  def load`
  - L11 `  def delete`

- `ai_core/runtime/environment/__init__.py`（11 行）：environment/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/runtime/environment/permission_policy.py`（88 行）：environment/permission_policy.py 模块，围绕 permission policy 提供结构化运行、配置、验证或桥接能力。
  - L9 `class RuntimePermissionPolicy`：Generic runtime permission policy for self-healing execution.
  - L33 `  def from_env`
  - L56 `  def can_execute`
  - L68 `  def is_development_administrator`
  - L71 `  def can_use_arbitrary_runtime_material`
  - L87 `  def to_dict`

- `ai_core/runtime/environment/runtime_command_executor.py`（128 行）：environment/runtime_command_executor.py 模块，围绕 runtime command executor 提供结构化运行、配置、验证或桥接能力。
  - L14 `class RuntimeCommandResult`
  - L24 `  def to_dict`
  - L33 `class RuntimeCommandExecutor`：Async shell/Python command runner used by runtime self-healing.
  - L40 `  def __init__`
  - L43 `  async def run_exec`
  - L86 `  async def run_shell`
  - L127 `  async def run_python_module`

- `ai_core/runtime/environment/runtime_dependency_manager.py`（216 行）：environment/runtime_dependency_manager.py 模块，围绕 runtime dependency manager 提供结构化运行、配置、验证或桥接能力。
  - L21 `class RuntimeDependencyResult`
  - L29 `  def to_dict`
  - L33 `class RuntimeDependencyManager`：Generic runtime dependency self-healing manager.
  - L45 `  def __init__`
  - L50 `  async def ensure`
  - L73 `  async def _ensure_python_package`
  - L94 `  async def _ensure_command`
  - L103 `  async def _ensure_playwright_browser`
  - L186 `  def _trace_path`
  - L193 `  def _record`
  - L202 `  def _which_command`
  - L207 `  def _playwright_launch_check_code`

- `ai_core/runtime/evidence/__init__.py`（15 行）：evidence/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/runtime/evidence/canonical_schema_normalizer.py`（185 行）：evidence/canonical_schema_normalizer.py 模块，围绕 canonical schema normalizer 提供结构化运行、配置、验证或桥接能力。
  - L12 `class CanonicalObservation`：Domain-neutral canonical observation used for cross-source comparison.
  - L30 `  def to_fact_patch`
  - L40 `  def _unit_family`
  - L63 `class CanonicalSchemaNormalizer`：Maps arbitrary source records to a generic canonical comparison schema.
  - L68 `  def normalize_facts`
  - L81 `  def observation_from_fact`
  - L114 `  def _number`
  - L123 `  def _unit_from_text`
  - L127 `  def _label_signature`
  - L136 `class SourceInvestigationReporter`：Builds a compact report of every source considered by DeepSearch.
  - L139 `  def build`
  - L175 `  def _int`
  - L181 `  def _float`

- `ai_core/runtime/evidence/consensus_fusion.py`（299 行）：evidence/consensus_fusion.py 模块，围绕 consensus fusion 提供结构化运行、配置、验证或桥接能力。
  - L19 `class ConsensusPolicy`：Generic convergence policy for external evidence.
  - L34 `class EvidenceConsensusFusion`：Fuse independently materialized evidence into compact final material.
  - L43 `  def fuse`
  - L118 `  def _source_packet`
  - L142 `  def _is_aligned_fact`
  - L155 `  def _known_values`
  - L166 `  def _has_measurement`
  - L170 `  def _remove_outliers`
  - L200 `  def _number`
  - L209 `  def _source_key`
  - L212 `  def _coverage_score`
  - L221 `  def _agreement_score`
  - L244 `  def _structure_score`
  - L256 `  def _text_alignment`
  - L263 `  def _build_material`
  - L280 `  def _fallback_material`
  - L288 `  def _source_summaries`

- `ai_core/runtime/evidence/evidence_budget.py`（204 行）：evidence/evidence_budget.py 模块，围绕 evidence budget 提供结构化运行、配置、验证或桥接能力。
  - L10 `class EvidenceBudget`：Adaptive evidence budget.
  - L33 `  def to_dict`
  - L37 `class EvidenceBudgetAllocator`：Build evidence budgets from task complexity without business terms.
  - L40 `  def allocate`
  - L84 `  def should_stop`
  - L102 `  def _variable_count`
  - L113 `  def _configured_int`
  - L120 `class CandidateEvidenceRanker`：Rank and diversify candidate sources before fetching.
  - L129 `  def rank`
  - L161 `  def _known_overlap`
  - L177 `  def _candidate_text`
  - L190 `  def _url`
  - L202 `  def _host`

- `ai_core/runtime/evidence/evidence_normalizer.py`（523 行）：evidence/evidence_normalizer.py 模块，围绕 evidence normalizer 提供结构化运行、配置、验证或桥接能力。
  - L14 `class EvidenceRecord`
  - L24 `  def to_dict`
  - L28 `class _VisibleBlockParser`：Extract compact visible blocks without relying on any domain words.
  - L34 `  def __init__`
  - L40 `  def handle_starttag`
  - L58 `  def handle_endtag`
  - L72 `  def handle_data`
  - L77 `  def _append`
  - L86 `  def _compact`
  - L90 `class RuntimeEvidenceNormalizer`：Create compact, target-aligned evidence without domain-specific rules.
  - L103 `  def __init__`
  - L107 `  def normalize`
  - L137 `  def _runtime_variables`
  - L157 `  def _extract_blocks`
  - L182 `  def _aligned_records`
  - L217 `  def _numeric_row_records`：Extract target-aligned compact numeric rows.
  - L279 `  def _looks_like_embedded_measure`
  - L284 `  def _cut_dense_numeric_row`
  - L305 `  def _numeric_row_quality`
  - L325 `  def _generic_records`
  - L346 `  def _selected_blocks`
  - L355 `  def _block_score`
  - L374 `  def _matched_alias_count`
  - L385 `  def _quality`
  - L428 `  def _material`
  - L452 `  def _record_has_measurement_signal`
  - L456 `  def _split_value_unit`
  - L462 `  def _context`
  - L465 `  def _label_from_context`
  - L472 `  def _looks_noisy_context`
  - L480 `  def _looks_like_repeated_index_strip`
  - L487 `  def _strip_markup`
  - L493 `  def _compact`
  - L496 `  def _dedupe_text`
  - L508 `  def _dedupe_records`

- `ai_core/runtime/evidence/evidence_reducer.py`（195 行）：evidence/evidence_reducer.py 模块，围绕 evidence reducer 提供结构化运行、配置、验证或桥接能力。
  - L9 `class AdaptiveEvidenceReducer`：Reduce raw evidence to compact structured material.
  - L18 `  def __init__`
  - L21 `  def reduce`
  - L113 `  def _document_text`
  - L129 `  def _fact_key`
  - L132 `  def _compact_material`
  - L165 `  def _ordered_facts_for_material`
  - L177 `  def _measurement_signal`
  - L180 `  def _merged_quality`

- `ai_core/runtime/evidence/multi_source_fusion.py`（49 行）：evidence/multi_source_fusion.py 模块，围绕 multi source fusion 提供结构化运行、配置、验证或桥接能力。
  - L7 `class MultiSourceEvidenceFusion`：Merges structured evidence from multiple sources without domain rules.
  - L10 `  def fuse`
  - L29 `  def _facts`
  - L39 `  def _fingerprint`
  - L43 `  def _confidence`

- `ai_core/runtime/evidence/structured_fact_graph.py`（135 行）：evidence/structured_fact_graph.py 模块，围绕 structured fact graph 提供结构化运行、配置、验证或桥接能力。
  - L9 `class StructuredFact`
  - L19 `  def to_dict`
  - L32 `class StructuredFactGraph`：Builds a generic fact graph from evidence text.
  - L49 `  def build`
  - L64 `  def _join_text`
  - L77 `  def _extract_facts`
  - L107 `  def _best_entity_hint`
  - L113 `  def _looks_temporal`
  - L116 `  def _nearby_label`
  - L123 `  def _coverage`

- `ai_core/runtime/evidence/temporal_measurement_sequence.py`（181 行）：evidence/temporal_measurement_sequence.py 模块，围绕 temporal measurement sequence 提供结构化运行、配置、验证或桥接能力。
  - L7 `class TemporalMeasurementSequenceExtractor`：Extract compact temporal measurement rows from structured page text.
  - L27 `  def extract`
  - L71 `  def _known_dates`
  - L88 `  def _extract_rows`
  - L120 `  def _extract_table_rows`
  - L150 `  def _measurements`
  - L162 `  def _generic_label`
  - L176 `  def _row`

- `ai_core/runtime/execution_graph_optimizer.py`（18 行）：runtime/execution_graph_optimizer.py 模块，围绕 execution graph optimizer 提供结构化运行、配置、验证或桥接能力。
  - L6 `class ExecutionGraphOptimizer`：Optimizes a generic execution strategy based on available evidence.
  - L11 `  def optimize`

- `ai_core/runtime/external_runtimes/__init__.py`（0 行）：external_runtimes/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/runtime/external_runtimes/gguf_model_resolver.py`（200 行）：external_runtimes/gguf_model_resolver.py 模块，围绕 gguf model resolver 提供结构化运行、配置、验证或桥接能力。
  - L16 `class GGUFModelSource`
  - L24 `class GGUFModelResolver`：Resolve and stage external GGUF model files.
  - L47 `  def __init__`
  - L51 `  def resolve_candidate`
  - L87 `  def find_local_file`
  - L112 `  def metadata`
  - L124 `  def _source_for`
  - L137 `  def _configured_path`
  - L156 `  def _configured_url`
  - L171 `  def _env_keys`
  - L183 `  def _hf_resolve_url`
  - L189 `  def _filename_from_url`
  - L195 `  def _default_filename`
  - L199 `  def _safe`

- `ai_core/runtime/generated_execution/__init__.py`（2 行）：generated_execution/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/runtime/generated_execution/generated_code_runner.py`（24 行）：generated_execution/generated_code_runner.py 模块，围绕 generated code runner 提供结构化运行、配置、验证或桥接能力。
  - L10 `class GeneratedCodeRunner`：Runs generated Python code in a constrained temporary process.
  - L13 `  def run_python`

- `ai_core/runtime/generated_execution/runtime_command_service.py`（27 行）：generated_execution/runtime_command_service.py 模块，围绕 runtime command service 提供结构化运行、配置、验证或桥接能力。
  - L9 `class RuntimeCommandService`：Unified command service for generated runtime tools.
  - L17 `  def __init__`
  - L20 `  async def run_shell`
  - L23 `  async def run_command`
  - L26 `  async def run_python_module`

- `ai_core/runtime/generated_execution/shell_runtime_executor.py`（12 行）：generated_execution/shell_runtime_executor.py 模块，围绕 shell runtime executor 提供结构化运行、配置、验证或桥接能力。
  - L7 `class ShellRuntimeExecutor`：Executes shell commands with timeout and captured output.
  - L10 `  def run`

- `ai_core/runtime/generated_execution/source_safety.py`（68 行）：generated_execution/source_safety.py 模块，围绕 source safety 提供结构化运行、配置、验证或桥接能力。
  - L9 `class _LoopBoundTransformer`
  - L10 `  def __init__`
  - L14 `  def visit_For`
  - L19 `  def visit_While`
  - L24 `  def _guarded_body`
  - L36 `def bound_python_source`：Return source with generic loop bounds for generated runtime execution.
  - L53 `def write_bounded_python_copy`

- `ai_core/runtime/governance/__init__.py`（1 行）：governance/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/runtime/governance/runtime_cost_policy.py`（188 行）：governance/runtime_cost_policy.py 模块，围绕 runtime cost policy 提供结构化运行、配置、验证或桥接能力。
  - L9 `class RuntimeCostSnapshot`
  - L37 `  def evidence_policy`
  - L54 `  def stage_timeout`
  - L63 `class RuntimeCostPolicy`：Runtime cost and convergence policy.
  - L72 `  def snapshot`
  - L112 `  def apply_adapter_budget`
  - L128 `  def trim_route`
  - L134 `  def _find_policy`
  - L145 `  def _bool`
  - L154 `  def _int`
  - L163 `  def _float`
  - L174 `def _runtime_cost_policy_stage_timeouts`

- `ai_core/runtime/governance/runtime_governance.py`（52 行）：governance/runtime_governance.py 模块，围绕 runtime governance 提供结构化运行、配置、验证或桥接能力。
  - L11 `class RuntimeGovernanceRegistry`：Persists runtime-generated model/capability governance artifacts.
  - L19 `  def __init__`
  - L22 `  def write_bootstrap_artifacts`
  - L42 `  def _extract_requirements`
  - L51 `  def _write`

- `ai_core/runtime/learning/__init__.py`（0 行）：learning/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/runtime/learning/runtime_learning_store.py`（26 行）：learning/runtime_learning_store.py 模块，围绕 runtime learning store 提供结构化运行、配置、验证或桥接能力。
  - L8 `class RuntimeLearningStore`：Append-only runtime learning store for successful generic patterns.
  - L11 `  def __init__`
  - L15 `  def append`
  - L19 `  def read_all`

- `ai_core/runtime/mcp/__init__.py`（0 行）：mcp/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/runtime/mcp/mcp_registry.py`（49 行）：mcp/mcp_registry.py 模块，围绕 mcp registry 提供结构化运行、配置、验证或桥接能力。
  - L10 `class MCPRegistry`：Generic MCP capability manifest registry.
  - L20 `  def load`
  - L32 `  def find_capability`
  - L42 `  def _load`

- `ai_core/runtime/modeling/__init__.py`（9 行）：modeling/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/runtime/modeling/capability_topology.py`（99 行）：modeling/capability_topology.py 模块，围绕 capability topology 提供结构化运行、配置、验证或桥接能力。
  - L11 `class RuntimeModelTopology`：Loads runtime model topology from source config and generated overlays.
  - L14 `  def __init__`
  - L17 `  def load`
  - L24 `  def ensure_defaults`
  - L30 `  def default_topology`
  - L74 `  def _load_json`
  - L83 `  def _load_yaml`
  - L90 `  def _merge`

- `ai_core/runtime/modeling/complexity_estimator.py`（115 行）：modeling/complexity_estimator.py 模块，围绕 complexity estimator 提供结构化运行、配置、验证或桥接能力。
  - L6 `class ComplexityEstimator`：Generic cognitive complexity estimator.
  - L16 `  def estimate`
  - L88 `  def _requested_capabilities`
  - L96 `  def _node_policy`
  - L101 `  def _normalize_level`
  - L105 `  def _score_for_level`
  - L108 `  def _level_for_score`

- `ai_core/runtime/modeling/feedback_escalator.py`（76 行）：modeling/feedback_escalator.py 模块，围绕 feedback escalator 提供结构化运行、配置、验证或桥接能力。
  - L11 `class FeedbackEscalator`：Stores generic model feedback and decides escalation.
  - L18 `  def __init__`
  - L21 `  def load`
  - L30 `  def feedback_for`
  - L37 `  def should_escalate`
  - L54 `  def record_event`
  - L74 `  def _key`

- `ai_core/runtime/modeling/model_provider_autoconfig.py`（248 行）：modeling/model_provider_autoconfig.py 模块，围绕 model provider autoconfig 提供结构化运行、配置、验证或桥接能力。
  - L11 `class ModelProviderAutoConfigurator`：Creates and repairs generic model-provider runtime configuration.
  - L19 `  def __init__`
  - L23 `  def ensure`
  - L33 `  def default_config`
  - L181 `  def _vllm_enabled_by_environment`
  - L184 `  def _prefer_supported_local_runtime`：Keep Windows/default local execution on Ollama.
  - L222 `  def merge`

- `ai_core/runtime/modeling/model_routing_planner.py`（80 行）：modeling/model_routing_planner.py 模块，围绕 model routing planner 提供结构化运行、配置、验证或桥接能力。
  - L10 `class ModelRoutingPlanner`：Plans provider routes for cognitive runtime nodes.
  - L18 `  def __init__`
  - L23 `  def plan`
  - L64 `  def _select_route_name`
  - L77 `  def _node_policy`

- `ai_core/runtime/modeling/model_runtime_preflight.py`（347 行）：modeling/model_runtime_preflight.py 模块，围绕 model runtime preflight 提供结构化运行、配置、验证或桥接能力。
  - L21 `class ProviderHealth`
  - L31 `class ModelRuntimePreflight`：Checks whether the user-selected model mode can actually start.
  - L39 `  def __init__`
  - L46 `  async def check_before_runtime`
  - L104 `  async def _check_local_provider_chain`
  - L131 `  async def _check_local_provider`
  - L204 `  def _missing_python_module_for_command`
  - L219 `  def _maybe_download_local_model`：Prepare a missing local model when policy explicitly allows it.
  - L263 `  async def _check_api_provider`
  - L280 `  def _provider_config`
  - L289 `  def _ok`
  - L297 `  def _blocked`
  - L309 `  def _requires_secret`
  - L338 `  def _format_checks`

- `ai_core/runtime/modeling/model_stage_policy.py`（537 行）：modeling/model_stage_policy.py 模块，围绕 model stage policy 提供结构化运行、配置、验证或桥接能力。
  - L14 `class ModelStagePolicy`：Domain-neutral runtime model governance resolver.
  - L103 `  def __init__`
  - L108 `  def ensure_defaults`
  - L114 `  def load`
  - L122 `  def stage_for`
  - L131 `  def policy_for_stage`
  - L140 `  def should_escalate_on_validation_failure`
  - L145 `  def escalation_adapter`
  - L152 `  def models_for_stage`：Return catalog entries in the exact order the runtime would prefer.
  - L176 `  def apply_to_route`：Return config and route amended with stage-specific virtual providers.
  - L311 `  def _candidate_models`
  - L326 `  def _filter_candidates_by_current_mode`
  - L343 `  def _filter_candidates_by_cost`
  - L357 `  def _filter_candidates_by_stage_requirements`
  - L389 `  def _override_paid_policy`
  - L396 `  def _route_provider_is_local`
  - L414 `  def _local_model_policy`
  - L424 `  def _is_local_model`
  - L430 `  def _is_api_model`
  - L436 `  def _provider_templates_for_model`
  - L470 `  def _provider_can_host_model`
  - L486 `  def _provider_model_for_template`
  - L495 `  def _catalog_provider`
  - L501 `  def _is_ollama_provider`
  - L504 `  def _virtual_provider_name`
  - L509 `  def default_policy`
  - L521 `  def _load_json`
  - L530 `  def _merge`

- `ai_core/runtime/modeling/runtime_execution_policy.py`（213 行）：modeling/runtime_execution_policy.py 模块，围绕 runtime execution policy 提供结构化运行、配置、验证或桥接能力。
  - L30 `class RuntimeExecutionPolicySnapshot`：Single source of truth for provider/runtime execution switches.
  - L42 `  def provider_is_local`
  - L58 `  def filter_route`
  - L84 `  def to_provider_policy`
  - L106 `class RuntimeExecutionPolicy`：Reads the runtime execution switch from one canonical location.
  - L115 `  def __init__`
  - L121 `  def snapshot`
  - L184 `  def _load_policy`
  - L191 `  def _coalesce_bool`
  - L198 `  def _parse_bool`
  - L208 `  def _string_list`

- `ai_core/runtime/modeling/user_model_selection.py`（309 行）：modeling/user_model_selection.py 模块，围绕 user model selection 提供结构化运行、配置、验证或桥接能力。
  - L20 `class UserModelSelectionSnapshot`
  - L34 `  def local_enabled`
  - L38 `  def api_enabled`
  - L42 `  def local_only`
  - L46 `  def api_only`
  - L50 `class UserModelSelectionStore`：User-facing runtime model mode and initial model selection.
  - L60 `  def __init__`
  - L67 `  def snapshot`
  - L96 `  def update`
  - L124 `  def state`
  - L144 `  def available_models`
  - L171 `  def route_allowed`
  - L180 `  def provider_is_local`
  - L190 `  def family_for_model`
  - L194 `  def family_for_model_meta`
  - L202 `  def provider_for_model`
  - L215 `  def provider_model_for`
  - L224 `  def required_secret_for_model`
  - L236 `  def initial_adapter_overrides`
  - L245 `  def reorder_candidates`
  - L255 `  def _read`
  - L264 `  def _load_policy`
  - L275 `  def _model_meta`
  - L281 `  def _local_provider_order`
  - L291 `  def _default_local_model`
  - L298 `  def _default_api_model`
  - L305 `  def _normalize_mode`

- `ai_core/runtime/observability/__init__.py`（0 行）：observability/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/runtime/observability/runtime_console.py`（164 行）：observability/runtime_console.py 模块，围绕 runtime console 提供结构化运行、配置、验证或桥接能力。
  - L18 `def emit_console_event`：Append an operator-visible runtime console event.
  - L41 `def list_console_sources`
  - L80 `def read_console_source`
  - L107 `def _safe_source_path`
  - L125 `def _source_type`
  - L136 `def _redact_data`
  - L153 `def _redact`

- `ai_core/runtime/observability/runtime_debug_console.py`（32 行）：observability/runtime_debug_console.py 模块，围绕 runtime debug console 提供结构化运行、配置、验证或桥接能力。
  - L9 `class RuntimeEvent`
  - L14 `  def to_dict`
  - L18 `class RuntimeDebugConsole`：In-memory observability console for deterministic tests and UI display.
  - L21 `  def __init__`
  - L24 `  def record`
  - L27 `  def timeline`
  - L30 `  def assert_seen`

- `ai_core/runtime/observability/stage_observer.py`（120 行）：observability/stage_observer.py 模块，围绕 stage observer 提供结构化运行、配置、验证或桥接能力。
  - L16 `class StageSpan`
  - L27 `class RuntimeStageObserver`：Domain-neutral runtime stage observer.
  - L35 `  def __init__`
  - L40 `  def span`
  - L90 `  def emit`
  - L119 `  def _safe`

- `ai_core/runtime/provenance.py`（179 行）：runtime/provenance.py 模块，围绕 provenance 提供结构化运行、配置、验证或桥接能力。
  - L13 `class ExecutionProvenanceRecorder`：Records generic execution provenance for tools and modules.
  - L22 `  def __init__`
  - L26 `  def start`
  - L70 `  def finish`
  - L85 `  def attach`
  - L91 `  def public_trace`
  - L112 `  def _trace_id`
  - L116 `  def _artifact_summary`
  - L142 `  def _execution_claims`
  - L169 `  def _safe_json`
  - L172 `  def _write`
  - L178 `  def _now`

- `ai_core/runtime/routing/__init__.py`（0 行）：routing/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/runtime/routing/cost_aware_router.py`（29 行）：routing/cost_aware_router.py 模块，围绕 cost aware router 提供结构化运行、配置、验证或桥接能力。
  - L6 `class CostAwareRouter`：Provider-neutral routing by budget, latency, and quality hints.
  - L9 `  def rank`
  - L20 `  def _score`

- `ai_core/runtime/runtime_template_generator.py`（561 行）：runtime/runtime_template_generator.py 模块，围绕 runtime template generator 提供结构化运行、配置、验证或桥接能力。
  - L14 `class RuntimeTemplateGenerator`：Runtime-generated prompt/schema generator and evolver.
  - L25 `  def __init__`
  - L32 `  def ensure_node_template`
  - L45 `  def evolve_from_feedback`
  - L142 `  def _default_prompt`
  - L175 `  def _stage_boundary_rules`
  - L209 `  def _default_contract`
  - L242 `  def _default_schema`
  - L377 `  def _needs_task_object_schema`
  - L387 `  def _needs_human_confirmation`
  - L399 `  def _needs_more_missing_info`
  - L402 `  def _enforce_object_array_field`
  - L426 `  def _forbid_top_level_field`
  - L441 `  def _ensure_field_in_array_items`
  - L451 `  def _ensure_string_array_field`
  - L459 `  def _ensure_top_level_field`
  - L466 `  def _add_runtime_rules`
  - L482 `  def _ensure_human_feedback_variable`
  - L498 `  def _needs_human_review_object`
  - L506 `  def _evolve_human_review_schema`
  - L542 `  def _add_human_review_prompt_rules`
  - L549 `  def _extract_required_fields`

- `ai_core/runtime/scheduler/__init__.py`（3 行）：scheduler/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/runtime/scheduler/scheduled_task_runner.py`（186 行）：scheduler/scheduled_task_runner.py 模块，围绕 scheduled task runner 提供结构化运行、配置、验证或桥接能力。
  - L11 `class ScheduledTaskRunner`：Generic durable task scheduler.
  - L19 `  def __init__`
  - L25 `  def start`
  - L31 `  async def stop`
  - L40 `  async def _loop`
  - L51 `  async def run_once`
  - L103 `  async def _call_executor`：Call either legacy one-argument or graph-aware executors.
  - L122 `  def _controller_participant_ids`
  - L126 `  def _payload_participant_ids`
  - L142 `  def _read`
  - L149 `  def _write`
  - L152 `  def _parse_time`
  - L164 `  def _trace`

- `ai_core/runtime/self_repair/__init__.py`（13 行）：self_repair/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/runtime/self_repair/contracts.py`（88 行）：self_repair/contracts.py 模块，围绕 contracts 提供结构化运行、配置、验证或桥接能力。
  - L16 `class FailureReport`：Generic failure envelope used by the runtime self-repair engine.
  - L36 `  def to_dict`
  - L41 `class RepairAction`
  - L53 `  def to_dict`
  - L58 `class RepairPlan`
  - L68 `  def can_auto_apply`
  - L71 `  def to_dict`
  - L78 `class RepairResult`
  - L87 `  def to_dict`

- `ai_core/runtime/self_repair/engine.py`（171 行）：self_repair/engine.py 模块，围绕 engine 提供结构化运行、配置、验证或桥接能力。
  - L15 `class RuntimeSelfRepairEngine`：Generic self-repair orchestrator for ai_core runtime failures.
  - L23 `  def __init__`
  - L31 `  def diagnose`
  - L36 `  def plan`
  - L77 `  def repair`
  - L101 `  def write_trace`
  - L112 `  def _normalize_report`
  - L129 `  def _payload`
  - L137 `  def _schema`
  - L143 `  def _required`
  - L152 `  def _apply`
  - L165 `  def _validate`

- `ai_core/runtime/self_repair/execution_failure_repair.py`（146 行）：self_repair/execution_failure_repair.py 模块，围绕 execution failure repair 提供结构化运行、配置、验证或桥接能力。
  - L8 `class ExecutionFailureDiagnosis`
  - L19 `  def to_dict`
  - L23 `class ExecutionFailureRepairClassifier`：Classify runtime execution failures using generic structural signals.
  - L31 `  def classify`
  - L106 `  def _error_object`
  - L116 `  def _schema_or_parameter_signal`
  - L122 `  def _configuration_signal`
  - L132 `  def _secret_signal`
  - L137 `  def _external_service_signal`
  - L140 `  def _implementation_signal`

- `ai_core/runtime/self_repair/failure_classifier.py`（90 行）：self_repair/failure_classifier.py 模块，围绕 failure classifier 提供结构化运行、配置、验证或桥接能力。
  - L8 `class FailureClassifier`：Classifies runtime failures using structural signals only.
  - L11 `  def classify`
  - L54 `  def _has_schema_signal`
  - L59 `  def _has_variable_signal`
  - L65 `  def _has_parameter_signal`
  - L77 `  def _has_state_signal`
  - L82 `  def _has_verification_signal`
  - L87 `  def _has_execution_signal`

- `ai_core/runtime/self_repair/final_answer_guard.py`（36 行）：self_repair/final_answer_guard.py 模块，围绕 final answer guard 提供结构化运行、配置、验证或桥接能力。
  - L6 `class FinalAnswerGuard`：Prevents unsupported success claims for runtime actions.
  - L9 `  def evaluate`
  - L28 `  def _looks_like_success`

- `ai_core/runtime/self_repair/json_path.py`（43 行）：self_repair/json_path.py 模块，围绕 json path 提供结构化运行、配置、验证或桥接能力。
  - L7 `def get_path`
  - L21 `def set_path`
  - L39 `def _parts`

- `ai_core/runtime/self_repair/parameter_repair.py`（70 行）：self_repair/parameter_repair.py 模块，围绕 parameter repair 提供结构化运行、配置、验证或桥接能力。
  - L9 `class ParameterBindingRepairer`：Repairs generic parameter binding gaps using declared aliases and names.
  - L17 `  def plan`
  - L48 `  def apply`
  - L55 `  def _find_source`
  - L69 `  def _norm`

- `ai_core/runtime/self_repair/repair_orchestrator.py`（283 行）：self_repair/repair_orchestrator.py 模块，围绕 repair orchestrator 提供结构化运行、配置、验证或桥接能力。
  - L15 `class FeedbackRepairOrchestrator`：User-confirmed repair coordinator.
  - L23 `  def __init__`
  - L30 `  def propose_for_tool_result`
  - L101 `  def apply`
  - L126 `  def _apply_parameter_repair`
  - L151 `  def _create_capability_patch_request`
  - L183 `  def _repair_interaction_contract`：Return the generic repair route for a diagnosed failure.
  - L247 `  def _user_message`
  - L250 `  def _new_repair_id`
  - L254 `  def _proposal_path`
  - L258 `  def _load_repair_record`
  - L268 `  def _redact`
  - L282 `  def _safe_name`

- `ai_core/runtime/self_repair/schema_repair.py`（95 行）：self_repair/schema_repair.py 模块，围绕 schema repair 提供结构化运行、配置、验证或桥接能力。
  - L9 `class SchemaRepairer`：Safe deterministic repairs for JSON-like payloads against simple schemas.
  - L12 `  def plan`
  - L36 `  def apply`
  - L43 `  def validate_minimal`
  - L60 `  def _convert`
  - L84 `  def _matches`

- `ai_core/runtime/self_repair/state_repair.py`（54 行）：self_repair/state_repair.py 模块，围绕 state repair 提供结构化运行、配置、验证或桥接能力。
  - L9 `class StateRepairer`：Plans safe recovery for missing runtime state references.
  - L12 `  def plan`
  - L34 `  def apply`
  - L41 `  def _find_checkpoint`

- `ai_core/runtime/self_repair/trace_logger.py`（53 行）：self_repair/trace_logger.py 模块，围绕 trace logger 提供结构化运行、配置、验证或桥接能力。
  - L11 `class FeedbackRepairTraceLogger`：Append-only generic repair trace logger.
  - L20 `  def __init__`
  - L23 `  def record`
  - L37 `  def write_snapshot`
  - L45 `  def _json_safe`
  - L52 `  def _safe_name`

- `ai_core/runtime/self_repair/variable_repair.py`（108 行）：self_repair/variable_repair.py 模块，围绕 variable repair 提供结构化运行、配置、验证或桥接能力。
  - L13 `class VariableBindingRepairer`：Resolves template references from generic runtime state.
  - L16 `  def plan`
  - L36 `  def apply`
  - L43 `  def _resolve_text`
  - L58 `  def _lookup`
  - L73 `  def _walk`
  - L85 `  def _set`
  - L103 `  def _compact`

- `ai_core/runtime/self_repair/web_evidence.py`（51 行）：self_repair/web_evidence.py 模块，围绕 web evidence 提供结构化运行、配置、验证或桥接能力。
  - L6 `class WebEvidenceRepairAdvisor`：Optional adapter for external evidence repair.
  - L14 `  async def advise`

- `ai_core/runtime/semantic/__init__.py`（15 行）：semantic/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/runtime/semantic/constraint_engine.py`（70 行）：semantic/constraint_engine.py 模块，围绕 constraint engine 提供结构化运行、配置、验证或桥接能力。
  - L6 `class ConstraintEngine`：Applies runtime-declared and generic semantic constraints.
  - L19 `  def validate`
  - L56 `  def _contract_constraints`
  - L66 `  def _number`

- `ai_core/runtime/semantic/contract_engine.py`（88 行）：semantic/contract_engine.py 模块，围绕 contract engine 提供结构化运行、配置、验证或桥接能力。
  - L13 `class RuntimeSemanticContractEngine`：Validates facts using runtime-generated semantic contracts.
  - L21 `  def __init__`
  - L27 `  def verify_facts`
  - L46 `  def load_contract`
  - L61 `  def _inline_contract`
  - L73 `  def _merge`
  - L84 `  def _sort_and_limit`

- `ai_core/runtime/semantic/fact_type_inferencer.py`（83 行）：semantic/fact_type_inferencer.py 模块，围绕 fact type inferencer 提供结构化运行、配置、验证或桥接能力。
  - L7 `class FactTypeInferencer`：Infers generic semantic types for extracted facts.
  - L24 `  def infer`
  - L50 `  def _looks_like_coordinate`
  - L64 `  def _text_after_value`
  - L72 `  def _looks_like_temporal`
  - L75 `  def _confidence`

- `ai_core/runtime/semantic/source_trust_engine.py`（42 行）：semantic/source_trust_engine.py 模块，围绕 source trust engine 提供结构化运行、配置、验证或桥接能力。
  - L6 `class SourceTrustEngine`：Assigns generic trust levels to evidence material.
  - L17 `  def classify`
  - L34 `  def allowed`
  - L41 `  def rank`

- `ai_core/runtime/semantic/synthesis_guard.py`（18 行）：semantic/synthesis_guard.py 模块，围绕 synthesis guard 提供结构化运行、配置、验证或桥接能力。
  - L6 `class SynthesisGuard`：Filters synthesis inputs to verified, user-facing facts.
  - L9 `  def filter`

- `ai_core/runtime/semantic/verified_fact_filter.py`（8 行）：semantic/verified_fact_filter.py 模块，围绕 verified fact filter 提供结构化运行、配置、验证或桥接能力。
  - L6 `class VerifiedFactFilter`
  - L7 `  def filter`

- `ai_core/runtime/temporal/__init__.py`（3 行）：temporal/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/runtime/temporal/date_aliases.py`（206 行）：temporal/date_aliases.py 模块，围绕 date aliases 提供结构化运行、配置、验证或桥接能力。
  - L9 `class DateAliasGenerator`：Builds temporal aliases without hard-coded natural-language month names.
  - L20 `  def aliases_for`
  - L26 `  def aliases_from_state`
  - L63 `  def _walk_section`
  - L77 `  def _collect`
  - L112 `  def _collect_runtime_aliases`
  - L143 `  def _canonical_values`
  - L156 `  def _collect_raw`
  - L171 `  def _load_contract_aliases`
  - L194 `  def _dedupe`

- `ai_core/runtime/trace_writer.py`（12 行）：runtime/trace_writer.py 模块，围绕 trace writer 提供结构化运行、配置、验证或桥接能力。
  - L7 `class TraceWriter`
  - L8 `  def write`

- `ai_core/runtime/verification/__init__.py`（0 行）：verification/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/runtime/verification/evidence_contract.py`（33 行）：verification/evidence_contract.py 模块，围绕 evidence contract 提供结构化运行、配置、验证或桥接能力。
  - L8 `class EvidenceContractValidator`：Validates generic structured evidence before synthesis.
  - L17 `  def __init__`
  - L20 `  def validate`

- `ai_core/runtime/verification/execution_assertions.py`（12 行）：verification/execution_assertions.py 模块，围绕 execution assertions 提供结构化运行、配置、验证或桥接能力。
  - L6 `class ExecutionAssertions`：Asserts required runtime state transitions occurred.
  - L9 `  def require_events`

- `ai_core/runtime/verification/failure_taxonomy.py`（34 行）：verification/failure_taxonomy.py 模块，围绕 failure taxonomy 提供结构化运行、配置、验证或桥接能力。
  - L7 `class FailureKind`
  - L17 `class FailureClassifier`
  - L18 `  def classify`

- `ai_core/runtime/verification/generated_execution_validator.py`（18 行）：verification/generated_execution_validator.py 模块，围绕 generated execution validator 提供结构化运行、配置、验证或桥接能力。
  - L6 `class GeneratedExecutionValidator`：Rejects generated execution results without evidence linkage.
  - L9 `  def validate`

- `ai_core/runtime/verification/regression_replay.py`（14 行）：verification/regression_replay.py 模块，围绕 regression replay 提供结构化运行、配置、验证或桥接能力。
  - L6 `class RegressionReplayRunner`：Runs deterministic replay scenarios.
  - L9 `  def run`

- `ai_core/sandbox/__init__.py`（0 行）：sandbox/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/sandbox/verified_sandbox_runtime.py`（319 行）：sandbox/verified_sandbox_runtime.py 模块，围绕 verified sandbox runtime 提供结构化运行、配置、验证或桥接能力。
  - L20 `class VerifiedSandboxResult`
  - L31 `class VerifiedSandboxRuntime`：Verify runtime artifacts in an isolated Docker or venv sandbox.
  - L41 `  def __init__`
  - L45 `  def _project_root`：Return the source root that contains ai_core.
  - L55 `  def verify_tool_artifact`
  - L121 `  def _sandbox_stdout_error`：Treat structured error output as sandbox failure even with exit code 0.
  - L140 `  def _summarize_static_failure`
  - L155 `  def verify_module_artifact`：Verify a runtime module artifact with the same generic sandbox path.
  - L181 `  def _write_artifact`
  - L192 `  def _safe_child_path`
  - L198 `  def _callable_info`
  - L209 `  def _write_runner`
  - L269 `  def _run_in_docker`
  - L284 `  def _run_in_venv`
  - L311 `  def _missing_python_module`

- `ai_core/secrets/__init__.py`（3 行）：secrets/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/secrets/secret_store.py`（107 行）：Runtime secret persistence for local development.
  - L20 `class SecretStore`：Small file-backed secret store used by runtime credential recovery.
  - L37 `  def __init__`
  - L40 `  def set`
  - L55 `  def get`
  - L74 `  def has`
  - L77 `  def delete`
  - L90 `  def list_keys`
  - L96 `  def _load_unlocked`
  - L106 `  def _normalize_key`

- `ai_core/security/__init__.py`（0 行）：security/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/security/dependency_scanner.py`（128 行）：security/dependency_scanner.py 模块，围绕 dependency scanner 提供结构化运行、配置、验证或桥接能力。
  - L14 `class DependencyScanResult`
  - L23 `class DependencyScanner`：Generic dependency scanner for runtime-downloaded/generated artifacts.
  - L39 `  def scan_requirements_text`
  - L71 `  def scan_path`
  - L88 `  def _normalize_lines`
  - L100 `  def _pip_audit`

- `ai_core/security/repository_dependency_gate.py`（45 行）：security/repository_dependency_gate.py 模块，围绕 repository dependency gate 提供结构化运行、配置、验证或桥接能力。
  - L12 `class RepositoryDependencyGateResult`
  - L21 `class RepositoryDependencyGate`：Require explicit approval before installing dependencies from external repositories.
  - L24 `  def __init__`
  - L28 `  def evaluate`

- `ai_core/tools/browser_automation_blueprint.py`（5 行）：tools/browser_automation_blueprint.py 模块，围绕 browser automation blueprint 提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/tools/generic_tool_runner.py`（235 行）：tools/generic_tool_runner.py 模块，围绕 generic tool runner 提供结构化运行、配置、验证或桥接能力。
  - L12 `class GenericToolRunner`：Generic runtime tool runner.
  - L21 `  def __init__`
  - L25 `  def run_tool`
  - L118 `  def _runtime_input_for_schema_validation`：Return only the runtime input part that should be checked by input_schema.
  - L136 `  def _output_for_schema_validation`：Return the tool-contract output view for output_schema validation.
  - L153 `  def _redact_runtime_sensitive`
  - L175 `  def _normalize_tool_output`
  - L204 `  def _is_success`
  - L207 `  def _first_capability`
  - L216 `  def _load_function`
  - L228 `  def _error`

- `ai_core/tools/generic_web_extract_artifact.py`（5 行）：tools/generic_web_extract_artifact.py 模块，围绕 generic web extract artifact 提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/tools/runtime_generated_tool_installer.py`（5 行）：tools/runtime_generated_tool_installer.py 模块，围绕 runtime generated tool installer 提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/tools/runtime_primitive_tool_factory.py`（5 行）：tools/runtime_primitive_tool_factory.py 模块，围绕 runtime primitive tool factory 提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/tools/runtime_registered_tool_service.py`（464 行）：tools/runtime_registered_tool_service.py 模块，围绕 runtime registered tool service 提供结构化运行、配置、验证或桥接能力。
  - L15 `class RuntimeRegisteredToolService`：Generic service for listing and executing runtime-registered tools.
  - L23 `  def __init__`
  - L30 `  def list_tools`
  - L46 `  def get_tool`
  - L55 `  def configure_tool_profile`
  - L80 `  def execute_tool`
  - L216 `  def _validation_error`
  - L249 `  def delete_tool`
  - L284 `  def list_tool_runs`
  - L299 `  def list_execution_traces`
  - L314 `  def list_profiles`
  - L319 `  def _coerce_by_schema`：Coerce browser/runtime string values to schema-declared JSON types.
  - L368 `  def _parse_bool`
  - L382 `  def _apply_runtime_invocation_defaults`：Apply registry-declared invocation defaults before execution.
  - L411 `  def _approval_preview`
  - L417 `  def _persist_tool_result`
  - L428 `  def _load_registry`
  - L437 `  def _is_executable`
  - L450 `  def _public_tool_summary`

- `ai_core/tools/runtime_tool_artifact_generator.py`（5 行）：tools/runtime_tool_artifact_generator.py 模块，围绕 runtime tool artifact generator 提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/tools/runtime_tool_artifact_validator.py`（5 行）：tools/runtime_tool_artifact_validator.py 模块，围绕 runtime tool artifact validator 提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/tools/runtime_tool_registry.py`（6 行）：tools/runtime_tool_registry.py 模块，围绕 runtime tool registry 提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/tools/sandbox_verifier.py`（5 行）：tools/sandbox_verifier.py 模块，围绕 sandbox verifier 提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/tools/tool_blueprint_builder.py`（5 行）：tools/tool_blueprint_builder.py 模块，围绕 tool blueprint builder 提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/tools/tool_code_generation_request.py`（5 行）：tools/tool_code_generation_request.py 模块，围绕 tool code generation request 提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/tools/tool_schema_validator.py`（83 行）：tools/tool_schema_validator.py 模块，围绕 tool schema validator 提供结构化运行、配置、验证或桥接能力。
  - L6 `class ToolSchemaValidator`：Small generic JSON-schema subset validator used by the runtime tool layer.
  - L15 `  def validate_input`
  - L18 `  def validate_output`
  - L21 `  def _validate`
  - L26 `  def _check`
  - L68 `  def _matches_type`

- `ai_core/utils/safe_json.py`（78 行）：utils/safe_json.py 模块，围绕 safe json 提供结构化运行、配置、验证或桥接能力。
  - L11 `def make_json_safe`：Return a JSON-serializable copy of *value*.
  - L76 `def safe_json_dumps`

- `ai_core/utils/safe_subprocess.py`（19 行）：utils/safe_subprocess.py 模块，围绕 safe subprocess 提供结构化运行、配置、验证或桥接能力。
  - L7 `def run_text`：Run a subprocess and decode text output safely on every OS.

- `ai_core/validation/__init__.py`（0 行）：validation/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/validation/recoverable_validation_error.py`（7 行）：validation/recoverable_validation_error.py 模块，围绕 recoverable validation error 提供结构化运行、配置、验证或桥接能力。
  - L1 `class RecoverableValidationError`
  - L2 `  def __init__`

- `ai_core/validation/result_auto_repair.py`（294 行）：validation/result_auto_repair.py 模块，围绕 result auto repair 提供结构化运行、配置、验证或桥接能力。
  - L10 `class ResultAutoRepair`：Generic runtime result repair.
  - L25 `  def __init__`
  - L28 `  def try_repair`
  - L78 `  def _repair_value`
  - L140 `  def _repair_object`
  - L168 `  def _select_schema`
  - L180 `  def _value_matches_type`
  - L195 `  def _preferred_type`
  - L201 `  def _find_value`
  - L211 `  def _search_nested`
  - L226 `  def _default_from_schema`
  - L258 `  def _field_name`
  - L263 `  def _stringify`
  - L270 `  def _truthy`
  - L277 `  def _truthy_object`
  - L284 `  def _number`
  - L291 `  def _log`

- `ai_core/validation/schema_auto_repair.py`（223 行）：validation/schema_auto_repair.py 模块，围绕 schema auto repair 提供结构化运行、配置、验证或桥接能力。
  - L13 `class SchemaAutoRepair`：Generic runtime schema repair.
  - L24 `  def __init__`
  - L28 `  def try_repair`
  - L117 `  def _extract_property_field`
  - L132 `  def _forbid_property`
  - L147 `  def _infer_schema`
  - L169 `  def _ensure_property`
  - L176 `  def _make_property_compatible`
  - L199 `  def _schema_accepts`
  - L217 `  def _schemas_equal`
  - L220 `  def _log`

- `ai_core/validation/schema_validator.py`（5 行）：validation/schema_validator.py 模块，围绕 schema validator 提供结构化运行、配置、验证或桥接能力。
  - L3 `class SchemaValidator`
  - L4 `  def validate_data`

- `ai_core/validation/semantic_boundary_scanner.py`（83 行）：validation/semantic_boundary_scanner.py 模块，围绕 semantic boundary scanner 提供结构化运行、配置、验证或桥接能力。
  - L10 `class SemanticBoundaryFinding`
  - L18 `class SemanticBoundaryScanner`：Generic semantic boundary scanner.
  - L26 `  def scan_path`
  - L49 `  def scan_text`
  - L71 `  def _matches`

- `ai_core/web_evidence_optimizer/__init__.py`（4 行）：web_evidence_optimizer/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/web_evidence_optimizer/optimizer.py`（427 行）：web_evidence_optimizer/optimizer.py 模块，围绕 optimizer 提供结构化运行、配置、验证或桥接能力。
  - L12 `def json_safe_string`
  - L28 `class EvidenceChunk`
  - L39 `class WebEvidenceOptimizer`：Optimize noisy web/retrieval material into compact evidence packs.
  - L55 `  def __init__`
  - L58 `  def plan_queries`
  - L61 `  def optimize`
  - L109 `  def _materialize_documents`
  - L148 `  def _build_chunks`
  - L175 `  def _batch_select_chunks`：Select top evidence in small batches, then perform a global top-k.
  - L193 `  def _limit_evidence_pack`：Limit evidence size before it is passed to a small model.
  - L219 `  def _dedupe_chunks`
  - L229 `  def _chunk_to_pack_item`
  - L245 `  def _summary`
  - L259 `  def _clean_text`
  - L273 `  def _remove_known_noise_nodes`
  - L299 `  def _select_content_nodes`
  - L324 `  def _split_text`
  - L344 `  def _terms`
  - L349 `  def _score`
  - L361 `  def _trust_score`
  - L376 `  def _source_type`
  - L388 `  def _purpose`
  - L398 `  def _extract_facts`
  - L407 `  def _extract_hints`
  - L416 `  def _extract_security_notes`
  - L425 `  def _fingerprint`

- `ai_core/web_evidence_optimizer/query_planner.py`（86 行）：web_evidence_optimizer/query_planner.py 模块，围绕 query planner 提供结构化运行、配置、验证或桥接能力。
  - L9 `class PlannedQuery`
  - L15 `class SearchQueryPlanner`：Create compact, purpose-scoped search queries from runtime context.
  - L26 `  def plan`
  - L52 `  def _identity_text`
  - L67 `  def _compact_terms`
  - L84 `  def _clip`

- `ai_core/workflow/__init__.py`（0 行）：workflow/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `ai_core/workflow/execution_options.py`（146 行）：workflow/execution_options.py 模块，围绕 execution options 提供结构化运行、配置、验证或桥接能力。
  - L8 `class ExecutionOption`
  - L130 `def fixed_options_for_prompt`
  - L134 `def method_for_action`
  - L138 `def is_fixed_action`
  - L142 `def normalize_action_type`

- `ai_core/workflow/execution_state_repair.py`（205 行）：workflow/execution_state_repair.py 模块，围绕 execution state repair 提供结构化运行、配置、验证或桥接能力。
  - L12 `class ExecutionStateRepair`：Repairs runtime-generated workflow state before execution.
  - L26 `  def __init__`
  - L34 `  def repair`
  - L122 `  def _load_config`
  - L131 `  def _missing_names`
  - L138 `  def _missing_value`
  - L143 `  def _is_optional_refinement`
  - L149 `  def _can_mark_ready`
  - L161 `  def _requires_confirmation_by_structure`
  - L177 `  def _strategy_values`
  - L185 `  def _human_interaction_only_optional`
  - L194 `  def _collect_blockers`
  - L203 `  def _tokens`

- `ai_core/workflow/intent_contract.py`（242 行）：workflow/intent_contract.py 模块，围绕 intent contract 提供结构化运行、配置、验证或桥接能力。
  - L9 `class IntentContractGuard`：Creates and enforces a stage-boundary contract from intent output.
  - L20 `  def build`
  - L51 `  def apply`
  - L86 `  def _guard_step`
  - L132 `  def _ensure_external_strategy`
  - L140 `  def _extract_request_objective`
  - L163 `  def _intent_family`
  - L199 `  def _is_redundant_parameter_preparation_step`
  - L224 `  def _target_values`

- `ai_core/workflow/planning_recovery.py`（69 行）：workflow/planning_recovery.py 模块，围绕 planning recovery 提供结构化运行、配置、验证或桥接能力。
  - L7 `class PlanningRecoveryService`：Generic recovery when the planner produced no executable steps.
  - L16 `  def recover_if_empty`
  - L36 `  def _generic_generation_step`

- `ai_core/workflow/workflow_contract_builder.py`（755 行）：workflow/workflow_contract_builder.py 模块，围绕 workflow contract builder 提供结构化运行、配置、验证或桥接能力。
  - L18 `class WorkflowContractBuilder`：Domain-neutral workflow output normalizer.
  - L27 `  def __init__`
  - L30 `  def fixed_action_types`
  - L33 `  def is_runtime_capability_acquisition_context`：Return True when upstream structure says this run is acquiring a runtime capability.
  - L70 `  def normalize_workflow_result`
  - L139 `  def extract_execution_decision`：Find the first valid fixed-action decision in a generic nested record.
  - L169 `  def extract_execution_instruction`：Extract a generic executor-facing instruction from planner output.
  - L213 `  def extract_planned_steps`：Return the deepest valid planned_steps array from nested output.
  - L242 `  def iter_nested_dicts`
  - L253 `  def normalize_decision`
  - L282 `  def _joined_request_text`：Collect generic request text for structural action-policy checks.
  - L310 `  def _looks_like_final_text_deliverable`：Return False without vocabulary inference.
  - L319 `  def _correct_action_for_output_contract`：Prevent accidental runtime-artifact generation for direct output tasks.
  - L333 `  def default_execution_decision`
  - L349 `  def default_action_from_structural_context`：Choose a safe fixed action using only generic runtime structure.
  - L371 `  def has_missing_required_input`
  - L385 `  def allows_research_to_resolve_missing`
  - L402 `  def default_step`
  - L430 `  def collect_available_artifacts`
  - L468 `  def referenced_artifacts_for_state`
  - L491 `  def artifact_forced_decision`
  - L509 `  def normalize_step`
  - L573 `  def extract_agent_execution_flow`：Extract or synthesize a domain-neutral agent execution flow.
  - L587 `  def default_agent_execution_flow`
  - L701 `  def source_policy_for_method`
  - L708 `  def build_agent_graph`
  - L719 `  def collect_known_parameters`
  - L742 `  def objective_from_state`
  - L748 `  def capability_from_state`

- `ai_core/workflow/workflow_normalizer.py`（173 行）：workflow/workflow_normalizer.py 模块，围绕 workflow normalizer 提供结构化运行、配置、验证或桥接能力。
  - L9 `class WorkflowNormalizer`：Normalizes runtime-generated workflow plans without knowing domain semantics.
  - L18 `  def __init__`
  - L21 `  def normalize`
  - L72 `  def _normalize_parameters`
  - L89 `  def _collect_missing_info`
  - L96 `  def _extract_step_capability`
  - L118 `  def _match_capability`
  - L145 `  def _missing_fields_from_parameters`
  - L156 `  def _as_string_list`
  - L169 `  def _tokens`

- `ai_core/workflow/workflow_state_merger.py`（232 行）：workflow/workflow_state_merger.py 模块，围绕 workflow state merger 提供结构化运行、配置、验证或桥接能力。
  - L7 `class WorkflowStateMerger`：Merges human-provided values into runtime-generated workflow state.
  - L15 `  def merge_human_information`
  - L63 `  def _merge_missing_dict`
  - L77 `  def _merge_missing_list`
  - L95 `  def _merge_explicit_step_answers`：Keep provided values in known even when there is no missing match.
  - L119 `  def _extract_answers`
  - L133 `  def _extract_mapping`
  - L159 `  def _answer_aliases`
  - L191 `  def _find_answer_key`
  - L202 `  def _normalized_aliases`
  - L210 `  def _safe_key`
  - L216 `  def _has_value`
  - L219 `  def _missing_fields`
  - L227 `  def _collect_missing`

#### apps

- `apps/__init__.py`（0 行）：apps/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `apps/api/__init__.py`（0 行）：api/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `apps/api/server.py`（1101 行）：api/server.py 模块，围绕 server 提供结构化运行、配置、验证或桥接能力。
  - L49 `async def _start_scheduled_task_runner`
  - L76 `async def _stop_scheduled_task_runner`
  - L80 `def _write_api_failure_log`
  - L96 `def _write_api_error_log`
  - L116 `def _runtime_tool_execute_http_status`：Map registered-tool execution payloads to HTTP status codes.
  - L149 `class ChatRequest`
  - L155 `class ConversationFeedbackRequest`
  - L164 `class RegisteredToolExecuteRequest`
  - L176 `class FeedbackRepairApplyRequest`
  - L182 `class RuntimeApprovalPolicyRequest`
  - L187 `class RuntimeToolProfileRequest`
  - L194 `class DeleteRuntimeCapabilityRequest`
  - L198 `class AgentStudioRequest`
  - L205 `class TaskInstructionUpdateRequest`
  - L211 `class KnowledgeQueryRequest`
  - L218 `class AgentStudioSecretRequest`
  - L223 `class VideoGenerationSetupRequest`
  - L227 `class ClientErrorRequest`
  - L235 `class ArtifactEditRequest`
  - L242 `class ArtifactProposalActionRequest`
  - L247 `class ArtifactUploadItem`
  - L253 `class ArtifactUploadJsonRequest`
  - L257 `class AgentStudioModelSelectionRequest`
  - L270 `class CommandSetUpdateRequest`
  - L279 `class AgentStudioResumeRunRequest`
  - L284 `class ResumeRequest`
  - L292 `async def runtime_bootstrap_on_startup`
  - L306 `async def runtime_bootstrap`
  - L311 `async def runtime_bootstrap_state`
  - L316 `async def home`
  - L334 `async def runtime_settings_home`
  - L347 `async def graph_runtime_home`
  - L361 `async def runtime_console_home`
  - L375 `async def execution_monitor_home`
  - L388 `async def runtime_console_sources`
  - L393 `async def runtime_console_read`
  - L397 `def _graph_runtime_schedule_payload`
  - L427 `async def graph_runtime_state`
  - L478 `async def graph_runtime_pause_schedule`
  - L483 `async def graph_runtime_resume_schedule`
  - L488 `async def graph_runtime_schedule_history`
  - L495 `async def knowledge_home`
  - L508 `async def knowledge_status`
  - L513 `async def knowledge_documents`
  - L518 `async def knowledge_upload`
  - L544 `async def knowledge_query`
  - L555 `async def agent_studio_home`
  - L575 `def _read_artifact_registry`
  - L578 `def _write_artifact_registry`
  - L582 `async def agent_studio_artifacts`
  - L585 `def _store_uploaded_artifact_items`
  - L619 `async def agent_studio_upload_artifacts`
  - L632 `async def agent_studio_upload_artifacts_json`
  - L649 `async def agent_studio_artifact_edit_proposal`
  - L663 `async def download_runtime_file`
  - L677 `async def agent_studio_artifact_edit_download`
  - L688 `async def agent_studio_artifact_edit_confirm`
  - L700 `async def agent_studio_artifact_edit_cancel`
  - L706 `async def agent_studio_artifact_edit_revise`
  - L720 `async def agent_studio_model_selection_state`
  - L725 `async def agent_studio_model_selection_update`
  - L731 `async def agent_studio_command_set`
  - L736 `async def agent_studio_command_set_update`
  - L756 `async def agent_studio_sessions`
  - L761 `async def agent_studio_create_session`
  - L768 `async def agent_studio_session_snapshot`
  - L773 `async def agent_studio_rename_session`
  - L779 `async def agent_studio_runtime_tools`
  - L784 `async def runtime_settings`
  - L794 `async def runtime_settings_tool_approval`
  - L804 `async def agent_studio_runtime_tool_profiles`
  - L809 `async def agent_studio_save_runtime_tool_profile`
  - L831 `async def agent_studio_execute_runtime_tool`
  - L856 `async def agent_studio_apply_feedback_repair`
  - L872 `async def agent_studio_delete_agent`
  - L882 `async def agent_studio_delete_task`
  - L892 `async def agent_studio_rebuild_task`
  - L902 `async def agent_studio_update_task_instruction`
  - L912 `async def agent_studio_delete_runtime_tool`
  - L923 `async def agent_studio_state`
  - L928 `async def agent_studio_message`
  - L964 `async def agent_studio_secret`
  - L977 `async def _apply_video_generation_setup`
  - L987 `async def agent_studio_video_generation_setup`
  - L991 `async def agent_studio_video_generation_setup_alias`
  - L995 `async def video_generation_setup_alias`
  - L999 `async def agent_studio_client_error`
  - L1018 `async def agent_studio_resume_run`
  - L1023 `async def version`
  - L1028 `async def chat`
  - L1036 `async def conversation_feedback`
  - L1064 `async def resume`
  - L1100 `async def events`

#### auxiliary_brain

- `auxiliary_brain/__init__.py`（5 行）：Auxiliary brain package.
  - 无显式顶层类/函数。

- `auxiliary_brain/capability_acquisition/__init__.py`（15 行）：capability_acquisition/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `auxiliary_brain/capability_acquisition/acquisition_router.py`（1263 行）：capability_acquisition/acquisition_router.py 模块，围绕 acquisition router 提供结构化运行、配置、验证或桥接能力。
  - L26 `class TemplateMatch`
  - L31 `class RuntimeCapabilityGapImplementer`：Generic runtime capability implementation lifecycle.
  - L41 `  def __init__`
  - L54 `  def implement_if_requested`：Run the runtime capability acquisition pipeline.
  - L327 `  def _load_templates`：Load runtime capability templates from runtime-owned storage.
  - L337 `  def _extract_need_capability_event_contract`：Read ai_core's authoritative planning contract from evidence.
  - L355 `  def _extract_requested_identity_contract`：Extract capability identity requirements declared by the user prompt.
  - L395 `  def _merge_identity_contract_into_template`
  - L414 `  def _plan_capability_with_runtime_planner`：Invoke a runtime-configured planner hook for template-less acquisition.
  - L486 `  def _allow_template_fallback`
  - L489 `  def _load_runtime_generated_default_planner`：Load the runtime-owned default planner when no env hook is set.
  - L508 `  def _persist_runtime_planned_template`：Persist a planned template into runtime/generated for future Template First use.
  - L542 `  def _runtime_planner_template_contract`
  - L550 `  def _validate_runtime_template_shape`
  - L566 `  def _classify_runtime_native_acquisition`：Classify whether acquisition can proceed without external evidence.
  - L614 `  def _runtime_self_repair`
  - L640 `  def _select_template`
  - L669 `  def _resolve_dependencies`
  - L705 `  def _module_available`
  - L711 `  def _clean_subprocess_env`：Return a stable validation environment for generated artifacts.
  - L739 `  def _python_executable_candidates`：Return Python executables suitable for sandbox validation.
  - L755 `  def _run_isolated_python`：Run a generated-artifact validation command with debugger isolation.
  - L798 `  def _pip_install`
  - L811 `  def _write_artifact`
  - L876 `  def _verify_capability_match`：Verify that the generated artifact really implements the matched capability.
  - L951 `  def _validate_artifact`
  - L1000 `  def _artifact_registration_quality_gate`：Reject blueprint/stub artifacts before registration.
  - L1050 `  def _schema_is_specific`
  - L1064 `  def _artifact_source_text`
  - L1076 `  def _execute_verification_run`
  - L1103 `  def _load_function`
  - L1115 `  def _matches_expectations`
  - L1128 `  def _write_test_report`
  - L1141 `  def _write_verification_report`
  - L1149 `  def _register_artifact`
  - L1247 `  def _load_registry`
  - L1256 `  def _safe_name`
  - L1259 `  def _safe_relative_path`

- `auxiliary_brain/capability_acquisition/blueprint_generator.py`（3 行）：capability_acquisition/blueprint_generator.py 模块，围绕 blueprint generator 提供结构化运行、配置、验证或桥接能力。
  - L1 `class CapabilitySpecGenerator`
  - L2 `  def generate`

- `auxiliary_brain/capability_acquisition/code_generator.py`（539 行）：capability_acquisition/code_generator.py 模块，围绕 code generator 提供结构化运行、配置、验证或桥接能力。
  - L8 `class RuntimeBlueprintArtifactGenerator`：Materialize runtime capability blueprints into sandboxable artifacts.
  - L19 `  def materialize`
  - L106 `  def _looks_like_basic_smtp_request`
  - L110 `  def _smtp_schemas`
  - L150 `  def _smtp_verification_input`
  - L159 `  def _smtp_files`
  - L311 `  def _valid_files`
  - L314 `  def _schema_or_default`
  - L340 `  def _closed_schema`
  - L350 `  def _files_look_like_stub`
  - L354 `  def _allows_runtime_native_materialization`
  - L363 `  def _generic_verification_input`
  - L366 `  def _generic_stateful_files`
  - L516 `  def _neutral_files`
  - L538 `  def _safe_name`

- `auxiliary_brain/capability_acquisition/execution_verifier.py`（5 行）：capability_acquisition/execution_verifier.py 模块，围绕 execution verifier 提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `auxiliary_brain/capability_acquisition/implementation_planner.py`（18 行）：capability_acquisition/implementation_planner.py 模块，围绕 implementation planner 提供结构化运行、配置、验证或桥接能力。
  - L5 `class CapabilityResolver`
  - L6 `  def __init__`
  - L7 `  async def ensure_capabilities`
  - L17 `  async def install_start_verify`

- `auxiliary_brain/capability_acquisition/registry_manager.py`（31 行）：capability_acquisition/registry_manager.py 模块，围绕 registry manager 提供结构化运行、配置、验证或桥接能力。
  - L9 `class RuntimeCapabilityRegistryManager`：Registration guard for auxiliary_brain capability acquisition.
  - L15 `  def __init__`
  - L18 `  def assert_registerable`
  - L24 `  def normalize_status`

- `auxiliary_brain/capability_acquisition/repair_coordinator.py`（67 行）：capability_acquisition/repair_coordinator.py 模块，围绕 repair coordinator 提供结构化运行、配置、验证或桥接能力。
  - L12 `class AuxiliaryCapabilityRepairCoordinator`：Auxiliary-brain owner for runtime capability repair requests.
  - L22 `  def __init__`
  - L27 `  def prepare_patch_lifecycle`
  - L56 `  def _load_request`
  - L66 `  def _safe_name`

- `auxiliary_brain/capability_acquisition/sandbox_validator.py`（71 行）：capability_acquisition/sandbox_validator.py 模块，围绕 sandbox validator 提供结构化运行、配置、验证或桥接能力。
  - L8 `class RuntimeCapabilitySandboxValidator`：Static registration-quality validator for generated runtime artifacts.
  - L17 `  def validate_registration_quality`
  - L51 `  def _schema_is_specific`
  - L63 `  def _source_text`

- `auxiliary_brain/capability_acquisition/tools/__init__.py`（0 行）：tools/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `auxiliary_brain/capability_acquisition/tools/browser_automation_blueprint.py`（158 行）：tools/browser_automation_blueprint.py 模块，围绕 browser automation blueprint 提供结构化运行、配置、验证或桥接能力。
  - L10 `class BrowserAutomationBlueprintBuilder`：Generic browser automation blueprint writer.
  - L35 `  def __init__`
  - L39 `  def create_blueprint`
  - L85 `  def _runtime_metadata`
  - L115 `  def _default_credential_policy`
  - L123 `  def _default_safety_policy`
  - L132 `  def _default_playwright_generation`
  - L140 `  def _readme`
  - L147 `  def _safe_placeholder_py`

- `auxiliary_brain/capability_acquisition/tools/generic_web_extract_artifact.py`（341 行）：tools/generic_web_extract_artifact.py 模块，围绕 generic web extract artifact 提供结构化运行、配置、验证或桥接能力。
  - L8 `class GenericWebExtractArtifactFactory`：Build a deterministic generic web extraction runtime tool artifact.
  - L18 `  def build_artifact`
  - L87 `  def _compact_candidate`
  - L97 `  def _safe_name`
  - L101 `  def _tool_source`

- `auxiliary_brain/capability_acquisition/tools/runtime_generated_tool_installer.py`（288 行）：tools/runtime_generated_tool_installer.py 模块，围绕 runtime generated tool installer 提供结构化运行、配置、验证或桥接能力。
  - L16 `class RuntimeGeneratedToolInstaller`：Installs runtime-generated tool artifacts into runtime/generated/tools.
  - L27 `  def __init__`
  - L40 `  def install_from_step`
  - L57 `  def install_artifact`
  - L225 `  def _build_sandbox_artifact`
  - L256 `  def _verification_input`
  - L263 `  def _extract_artifact`
  - L275 `  def _load_registry`
  - L281 `  def _safe_child_path`
  - L287 `  def _safe_name`

- `auxiliary_brain/capability_acquisition/tools/runtime_primitive_tool_factory.py`（106 行）：tools/runtime_primitive_tool_factory.py 模块，围绕 runtime primitive tool factory 提供结构化运行、配置、验证或桥接能力。
  - L11 `class RuntimePrimitiveToolFactory`：Builds executable tool artifacts from runtime policy templates.
  - L18 `  def build_artifact`
  - L50 `  def _select_template`
  - L62 `  def _templates`
  - L78 `  def _matches_tokens`
  - L88 `  def _contract_text`

- `auxiliary_brain/capability_acquisition/tools/runtime_tool_artifact_generator.py`（220 行）：tools/runtime_tool_artifact_generator.py 模块，围绕 runtime tool artifact generator 提供结构化运行、配置、验证或桥接能力。
  - L12 `class RuntimeToolArtifactGenerator`：Generic runtime tool artifact generator.
  - L25 `  def __init__`
  - L29 `  async def generate_artifact`
  - L43 `  async def repair_artifact`
  - L67 `  async def _generate`
  - L160 `  def _code_generation_route`
  - L168 `  def artifact_schema`

- `auxiliary_brain/capability_acquisition/tools/runtime_tool_artifact_validator.py`（104 行）：tools/runtime_tool_artifact_validator.py 模块，围绕 runtime tool artifact validator 提供结构化运行、配置、验证或桥接能力。
  - L12 `class RuntimeToolArtifactValidator`：Validates runtime-generated Python tool artifacts generically.
  - L26 `  def validate_python_file`
  - L97 `  def _assigned_names`

- `auxiliary_brain/capability_acquisition/tools/runtime_tool_registry.py`（210 行）：tools/runtime_tool_registry.py 模块，围绕 runtime tool registry 提供结构化运行、配置、验证或桥接能力。
  - L15 `class RuntimeToolRegistry`：Generic runtime tool registry.
  - L23 `  def __init__`
  - L39 `  def load_registry`
  - L45 `  def save_registry`
  - L48 `  def find_by_capability`
  - L70 `  def _is_executable_tool_record`：Return True only for records that can be passed to the generic runner.
  - L101 `  def create_missing_tool_spec`
  - L209 `  def _safe_name`

- `auxiliary_brain/capability_acquisition/tools/sandbox_verifier.py`（216 行）：tools/sandbox_verifier.py 模块，围绕 sandbox verifier 提供结构化运行、配置、验证或桥接能力。
  - L16 `class SandboxVerificationResult`
  - L24 `class SandboxVerifier`：Static and compile-time verifier for runtime-generated artifacts.
  - L51 `  def verify_tool_artifact`
  - L56 `  def verify_python_source`
  - L103 `  def _check_syntax`
  - L110 `  def _check_static_policy`
  - L142 `  def _declared_python_packages`
  - L153 `  def _expected_entrypoint`
  - L158 `  def _check_entrypoint`
  - L189 `  def _runtime_variables`
  - L197 `  def _check_dynamic_value_hardcoding`
  - L204 `  def _check_compile`
  - L214 `  def write_report`

- `auxiliary_brain/capability_acquisition/tools/tool_blueprint_builder.py`（172 行）：tools/tool_blueprint_builder.py 模块，围绕 tool blueprint builder 提供结构化运行、配置、验证或桥接能力。
  - L10 `class ToolBlueprintBuilder`：Generic runtime tool blueprint builder.
  - L20 `  def __init__`
  - L28 `  def create_blueprint`
  - L70 `  def _runtime_metadata`
  - L88 `  def _default_input_schema`
  - L99 `  def _default_output_schema`
  - L111 `  def _default_safety`
  - L120 `  def _default_implementation_plan`
  - L129 `  def _placeholder_tool_py`
  - L143 `  def _readme`
  - L150 `  def _register`
  - L171 `  def _safe_name`

- `auxiliary_brain/capability_acquisition/tools/tool_code_generation_request.py`（47 行）：tools/tool_code_generation_request.py 模块，围绕 tool code generation request 提供结构化运行、配置、验证或桥接能力。
  - L10 `class ToolCodeGenerationRequestBuilder`
  - L11 `  def __init__`
  - L15 `  def create_request`
  - L46 `  def _safe_name`

- `auxiliary_brain/capability_acquisition/trace_logger.py`（50 行）：capability_acquisition/trace_logger.py 模块，围绕 trace logger 提供结构化运行、配置、验证或桥接能力。
  - L11 `class CapabilityAcquisitionTraceLogger`：JSONL trace logger for ai_core -> auxiliary_brain capability acquisition.
  - L18 `  def __init__`
  - L21 `  def record`
  - L35 `  def write_snapshot`
  - L42 `  def _json_safe`
  - L49 `  def _safe_name`

- `auxiliary_brain/delegation/__init__.py`（3 行）：delegation/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `auxiliary_brain/delegation/delegation_runtime.py`（3210 行）：delegation/delegation_runtime.py 模块，围绕 delegation runtime 提供结构化运行、配置、验证或桥接能力。
  - L23 `class AgentDelegationRuntime`：Coordinates delegation without executing participant work itself.
  - L32 `  def __init__`
  - L42 `  async def execute_task`
  - L47 `  async def _execute_task_with_selected`
  - L346 `  async def _resume_registered_tool_confirmation`：Resume a runtime-registered tool approval using the same tool path.
  - L508 `  async def _resume_feedback_repair_confirmation`：Resume a paused feedback-repair proposal without primary checkpoints.
  - L695 `  def _submitted_confirmation`
  - L715 `  def _submitted_trust_request`
  - L743 `  def _approval_trusted`
  - L754 `  def _persist_approval_trust`
  - L775 `  def _blocked_dependency_ids`
  - L792 `  def _dependency_blocked_result`
  - L809 `  async def reoptimize_result`：Re-synthesize an existing run without restarting completed work.
  - L871 `  async def resume_task`：Resume the same delegation run from its paused participant checkpoint.
  - L1196 `  def _collect_generated_files`
  - L1209 `  def _participant_identity`
  - L1212 `  def _participant_name`
  - L1215 `  def _participant_objective`
  - L1218 `  def _build_task_mind_graph`：Create the top-level task mind graph before executing agents.
  - L1228 `  def _record_global_mind_graph_progress`
  - L1240 `  def _participants_in_mind_graph_order`
  - L1253 `  def _mind_graph_node_for_participant`
  - L1260 `  def _build_participant_dependency_plan`：Build a coordination-only dependency plan for participant execution.
  - L1315 `  def _build_participant_shared_context`
  - L1391 `  def _terminal_results_for_synthesis`：Return only terminal graph outputs for final answer synthesis.
  - L1414 `  def _merged_runtime_parameters`
  - L1422 `  def _compact_parameter_contract`
  - L1439 `  def _apply_task_runtime_parameters_to_selected`：Apply current task-run parameters to participant copies only.
  - L1462 `  def _collect_missing_agent_parameter_fields`
  - L1494 `  def _runtime_field_already_bound`：Return True when a missing field is already satisfied in run state.
  - L1527 `  def _runtime_value_for_field`：Look up a run-scoped value for one participant field.
  - L1559 `  def _fill_registered_tool_input_from_runtime`：Last-mile schema-value reconciliation before asking the user.
  - L1583 `  def _capability_required_fields`：Build missing input fields from runtime capability metadata.
  - L1620 `  def _is_blocking_agent_parameter_field`：Return True only for explicitly blocking runtime parameters.
  - L1664 `  def _participant_dependency_ids`
  - L1670 `  def _field_text`
  - L1673 `  def _field_accepts_upstream_material`
  - L1677 `  def _field_is_runtime_default_output_location`
  - L1681 `  def _can_defer_field_to_dependency_output`
  - L1703 `  def _contract_fields`
  - L1708 `  def _field_name`
  - L1711 `  def _extract_primary_material_from_result`
  - L1721 `  def _resolve_task_variable_placeholders_for_participant`：Resolve task dataflow placeholders in participant runtime values.
  - L1762 `  def _task_variable_reference_map`
  - L1817 `  def _task_step_aliases_for_result`：Return stable workflow-step aliases for a completed result.
  - L1860 `  def _resolve_task_variable_templates`
  - L1881 `  def _normalize_task_variable_key`
  - L1888 `  def _dependency_material_text`
  - L1903 `  def _bind_dependency_outputs_to_participant`
  - L1932 `  def _looks_like_file_material_contract`
  - L1942 `  def _value_for_field_role`
  - L1954 `  def _first_scalar`
  - L1970 `  def _safe_download_filename`
  - L1979 `  async def _try_execute_generated_capability`
  - L2041 `  def _ensure_participant_structural_context`：Ensure delegated registered-tool participants carry source spans.
  - L2069 `  def _ensure_task_runtime_parameters_for_participant`：Hydrate a participant copy with durable task-run parameters.
  - L2099 `  async def _execute_registered_tool_capability`
  - L2275 `  def _build_feedback_repair_pending_action`：Create a user interaction for a generic repair route.
  - L2345 `  def _repair_input_fields`
  - L2365 `  def _build_registered_tool_input`
  - L2369 `  def _missing_registered_tool_inputs`
  - L2374 `  def _configuration_fields_for_registered_tool`
  - L2396 `  def _registered_tool_final_answer`
  - L2425 `  async def _execute_image_generation_capability`
  - L2494 `  async def _execute_video_generation_capability`
  - L2554 `  def _try_execute_file_material_generation`
  - L2601 `  def _generated_files_from_result`
  - L2608 `  def _try_return_dependency_material`
  - L2638 `  def _uses_uploaded_artifact_runtime`
  - L2650 `  def _uses_uploaded_artifact_runtime_for_task`
  - L2659 `  def _apply_agent_parameter_values`
  - L2668 `  def _peer_results_for_participant`
  - L2683 `  def _safe_peer_result`：Return a strict JSON object for dependent-agent context.
  - L2705 `  def _compact_text`：Return a short, JSON-safe text preview for peer-agent context.
  - L2722 `  def _result_key`
  - L2725 `  def _dedupe_result_payloads`：Keep the latest result per participant and prefer non-paused results.
  - L2753 `  def _to_agent_results`
  - L2767 `  def _clear_waiting_fields`
  - L2771 `  def _sanitize_result_payload`
  - L2781 `  def _is_generated_dataflow_step`
  - L2793 `  async def _execute_intermediate_step_with_progress`
  - L2806 `  async def _execute_agent_request_with_progress`
  - L2817 `  async def _resume_agent_request_with_progress`
  - L2829 `  def _build_primary_runtime_progress_bridge`：Mirror primary-runtime node telemetry into the delegation run.
  - L2874 `  def _map_primary_runtime_event`
  - L2937 `  def _task_source_material`：Collect original task text for structural binding without capability rules.
  - L2963 `  def _extract_structural_values_from_material`：Return generic structural values extracted from original user material.
  - L2975 `  def _record_progress`
  - L2986 `  def _hydrate_runtime_bindings_for_task`：Recover durable agent capability bindings before a task run.
  - L3025 `  def _load_durable_participant_indexes`
  - L3045 `  def _merge_runtime_binding_fields`
  - L3075 `  def _fresh_task_participants`：Return task-run copies with no persisted runtime values.
  - L3104 `  def _select_participants`
  - L3133 `  def _participants_from_task_graph`
  - L3176 `  def _dedupe_participants_for_execution`：Keep one participant per reusable capability identity.
  - L3201 `  def _participant_reuse_key`
  - L3209 `  def _now`

- `auxiliary_brain/delegation/task_mind_graph.py`（324 行）：delegation/task_mind_graph.py 模块，围绕 task mind graph 提供结构化运行、配置、验证或桥接能力。
  - L8 `class TaskMindGraphNode`
  - L17 `class TaskMindGraphBuilder`：Builds a coordination mind-map for multi-agent task execution.
  - L26 `  def build`
  - L122 `  def _relation_plan`
  - L235 `  def _task_participant_order`
  - L251 `  def _normalize_dependency_map`
  - L278 `  def _has_cycle`
  - L295 `  def _execution_groups`
  - L317 `  def _participant_id`
  - L320 `  def _participant_name`
  - L323 `  def _participant_objective`

- `auxiliary_brain/feedback_repair/__init__.py`（10 行）：Auxiliary-brain feedback-repair namespace.
  - 无显式顶层类/函数。

- `auxiliary_brain/parameters/__init__.py`（0 行）：parameters/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `auxiliary_brain/parameters/agent_parameter_contract.py`（528 行）：parameters/agent_parameter_contract.py 模块，围绕 agent parameter contract 提供结构化运行、配置、验证或桥接能力。
  - L11 `class ParameterSlot`
  - L20 `class AgentParameterContractService`：Build and validate participant parameter contracts.
  - L29 `  def __init__`
  - L33 `  async def build_contract_runtime`：Create a parameter contract at runtime from the agent definition.
  - L137 `  def _looks_like_self_contained_runtime_observation`：Detect requests that can be answered from runtime state alone.
  - L152 `  def _looks_like_open_capability`：Detect reusable capability definitions without domain keywords.
  - L174 `  def _fallback_contract_for_objective`：Build a safe generic fallback when runtime model inference fails.
  - L194 `  def _content_output_parameters`：Generic parameter shape for user-facing content deliverables.
  - L218 `  def _ensure_content_output_contract_shape`：Enrich sparse model-inferred contracts for content output agents.
  - L260 `  def _looks_like_content_output_capability`
  - L268 `  def _open_capability_fallback_contract`
  - L285 `  def build_contract`
  - L311 `  def _normalize_contract_result`
  - L336 `  def _parameter_record`
  - L347 `  def _safe_name`
  - L351 `  def missing_parameters`
  - L367 `  def apply_values`
  - L409 `  def to_missing_input_fields`
  - L435 `  def _lookup_runtime_parameter`：Find a task-run value for a parameter using generic scoped aliases.
  - L472 `  def _load_config`
  - L482 `  def _match_template`
  - L492 `  def _extract_known_values`
  - L512 `  def _normalize_list`

- `auxiliary_brain/protocols/__init__.py`（0 行）：protocols/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `auxiliary_brain/protocols/runtime_protocol.py`（58 行）：protocols/runtime_protocol.py 模块，围绕 runtime protocol 提供结构化运行、配置、验证或桥接能力。
  - L8 `class PrimaryRuntimeExecutionPolicy`：Policy passed from the auxiliary layer to the primary runtime.
  - L28 `class PrimaryRuntimeRequestEnvelope`：Canonical auxiliary_brain -> ai_core request envelope.
  - L46 `  def to_prompt_payload`

- `auxiliary_brain/runtime.py`（14 行）：auxiliary_brain/runtime.py 模块，围绕 runtime 提供结构化运行、配置、验证或桥接能力。
  - L6 `def new_id`：Return a compact runtime identifier.

- `auxiliary_brain/runtime_codegen/__init__.py`（1 行）：Auxiliary runtime code analysis helpers used outside ai_core generation ownership.
  - 无显式顶层类/函数。

- `auxiliary_brain/runtime_codegen/dynamic_value_hardcode_detector.py`（95 行）：runtime_codegen/dynamic_value_hardcode_detector.py 模块，围绕 dynamic value hardcode detector 提供结构化运行、配置、验证或桥接能力。
  - L8 `class DynamicValueHardcodeDetector`：Detect hardcoded runtime values in generated Python source.
  - L17 `  def detect`
  - L42 `  def _normalize`
  - L50 `  def _string_literals`
  - L68 `  def _should_check_alias`
  - L79 `  def _contains_hardcoded_value`

- `auxiliary_brain/runtime_codegen/runtime_variable_inferencer.py`（196 行）：runtime_codegen/runtime_variable_inferencer.py 模块，围绕 runtime variable inferencer 提供结构化运行、配置、验证或桥接能力。
  - L9 `class RuntimeVariable`
  - L16 `class RuntimeVariableInferencer`：Infer dynamic runtime variables from intent/workflow/request payloads.
  - L55 `  def infer`
  - L86 `  def _visit`
  - L119 `  def _schema_variables`
  - L140 `  def _add_variable`
  - L156 `  def _safe_name`
  - L162 `  def _aliases`
  - L190 `  def _is_dynamic_value`

- `auxiliary_brain/storage/__init__.py`（3 行）：storage/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `auxiliary_brain/storage/json_store.py`（75 行）：storage/json_store.py 模块，围绕 json store 提供结构化运行、配置、验证或桥接能力。
  - L9 `class JsonStore`
  - L10 `  def __init__`
  - L13 `  def ensure_workspace`
  - L28 `  def write_json`
  - L35 `  def read_json`
  - L45 `  def delete_json`
  - L55 `  def list_json`

- `auxiliary_brain/studio/__init__.py`（3 行）：studio/__init__.py 模块，围绕   init   提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `auxiliary_brain/studio/command_router.py`（127 行）：studio/command_router.py 模块，围绕 command router 提供结构化运行、配置、验证或桥接能力。
  - L11 `class RoutedCommand`
  - L17 `class StudioCommandRouter`：Configuration-backed command router for studio instructions.
  - L20 `  def __init__`
  - L25 `  def route`：Route user text through the effective command registry.
  - L41 `  def _load_config`
  - L44 `  def reload`
  - L47 `  def _registry`
  - L53 `  def _match_registry`
  - L61 `  def _extract_name_for_action`
  - L70 `  def _matches`
  - L86 `  def _extract_named_value`
  - L110 `  def _extract_execute_name`
  - L116 `  def _extract_feedback_target`

- `auxiliary_brain/studio/instruction_workflow_planner.py`（340 行）：studio/instruction_workflow_planner.py 模块，围绕 instruction workflow planner 提供结构化运行、配置、验证或桥接能力。
  - L10 `class PlannedWorkflow`
  - L17 `class InstructionWorkflowPlanner`：Build a task graph from a runtime semantic plan.
  - L27 `  def plan`
  - L256 `  def _generated_parameter_contract_from_step`
  - L267 `  def _task_contracts_from_step`
  - L285 `  def _semantic_steps`
  - L289 `  def _objective_from_step`
  - L303 `  def _find_participant`
  - L313 `  def _match_participants_by_declared_names`
  - L324 `  def _dedupe`
  - L336 `  def _participant_id`
  - L339 `  def _participant_name`

- `auxiliary_brain/studio/runtime_semantic_planner.py`（106 行）：studio/runtime_semantic_planner.py 模块，围绕 runtime semantic planner 提供结构化运行、配置、验证或桥接能力。
  - L10 `class RuntimeSemanticPlanner`：Runtime semantic decomposition facade.
  - L20 `  def __init__`
  - L23 `  def build_plan`
  - L31 `  async def _build_plan_async`

- `auxiliary_brain/studio/service.py`（2510 行）：studio/service.py 模块，围绕 service 提供结构化运行、配置、验证或桥接能力。
  - L34 `class AgentStudioService`：Studio service for managing participants, task graphs, and delegation state.
  - L37 `  def __init__`
  - L64 `  async def handle_message`
  - L169 `  async def _handle_direct_image_generation`
  - L208 `  async def _handle_direct_video_generation`
  - L253 `  def _direct_ephemeral_answer`
  - L260 `  def _compact_final_answer`
  - L263 `  async def _try_reused_task_execution`
  - L369 `  def _resolve_bare_task_name`
  - L384 `  def list_command_set`
  - L393 `  def update_command_set`
  - L407 `  async def _maybe_handle_artifact_edit_message`：Create a reviewable edit proposal for an uploaded artifact when the user asks to change or regenerate a file.
  - L488 `  def _looks_like_artifact_edit_request`：Generic command-shape detection for file modification requests.
  - L517 `  async def handle_feedback`
  - L597 `  def _latest_task_name`
  - L604 `  def _resolve_task_name`
  - L623 `  def _latest_run_for_task`
  - L632 `  def delete_participant`
  - L642 `  def delete_task_graph`
  - L653 `  def set_task_schedule_enabled`：Pause or resume a durable schedule policy on a task graph.
  - L687 `  def task_execution_history`：Return recent scheduler/runtime observations for one task graph.
  - L722 `  def delete_runtime_capability`
  - L725 `  def _structural_source_runtime_context`
  - L766 `  def snapshot`
  - L785 `  async def create_participant`
  - L856 `  def _hydrate_task_step_bindings_from_participants`：Copy durable participant binding metadata into task steps.
  - L893 `  def _safe_task_asset_name`
  - L897 `  def _instruction_fingerprint`
  - L900 `  def _next_task_revision_metadata`：Create a generic lifecycle identity for a task graph revision.
  - L943 `  def _write_task_revision_asset`
  - L952 `  def _task_instruction_changed`
  - L963 `  def _rebuild_task_graph_from_current_instruction`：Rebuild a task's own graph/plan when its source instruction changed.
  - L983 `  def rebuild_task_graph`
  - L996 `  def update_task_graph_instruction`：Edit a task by creating a new active graph/plan revision.
  - L1010 `  def create_task_graph`
  - L1116 `  async def _maybe_execute_direct_participant_invocation`：Execute a one-off task when the text names an existing participant.
  - L1141 `  def _find_participant_mentioned_in_message`
  - L1165 `  def _contains_named_entity`
  - L1173 `  def _create_direct_participant_task_graph`
  - L1264 `  def _extract_participant_schema_parameters_from_instruction`：Extract values for fields declared by the participant contract.
  - L1298 `  def _extract_named_value_from_instruction`
  - L1336 `  async def execute_task`
  - L1438 `  async def resume_run`
  - L1546 `  def _execution_payload_only_ids`：Return executable payload participants for control-plane task graphs.
  - L1584 `  def _task_graph_with_payload_only_participants`
  - L1594 `  def _participants_from_task_graph`：Rebuild task-scoped generated participants when they are not durable agents.
  - L1644 `  def _normalize_missing_inputs`
  - L1720 `  def _paused_message`
  - L1731 `  def _extract_runtime_parameters_from_instruction`：Extract explicit task-run parameters from user-authored text.
  - L1796 `  def _extract_step_scoped_runtime_parameters_from_tasks`：Create participant-scoped runtime values from planned step fragments.
  - L1836 `  def _extract_named_parameter_blocks_from_instruction`：Extract parameter blocks addressed to a named participant.
  - L1899 `  def _normalize_parameter_block_target`
  - L1906 `  def _match_parameter_block_participant`
  - L1918 `  def _write_scoped_parameter_values`
  - L1943 `  def _preflight_runtime_parameters`：Resolve pre-execution requirements through typed context layers.
  - L1971 `  def _build_preflight_resolution_context`
  - L2015 `  def _collect_bound_resource_refs`
  - L2034 `  def _collect_execution_policy_values`
  - L2042 `  def _runtime_field_key`
  - L2045 `  def _preflight_uploaded_artifact_parameters`：Inspect uploaded artifacts before delegating execution.
  - L2118 `  def _build_uploaded_artifact_contract`
  - L2150 `  def _resolve_uploaded_artifact_parameter_aliases`：Map task/agent scoped values onto uploaded callable field names.
  - L2181 `  def _participant_scoped_runtime_values`
  - L2216 `  def _best_runtime_value_key_for_field`
  - L2238 `  def _value_present_for_field`
  - L2247 `  def _runtime_field_norm`
  - L2250 `  def _runtime_field_tokens`
  - L2256 `  def _derive_execution_objective`：Extract the participant's reusable work objective from a creation command.
  - L2300 `  def _resolve_uploaded_artifacts_for_instruction`：Bind explicit UI artifacts and filename references in the instruction.
  - L2310 `  def _normalize_uploaded_artifacts`
  - L2313 `  def _parameter_contract_schema_only`：Store only parameter schema on the agent profile.
  - L2327 `  def _runtime_parameters_from_contract`
  - L2341 `  def _ensure_community`
  - L2357 `  def _update_community`
  - L2380 `  def _select_participants_for_instruction`
  - L2394 `  def _dedupe_selected_participants`
  - L2411 `  def _participant_reuse_key`
  - L2420 `  def _derive_execution_controller_participant_ids`：Identify task participants that only define durable execution timing.
  - L2447 `  def _emit_schedule_observation`：Write operator-visible scheduler observations without affecting execution.
  - L2464 `  def _extract_schedule_policy_from_instruction`：Extract a generic durable execution policy from user language.
  - L2487 `  def _extract_generic_interval_seconds`
  - L2509 `  def _now`

- `auxiliary_brain/studio/structural_step_planner.py`（413 行）：studio/structural_step_planner.py 模块，围绕 structural step planner 提供结构化运行、配置、验证或桥接能力。
  - L9 `class StructuralStepPlanner`：Builds a conservative fallback graph from declared runtime objects.
  - L30 `  def __init__`
  - L34 `  def build_steps`
  - L144 `  def _parameter_contract_from_fragment`：Infer explicitly requested runtime inputs from generic prompt shape.
  - L189 `  def _split_requested_input_names`
  - L198 `  def _normalize_parameter_name`
  - L204 `  def _capability_profile_from_fragment`：Return a platform capability hint when the instruction names one.
  - L242 `  def _input_contract`
  - L251 `  def _output_contract`
  - L258 `  def _numbered_step_fragments`：Extract explicitly numbered instruction fragments.
  - L286 `  def _declared_step_dependencies`：Resolve explicit references to earlier numbered steps.
  - L306 `  def _load_config`
  - L318 `  def _strip_wrappers`
  - L327 `  def _split_fragments`
  - L335 `  def _referenced_participants`
  - L350 `  def _should_keep_generated_fragment`
  - L376 `  def _compact_fragment_label`
  - L385 `  def _remove_redundant_generated_steps`
  - L398 `  def _dedupe`
  - L409 `  def _participant_id`
  - L412 `  def _participant_name`

#### runtime_assets

- `runtime_assets/seeds/capability_planners/default_capability_planner.py`（371 行）：capability_planners/default_capability_planner.py 模块，围绕 default capability planner 提供结构化运行、配置、验证或桥接能力。
  - L12 `def plan`：Runtime-asset default planner for missing-template acquisition.
  - L63 `def _try_model_planner`
  - L99 `def _resolve_planner_model`：Resolve the local planner model from runtime selection before defaults.
  - L125 `def _candidate_project_roots`
  - L143 `def _call_ollama_json_planner`
  - L179 `def _model_prompt`
  - L220 `def _compact_model_prompt`
  - L260 `def _neutral_blueprint`
  - L286 `def _schema_from_event_contract`
  - L303 `def _compact_event_contract`
  - L329 `def _safe_name`
  - L332 `def _compact_contract`
  - L345 `def _parse_json_object`
  - L359 `def _to_bool`

#### scripts

- `scripts/reset_runtime_data.py`（141 行）：Reset local test data for session and vector-memory tests.
  - L36 `def _safe_remove_path`
  - L48 `def _reset_sqlite`
  - L69 `def _reset_postgres`
  - L89 `def _reset_jsonl_files`
  - L95 `def main`

- `scripts/verify_task_revision_lifecycle.py`（57 行）：scripts/verify_task_revision_lifecycle.py 模块，围绕 verify task revision lifecycle 提供结构化运行、配置、验证或桥接能力。
  - L17 `def main`

- `scripts/verify_weather_dependency_imports.py`（6 行）：scripts/verify_weather_dependency_imports.py 模块，围绕 verify weather dependency imports 提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

#### tests

- `tests/verify_resume_registered_tool_participant.py`（111 行）：tests/verify_resume_registered_tool_participant.py 模块，围绕 verify resume registered tool participant 提供结构化运行、配置、验证或桥接能力。
  - L13 `class DummyPrimaryClient`
  - L14 `  async def synthesize_delegated_results`
  - L18 `async def main`

#### tools

- `tools/validate_source_package.py`（110 行）：tools/validate_source_package.py 模块，围绕 validate source package 提供结构化运行、配置、验证或桥接能力。
  - L40 `def iter_source_files`
  - L50 `def check_runtime_outputs_absent`
  - L59 `def check_stage_contract`
  - L69 `def check_domain_terms`
  - L85 `def check_python_syntax`
  - L97 `def main`

- `tools/verify_capability_acquisition_generic_isolation.py`（54 行）：tools/verify_capability_acquisition_generic_isolation.py 模块，围绕 verify capability acquisition generic isolation 提供结构化运行、配置、验证或桥接能力。
  - L11 `def assert_true`
  - L16 `def verify_new_capability_artifact_directory_is_cleaned`
  - L40 `def verify_generator_has_no_static_route_for_example_capability`
  - L47 `def main`

- `tools/verify_conversation_capability_acquisition.py`（99 行）：tools/verify_conversation_capability_acquisition.py 模块，围绕 verify conversation capability acquisition 提供结构化运行、配置、验证或桥接能力。
  - L42 `async def _run`
  - L46 `def main`
  - L74 `def cleanup_runtime_capability_outputs`

- `tools/verify_default_planner_neutrality.py`（26 行）：tools/verify_default_planner_neutrality.py 模块，围绕 verify default planner neutrality 提供结构化运行、配置、验证或桥接能力。
  - L6 `def _markers`
  - L16 `def main`

- `tools/verify_direct_gguf_import_precedence.py`（42 行）：tools/verify_direct_gguf_import_precedence.py 模块，围绕 verify direct gguf import precedence 提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `tools/verify_external_gguf_download_resolver.py`（34 行）：tools/verify_external_gguf_download_resolver.py 模块，围绕 verify external gguf download resolver 提供结构化运行、配置、验证或桥接能力。
  - L11 `def main`

- `tools/verify_feedback_repair_confirmation_checkpoint_english.py`（39 行）：tools/verify_feedback_repair_confirmation_checkpoint_english.py 模块，围绕 verify feedback repair confirmation checkpoint english 提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `tools/verify_feedback_repair_generic_boundary.py`（115 行）：tools/verify_feedback_repair_generic_boundary.py 模块，围绕 verify feedback repair generic boundary 提供结构化运行、配置、验证或桥接能力。
  - L35 `def _iter_text_files`
  - L45 `def verify_no_business_terms`
  - L57 `def verify_generic_behavior`
  - L108 `def main`

- `tools/verify_feedback_repair_phase2.py`（57 行）：tools/verify_feedback_repair_phase2.py 模块，围绕 verify feedback repair phase2 提供结构化运行、配置、验证或桥接能力。
  - L13 `def main`

- `tools/verify_feedback_repair_resume_checkpoint.py`（38 行）：tools/verify_feedback_repair_resume_checkpoint.py 模块，围绕 verify feedback repair resume checkpoint 提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `tools/verify_graph_runtime_viewer_observability.py`（67 行）：tools/verify_graph_runtime_viewer_observability.py 模块，围绕 verify graph runtime viewer observability 提供结构化运行、配置、验证或桥接能力。
  - L14 `def main`

- `tools/verify_local_model_auto_download_hook.py`（30 行）：tools/verify_local_model_auto_download_hook.py 模块，围绕 verify local model auto download hook 提供结构化运行、配置、验证或桥接能力。
  - L8 `class FakeDownloader`
  - L9 `  def download`

- `tools/verify_ollama_gguf_import_support.py`（40 行）：tools/verify_ollama_gguf_import_support.py 模块，围绕 verify ollama gguf import support 提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `tools/verify_phase21_repair_routing.py`（63 行）：tools/verify_phase21_repair_routing.py 模块，围绕 verify phase21 repair routing 提供结构化运行、配置、验证或桥接能力。
  - L11 `def main`

- `tools/verify_phase2_repair_and_deletion.py`（54 行）：tools/verify_phase2_repair_and_deletion.py 模块，围绕 verify phase2 repair and deletion 提供结构化运行、配置、验证或桥接能力。
  - L13 `def test_structural_source_context_repairs_truncated_structural_value`
  - L41 `def test_json_store_delete`

- `tools/verify_qwen35_local_defaults.py`（49 行）：tools/verify_qwen35_local_defaults.py 模块，围绕 verify qwen35 local defaults 提供结构化运行、配置、验证或桥接能力。
  - L13 `def assert_true`
  - L18 `def main`

- `tools/verify_repair_source_material_chain.py`（45 行）：tools/verify_repair_source_material_chain.py 模块，围绕 verify repair source material chain 提供结构化运行、配置、验证或桥接能力。
  - L8 `def main`

- `tools/verify_runtime_capability_pipeline.py`（93 行）：tools/verify_runtime_capability_pipeline.py 模块，围绕 verify runtime capability pipeline 提供结构化运行、配置、验证或桥接能力。
  - L36 `def main`
  - L67 `def cleanup_runtime_capability_outputs`

- `tools/verify_runtime_config_boundary.py`（53 行）：tools/verify_runtime_config_boundary.py 模块，围绕 verify runtime config boundary 提供结构化运行、配置、验证或桥接能力。
  - L19 `def _template_count`
  - L30 `def main`

- `tools/verify_runtime_console.py`（22 行）：tools/verify_runtime_console.py 模块，围绕 verify runtime console 提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `tools/verify_runtime_console_terminal_ui_and_planner_model_selection.py`（65 行）：tools/verify_runtime_console_terminal_ui_and_planner_model_selection.py 模块，围绕 verify runtime console terminal ui and planner model selection 提供结构化运行、配置、验证或桥接能力。
  - L10 `def test_console_ui_terminal_format`
  - L18 `def test_runtime_console_alias_route`
  - L24 `def test_planner_reads_agent_studio_model_selection`

- `tools/verify_runtime_native_capability_acquisition.py`（92 行）：tools/verify_runtime_native_capability_acquisition.py 模块，围绕 verify runtime native capability acquisition 提供结构化运行、配置、验证或桥接能力。
  - L65 `def main`

- `tools/verify_runtime_self_repair.py`（80 行）：tools/verify_runtime_self_repair.py 模块，围绕 verify runtime self repair 提供结构化运行、配置、验证或桥接能力。
  - L11 `def assert_schema_repair`
  - L32 `def assert_variable_repair`
  - L44 `def assert_parameter_repair`
  - L59 `def assert_final_answer_guard`

- `tools/verify_runtime_value_type_coercion.py`（43 行）：tools/verify_runtime_value_type_coercion.py 模块，围绕 verify runtime value type coercion 提供结构化运行、配置、验证或桥接能力。
  - L11 `def main`

- `tools/verify_scheduled_controller_and_reuse_fix.py`（49 行）：tools/verify_scheduled_controller_and_reuse_fix.py 模块，围绕 verify scheduled controller and reuse fix 提供结构化运行、配置、验证或桥接能力。
  - L13 `async def main`

- `tools/verify_scheduled_payload_dispatch_fix2.py`（42 行）：tools/verify_scheduled_payload_dispatch_fix2.py 模块，围绕 verify scheduled payload dispatch fix2 提供结构化运行、配置、验证或桥接能力。
  - L8 `async def main`

- `tools/verify_scheduled_runtime_generation.py`（64 行）：tools/verify_scheduled_runtime_generation.py 模块，围绕 verify scheduled runtime generation 提供结构化运行、配置、验证或桥接能力。
  - L12 `async def main`

- `tools/verify_scheduled_task_policy_and_parameter_extraction.py`（38 行）：tools/verify_scheduled_task_policy_and_parameter_extraction.py 模块，围绕 verify scheduled task policy and parameter extraction 提供结构化运行、配置、验证或桥接能力。
  - L6 `def test_compact_parameter_lines_are_extracted`
  - L25 `def test_controller_participant_is_derived_from_timing_step`

- `tools/verify_scheduled_task_runner.py`（43 行）：tools/verify_scheduled_task_runner.py 模块，围绕 verify scheduled task runner 提供结构化运行、配置、验证或桥接能力。
  - L12 `def test_scheduled_runner_executes_and_advances_next_run`

- `tools/verify_structural_entity_parameter_binding.py`（59 行）：tools/verify_structural_entity_parameter_binding.py 模块，围绕 verify structural entity parameter binding 提供结构化运行、配置、验证或桥接能力。
  - L13 `def main`

- `tools/verify_task_parameter_binding_no_reprompt.py`（38 行）：tools/verify_task_parameter_binding_no_reprompt.py 模块，围绕 verify task parameter binding no reprompt 提供结构化运行、配置、验证或桥接能力。
  - L6 `def main`

- `tools/verify_web_cleaning_batch_optimizer.py`（41 行）：tools/verify_web_cleaning_batch_optimizer.py 模块，围绕 verify web cleaning batch optimizer 提供结构化运行、配置、验证或桥接能力。
  - 无显式顶层类/函数。

- `tools/verify_web_evidence_optimizer.py`（59 行）：tools/verify_web_evidence_optimizer.py 模块，围绕 verify web evidence optimizer 提供结构化运行、配置、验证或桥接能力。
  - L11 `def main`

## 3. 主要缺陷与优化方案

### 3.1 源码边界校验没有隔离运行时目录
现象：运行 `.venv/bin/python validate_source_package.py` 失败，错误包含 `package contains Python cache files`，并把根目录 `runtime/external_runtimes/comfyui/...` 与 `.venv/...` 中大量 Markdown、依赖包文件纳入检查。
影响：验证脚本会被运行时缓存、外部运行环境、虚拟环境污染，导致“源码是否干净”的结论不可用。
优化：`validate_source_package.py` 的文件遍历应默认排除 `runtime/`、`.venv/`、`.git/`、`__pycache__/`；若需要检查运行时产物，应单独提供 runtime 专用验证命令。

### 3.2 单文件职责过大，维护风险高
静态统计显示，多个文件承担过多职责：
- `ai_core/executors/tool_call_executor.py`：5440 行，class=1，function=0，method=93。
- `auxiliary_brain/delegation/delegation_runtime.py`：3210 行，class=1，function=0，method=96。
- `auxiliary_brain/studio/service.py`：2510 行，class=1，function=0，method=81。
- `ai_core/interaction/conversation_core_runtime.py`：1497 行，class=1，function=0，method=34。
- `ai_core/agent_delegation/primary_brain_client.py`：1481 行，class=3，function=0，method=42。
- `auxiliary_brain/capability_acquisition/acquisition_router.py`：1263 行，class=2，function=0，method=36。
- `ai_core/media/image_generation_service.py`：1219 行，class=1，function=0，method=59。
- `ai_core/executors/llm_json_executor.py`：1208 行，class=1，function=0，method=27。
- `apps/api/server.py`：1101 行，class=21，function=72，method=0。
- `ai_core/runtime/bootstrap/core_bootstrap.py`：1100 行，class=1，function=7，method=21。
- `ai_core/media/video_generation_service.py`：1078 行，class=1，function=0，method=42。
- `ai_core/orchestration/workflow_runtime.py`：979 行，class=1，function=0，method=14。
- `ai_core/llm/provider_handlers/universal_model_handler.py`：926 行，class=1，function=1，method=27。
- `ai_core/executors/static_transform_executor.py`：816 行，class=1，function=0，method=33。
- `ai_core/knowledge/knowledge_service.py`：799 行，class=1，function=0，method=38。
优化：按“协议/状态模型、输入归一化、执行分派、错误恢复、持久化、展示适配”拆分；先从 `tool_call_executor.py`、`delegation_runtime.py`、`studio/service.py` 入手，建立薄门面 + 小服务组合。

### 3.3 宽泛异常捕获过多，错误语义会被吞掉
以下文件 `except Exception` 数量较高：
- `ai_core/executors/tool_call_executor.py`：30 处，5440 行。
- `ai_core/media/image_generation_service.py`：28 处，1219 行。
- `apps/api/server.py`：20 处，1101 行。
- `ai_core/media/video_generation_service.py`：17 处，1078 行。
- `auxiliary_brain/capability_acquisition/acquisition_router.py`：13 处，1263 行。
- `ai_core/runtime/browser/browser_network_observer.py`：12 处，236 行。
- `auxiliary_brain/studio/service.py`：10 处，2510 行。
- `ai_core/executors/llm_json_executor.py`：10 处，1208 行。
- `ai_core/tools/runtime_registered_tool_service.py`：9 处，464 行。
- `ai_core/agent_delegation/primary_brain_client.py`：9 处，1481 行。
- `ai_core/runtime/modeling/model_runtime_preflight.py`：8 处，347 行。
- `ai_core/knowledge/document_processor.py`：8 处，270 行。
- `ai_core/web_evidence_optimizer/optimizer.py`：7 处，427 行。
- `ai_core/research/deep_web_research.py`：7 处，657 行。
- `ai_core/interaction/conversation_core_runtime.py`：7 处，1497 行。
- `ai_core/context/execution_reuse_store.py`：7 处，754 行。
- `runtime_assets/seeds/capability_planners/default_capability_planner.py`：6 处，371 行。
- `auxiliary_brain/delegation/delegation_runtime.py`：6 处，3210 行。
- `ai_core/runtime/scheduler/scheduled_task_runner.py`：6 处，186 行。
- `ai_core/media/providers/generic_text_animation_provider.py`：6 处，366 行。
- `ai_core/orchestration/workflow_runtime.py`：5 处，979 行。
影响：运行失败可能只留下模糊状态，影响自修复分类、用户提示和测试定位。
优化：为外部进程、模型调用、JSON 解析、文件 IO、网络调用分别定义可恢复错误；捕获后写入结构化错误码、阶段、输入摘要和建议动作；只有最外层 API 才保留兜底异常。

### 3.4 `ai_core/tools` 与 `auxiliary_brain/capability_acquisition/tools` 存在镜像式重复
现象：两处均包含 `tool_blueprint_builder.py`、`runtime_generated_tool_installer.py`、`runtime_tool_artifact_validator.py`、`generic_web_extract_artifact.py`、`runtime_tool_registry.py`、`tool_code_generation_request.py`、`sandbox_verifier.py`、`runtime_primitive_tool_factory.py`、`browser_automation_blueprint.py`、`runtime_tool_artifact_generator.py` 等相近文件。
影响：修复和演进容易只改一边，造成能力生成/校验边界不一致。
优化：明确唯一所有权。建议把通用工具产物契约留在 `ai_core/tools`，辅助侧仅保留编排适配；迁移前增加对两边产物行为一致性的回归脚本。

### 3.5 配置驱动理念明确，但配置 Schema 覆盖不足
现象：`configs/` 中包含大量 JSON/YAML 种子，但 `schema/` 只覆盖部分契约。部分配置由服务代码直接读写和容错迁移。
影响：配置字段漂移会在运行时才暴露，容易导致模型路由、能力模板、权限策略行为不一致。
优化：为 `runtime_capability_templates.json`、`runtime_capability_policy.json`、`model_routing_topology.json`、`agent_parameter_contracts.json`、`provider_runtime_templates.seed.json` 建立或补齐 schema，并在 CI 中验证。

### 3.6 测试形态偏脚本化，缺少统一测试入口
现象：大量验证位于 `tools/verify_*.py` 和根目录 `verify_*.py`，只有少量 `tests/` 文件；验证脚本返回方式、清理方式和断言风格不完全统一。
影响：回归选择成本高，难以判断哪组验证代表发布门槛。
优化：保留脚本作为专项验证，但用 `pytest` 收编核心用例；按边界建立 `unit`、`integration`、`runtime-boundary` 标记；把根目录验证脚本迁入 `tools/` 或 `tests/`。

### 3.7 部分 Web/API 文件混合路由、状态拼装与错误处理
现象：`apps/api/server.py` 超过 1100 行，包含路由、文件读取、运行时服务调用、异常处理、静态页面入口等。
影响：API 行为变更容易影响 UI、运行时控制台和执行链路。
优化：拆成 routers：`studio`、`runtime_console`、`knowledge`、`artifacts`、`settings`；公共路径校验和脱敏逻辑沉到独立模块。

### 3.8 “不硬写代码、不设计业务专业词”的约束总体被遵守，但需要机器化守护
源码中大量 docstring 明确声明 domain-neutral、business-free、runtime-generated boundary，说明工程方向一致。风险点在于新增功能时容易把能力例子、provider 细节或一次性用户值写入核心。
优化：保留并修复 `tools/validate_source_package.py` 的边界扫描；增加专门规则：核心目录不得出现配置外业务词表、用户样例值、固定任务分支；运行时能力必须从 schema/registry/config 加载。

## 4. 关于“不硬写代码、不设计业务专业词”的实现建议
- 核心源码只表达结构概念：输入、参数、契约、证据、节点、阶段、能力、工具、模型、审批、权限、运行状态。
- 具体能力名称、字段别名、外部 API、用户样例、提示模板，应放入 `configs/` 或根目录 `runtime/` 下的运行时注册资料。
- 生成工具/模块时必须携带 identity contract、manifest、schema、sandbox report、verification report，禁止只根据字符串分支直接注册。
- 参数绑定优先使用 schema、aliases、runtime values、uploaded artifact contract，不在核心代码中写“某业务字段等于某含义”。
- 最终答案只消费已执行结果和证据材料，不重新执行、不重新搜索、不补编事实。

## 5. 建议优先级
1. 修复源码验证边界：让 `validate_source_package.py` 排除根目录 `runtime/`、`.venv/` 和缓存目录。
2. 拆分 `ai_core/executors/tool_call_executor.py`，优先抽出错误分类、参数解析、工具调用适配和结果归一化。
3. 统一工具生成相关模块所有权，减少 `ai_core/tools` 与 `auxiliary_brain/.../tools` 的双写。
4. 把关键 `tools/verify_*.py` 收编进 pytest 标记体系。
5. 为核心配置补 schema，并将“无业务词/无硬编码值”作为 CI 检查。
