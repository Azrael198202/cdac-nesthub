# 分脑规划当前代码分析

生成日期：2026-06-05

## 分析范围

本次分析按最新规划重新审视源码边界：

- `ai_core`：通用操作系统能力。
- `auxiliary_brain`：Agent、Task、Capability 生命周期管理。
- `repair_brain`：root cause analysis、repair planning。
- `verification_brain`：verification、evaluation。
- `memory_brain`：experience、memory、knowledge。
- 根目录 `runtime/`：运行时生成物和外部运行环境。

分析时排除了 `.venv/`、`.git/`、`__pycache__/`；根目录 `runtime/` 只看目录形态，不作为源码包分析。

## 当前落地情况

### ai_core

`ai_core` 仍是最大包：约 313 个 Python 文件、52164 行、2095 个类方法。它目前承担了主运行内核的大部分职责：

- 输入解析：`ai_core/input_parsing/`
- 阶段契约：`ai_core/pipeline/`、`ai_core/orchestration/`
- 意图识别和工作流规划：主要仍在 `ai_core/interaction/conversation_core_runtime.py`、`ai_core/executors/llm_json_executor.py`、`ai_core/workflow/`
- 执行：`ai_core/execution/`、`ai_core/executors/`
- 模型路由：`ai_core/llm/`、`ai_core/runtime/modeling/`、新增 `ai_core/model_orchestration/`
- 能力、工具、模块注册和运行：`ai_core/runtime/capability/`、`ai_core/tools/`、`ai_core/modules/`

判断：作为“通用操作系统能力”是合理的，但目前 `ai_core` 仍包含不少本应逐步迁出的职责，例如 memory/knowledge、repair、verification、部分 lifecycle 与 evidence 逻辑。

### auxiliary_brain

`auxiliary_brain` 约 42 个 Python 文件、12009 行。当前主要承担：

- Agent Studio 服务：`auxiliary_brain/studio/service.py`
- Agent/Task 图规划与执行委托：`auxiliary_brain/studio/*planner.py`、`auxiliary_brain/delegation/`
- Capability acquisition：`auxiliary_brain/capability_acquisition/`
- 参数契约：`auxiliary_brain/parameters/`
- 运行时代码分析：`auxiliary_brain/runtime_codegen/`

判断：和“Agent、Task、Capability 生命周期管理”基本一致。但 `auxiliary_brain/capability_acquisition/tools/` 与 `ai_core/tools/` 仍存在镜像式重复，需要明确所有权。

### repair_brain

`repair_brain` 已出现，约 4 个 Python 文件、142 行：

- `contracts.py`：`RepairRequest`、`RepairPlan`
- `brain.py`：`RuntimeRepairBrain`
- `compat.py`：旧 repair 导入兼容层

当前 `RuntimeRepairBrain` 会收集 evidence、调用 `ai_core.runtime.self_repair.execution_failure_repair.ExecutionFailureRepairClassifier` 做分类，再生成 repair plan，并写入 `memory_brain`。

判断：边界设计合理，但还是第一阶段 facade。真正 root cause analysis 尚未完全迁出 `ai_core.runtime.self_repair`，repair planning 也还偏规则化，尚未形成独立的 repair graph、repair policy、repair verification lifecycle。

### verification_brain

`verification_brain` 已出现，约 3 个 Python 文件、88 行：

- `contracts.py`：`VerificationExpectation`、`VerificationResult`
- `engine.py`：`RuntimeVerificationBrain`

当前验证能力是确定性结构检查：未解析模板变量、必填 key、允许状态等。

判断：作为独立 verification/evaluation 边界是合理的，但覆盖面仍较窄。`ai_core/execution/` 和 `ai_core/runtime/verification/` 中仍有大量验证/评估逻辑，后续应逐步迁移或明确为底层执行断言。

### memory_brain

`memory_brain` 已出现，约 3 个 Python 文件、78 行：

- `contracts.py`：`MemoryRecord`
- `store.py`：`RuntimeMemoryStore`

当前是 append-only JSONL experience store，默认写入 `runtime/generated/memory_brain/runtime_experience.jsonl`。

判断：方向正确，但目前 `ai_core/context/`、`ai_core/knowledge/`、`ai_core/evolution/`、`ai_core/runtime/learning/` 仍承担大量 memory/knowledge/experience 职责。`memory_brain` 需要成为统一门面，否则会出现多套记忆系统。

### runtime

根目录 `runtime/` 当前主要包含：

- `runtime/generated/`
- `runtime/external_runtimes/`
- `.DS_Store`

