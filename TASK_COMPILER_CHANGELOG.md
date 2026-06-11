# v22 Task Compiler 修改说明

## 本次目标

将任务运行链路从“创建后运行时解释”调整为：

Create Task → Compile Task → Validate Task → Save Compiled Task → Execute Compiled Task

## 新增模块

### auxiliary_brain/task_compiler

- task_graph_compiler.py：统一编译任务图、步骤、绑定、执行计划、校验报告并保存到 runtime/generated/tasks/<task_id>/。
- step_compiler.py：将每个步骤编译成独立 step 目录所需的契约文件。
- prompt_compiler.py：创建阶段锁定 Prompt Profile，禁止运行时猜 Prompt。
- binding_compiler.py：将上游/下游关系编译成结构化 Binding，禁止保存模板字符串。
- execution_plan_compiler.py：生成执行计划，声明上下文隔离和绑定解析方式。
- validation_compiler.py：TaskGraphCompileGate，创建阶段校验 Binding、Prompt Profile、Execution Owner、Capability、Source Contract。
- compiled_task_loader.py：执行阶段加载已编译任务，并注入 compiled_task 元数据。

### runtime/prompt_profiles

新增通用 Prompt Profile：

- source_retrieval.prompt
- document_composition.prompt
- capability_acquisition.prompt
- capability_execution.prompt
- workflow_compile.prompt
- verification.prompt
- presentation.prompt
- json_planning.prompt

### ai_core/step_execution

- step_request_builder.py：由 Compiled Step 构建 Step Request。
- step_execution_bridge.py：将编译后的 Step 契约桥接到 ai_core 执行。
- step_result_builder.py：统一 Step Result 输出结构。

### ai_core/presentation/presentation_bridge.py

将 verified_result 转为 presentation_output 和 exportable_outputs，并阻止 failure message 进入 exportable_outputs。

### ai_core/research/source_material_extractor.py

新增 Web Source Material Layer，提取顺序：

url page → visible text → text excerpt → search cards → blocked

## 已修改现有模块

### auxiliary_brain/studio/service.py

- 创建任务时：生成旧 task graph 后立即进入 TaskGraphCompiler。
- Compile Gate 失败时：返回 Task compile failed，不保存可执行任务。
- Compile Gate 通过后：保存 compiled task 目录，并在旧 task graph 中记录 compiled_task 元数据。
- 执行任务时：优先加载 compiled task；缺失时尝试补编译；补编译失败则阻止执行。

### ai_core/graph/graph_visualization.py

Graph Hover details 增加：

- Instruction
- Prompt Profile
- Execution Contract
- Dependencies
- Bindings
- Exportable Outputs

### scheduler

- 支持 runtime/generated/tasks/<task_id>/source_task_graph.json。
- 避免同时存在 legacy json 与 compiled task 目录时重复调度。

## 通用性检查

- 新增代码不包含具体业务能力名称。
- 新增代码不包含固定测试数据。
- Binding 使用结构化 JSON，不保存 {{Step.final_answer}} 形式模板。
- Prompt Profile 在创建阶段锁定，执行阶段只读取 profile id。
- Step Context 明确禁止 sibling step context inheritance。

## 验证结果

- python -m compileall：通过。
- TaskGraphCompiler 简单编译/保存/加载验证：通过；验证后已删除临时样例目录。
- 高风险业务词汇扫描：未发现指定业务词汇残留。