判断：总体符合“只放运行时生成物和外部运行环境”的规划。`.DS_Store` 是本机系统文件，应该加入忽略或清理。此前验证脚本曾把 `runtime/` 和 `.venv/` 扫入源码检查，边界检查还需要修正。

## 未说明但已经出现的模块

### evidence_engine

`evidence_engine` 已出现，约 3 个 Python 文件、177 行。它负责根据 `run_id`、`task_name`、`participant_id`、`event_name` 从 trace/log/artifact 中收集和过滤证据。

建议定位：应作为独立基础服务，供 `repair_brain`、`verification_brain`、`memory_brain` 使用。它不应回流到 `ai_core` 里做业务判断。

### task_runtime

`task_runtime` 已出现，约 2 个 Python 文件、21 行，目前只有 `TaskRuntimeRevision`。

建议定位：放 Task 运行生命周期的稳定契约，例如 task revision、graph revision、plan revision、active revision。当前执行行为仍在 `auxiliary_brain/studio/service.py`，后续可逐步迁到 `task_runtime`，让 Studio 服务变薄。

### ai_core/model_orchestration

新增 `BrainModelRouter` 和 `LiteLLMBrainClient`，通过 `configs/brain_model_policy.yaml` 为不同 brain 选择模型。

建议定位：这是跨 brain 的通用 OS 能力，放在 `ai_core` 可以接受。但要保持它只做策略路由，不做某个 brain 的推理逻辑。

### apps、configs、schema、runtime_assets、tools、scripts、tests

这些不属于六个 brain，但都是必要支撑模块：

- `apps/`：API 和 Web UI。
- `configs/`：静态策略和种子配置。
- `schema/`：契约校验。
- `runtime_assets/`：随源码分发的运行时种子资产。
- `tools/`、`scripts/`、`tests/`：验证和维护入口。

建议在架构文档中明确它们是“平台支撑层”，不要强行塞进某个 brain。

## 规划合理性判断

整体规划是合理的，原因是：

1. `ai_core` 被定义为通用 OS，能承接模型路由、执行调度、沙箱、权限、工具注册等底层能力。
2. `auxiliary_brain` 负责 Agent/Task/Capability 生命周期，能避免把用户侧组织和编排逻辑塞进核心执行层。
3. `repair_brain`、`verification_brain`、`memory_brain` 把失败分析、结果验证、经验沉淀拆开，有利于闭环演进。
4. 根目录 `runtime/` 只放生成物，符合“不硬写能力、不把运行时状态混入源码”的原则。
5. `evidence_engine` 作为独立证据层很有必要，可以降低 repair 和 verification 读取大日志的噪声。

但当前代码还处在过渡阶段：新包已经建立，旧职责还没有完全迁移。

## 当前主要问题

### 1. ai_core 仍然过重

`ai_core` 仍包含：

- `ai_core/knowledge/`
- `ai_core/context/session_memory_store.py`
- `ai_core/context/vector_memory_store.py`
- `ai_core/evolution/`
- `ai_core/runtime/learning/`
- `ai_core/runtime/self_repair/`
- `ai_core/runtime/verification/`
- `ai_core/execution/*validator*`

这些并非都必须删除，但需要重新定义：哪些是 OS 底层接口，哪些应迁到 `memory_brain`、`repair_brain`、`verification_brain`。

### 2. repair_brain 目前依赖 ai_core 的 self_repair 实现

`repair_brain/brain.py` 直接使用 `ExecutionFailureRepairClassifier`。这保证了兼容，但也说明 root cause analysis 还没有真正独立。

建议下一步把 `ExecutionFailureDiagnosis`、failure taxonomy、repair ownership policy 迁到 `repair_brain`，`ai_core` 只调用 `repair_brain` 接口。

### 3. verification 逻辑分散

现在有：

- `verification_brain/`
- `ai_core/runtime/verification/`
- `ai_core/execution/evidence_quality_validator.py`
- `ai_core/execution/generated_result_verifier.py`
- `ai_core/execution/answer_sufficiency_evaluator.py`
- `ai_core/execution/state_consistency_validator.py`

建议明确分层：

- `verification_brain`：最终结果和修复结果是否可接受。
- `ai_core/execution`：执行时的结构断言和状态一致性。
- `ai_core/runtime/verification`：如果保留，只作为底层 verification primitives，或逐步并入 `verification_brain`。

### 4. memory/knowledge/experience 目前是多中心

当前 memory 相关分布在：

- `memory_brain`
- `ai_core/context`
- `ai_core/knowledge`
- `ai_core/evolution`
- `ai_core/runtime/learning`
- `apps/api/server.py` 中的 memory/knowledge API

建议让 `memory_brain` 成为统一入口：

- conversation memory
- vector memory
- knowledge base
- prompt/evaluation experience
- repair memory

`ai_core` 可以保留底层 storage adapter，但不应再直接决定 memory 类型和提升策略。

### 5. auxiliary_brain 与 ai_core tools 有重复

`auxiliary_brain/capability_acquisition/tools/` 和 `ai_core/tools/` 仍有相近文件。建议统一：

- 通用工具契约、产物校验、注册：`ai_core/tools`
- 能力生命周期编排、生成请求组织、修复协调：`auxiliary_brain`

### 6. task_runtime 还只是契约壳

当前 Task revision 逻辑实际还在 `auxiliary_brain/studio/service.py`。后续如果要让规划更清晰，应把 task revision store、graph revision、plan revision、active revision 切到 `task_runtime`。

### 7. brain_model_policy 有潜在模型可用性风险

`configs/brain_model_policy.yaml` 中 `repair_brain.high` 和 `verification_brain.critical` 指向 `openai/gpt-5.5-thinking`。如果运行环境没有该模型或 provider 配置，会导致高复杂度路径失败。

建议为每个高阶路由配置本地 fallback，并在启动时做 policy preflight：provider 可用、模型名合法、fallback 可用。

### 8. 边界验证还偏 smoke test

`scripts/verify_brain_separation_boundaries.py` 已通过，说明新包可导入、基础行为可运行。但 `pytest` 当前不可用，运行 `python -m pytest tests/verify_logical_participant_dedupe_and_brain_model_routing.py -q` 失败：当前虚拟环境没有 `pytest`。

建议把边界检查纳入统一测试环境，并补充 import-boundary 测试，例如：

- `repair_brain` 不允许依赖 `auxiliary_brain/studio`。
- `verification_brain` 不允许直接写 runtime generated artifacts，除非通过明确 contract。
- `memory_brain` 不允许写入源码目录。
- `ai_core` 不允许直接 import 新 brain 的内部实现，只能 import contract/facade。

## 推荐迁移路线

### 第一阶段：定义边界和兼容层

当前已基本完成：

- 新包已建立。
- `docs/brain_separation_boundaries.md` 已描述边界。
- `scripts/verify_brain_separation_boundaries.py` 已有 smoke test。
- `ai_core/feedback_repair/__init__.py` 已提示新代码使用 `repair_brain`。

下一步补齐：为每个 brain 添加 README 或 package-level boundary docstring。

### 第二阶段：迁移 repair

优先迁移：

- failure contracts
- failure taxonomy
- root cause classifier
- repair plan policy
- repair memory recording

目标：`ai_core.runtime.self_repair` 变成兼容 facade 或底层执行修复 primitives，主入口切到 `repair_brain`。

### 第三阶段：迁移 verification/evaluation

优先迁移：

- final answer guard
- generated result verifier
- answer sufficiency evaluator
- evidence quality validator
- repair output verification

目标：所有“结果是否可接受”的判断进入 `verification_brain`，`ai_core` 只负责执行阶段结构校验。

### 第四阶段：统一 memory

优先迁移：

- `SessionMemoryStore`
- `VectorMemoryStore`
- `KnowledgeService`
- `RuntimeLearningService`
- approval/correction learning

目标：`memory_brain` 暴露统一接口：remember、recall、promote、search、ingest_knowledge、record_experience。

### 第五阶段：拆 task_runtime

优先从 `auxiliary_brain/studio/service.py` 抽出：

- task revision metadata
- graph revision asset writing
- active revision selection
- schedule state
- task execution history

目标：Studio 只处理用户交互和 API 编排，Task 生命周期由 `task_runtime` 持有。

### 第六阶段：清理 runtime 边界

- `.gitignore` 忽略 `runtime/` 下生成物和 `.DS_Store`。
- `validate_source_package.py` 排除根目录 `runtime/`、`.venv/`、`__pycache__/`。
- 对 `runtime_assets/` 单独定义：它是源码分发的种子资产，不是运行时写入目录。

## 结论

这次规划方向是对的，而且最新代码已经迈出第一步：`repair_brain`、`verification_brain`、`memory_brain`、`evidence_engine`、`task_runtime` 都已经有了最小可运行边界。

当前最大问题不是方向，而是“旧职责还留在 ai_core”。建议不要一次性大搬迁，而是按 repair、verification、memory、task runtime 的顺序迁移，每迁一类就加边界测试和兼容 facade。这样能保持现有运行链路稳定，同时逐步把六层规划变成真实代码结构。
