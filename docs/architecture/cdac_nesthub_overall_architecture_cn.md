# cdac-nesthub 整体架构分析与模块职责说明

> 语言：中文  
> 分析对象：`cdac-nesthub-v21`  
> 生成时间：2026-06-08 10:30:34  
> 检查范围：源码目录、脑模块划分、能力生成链路、执行验证链路、硬编码/业务词边界  
> Python 文件数量：399

---

## 1. 设计基准

本版本必须对齐两个核心文件：

- `Des
- `rule.txt`


### 1.1 Design-Concept 核心原则

系统角色分为三类：

1. **高端设计者**  
   负责 `ai_core` 与 `auxiliary_brain` 与其他脑的整体设计。  
   `ai_core` 是系统主脑，`auxiliary_brain` 是辅助脑，`verification_brain` 是验证脑、`repair_brain` 是修复脑、`presentation_brain` 表达脑。
- `perception_brain` 感知脑、`memory_brain` 记忆脑、`evidence_engine` 。
   `ai_core` 只做通用大脑与运行时操作系统，不写具体功能。具体能力由运行时根据用户需求生成、组合、执行、验证。

2. **高级代码实现者**  
   按照高端设计者的设计思想实现功能，保证代码结构、模块边界和运行流程可落地。

3. **魔鬼检验者**  
   对设计思想、实现逻辑、代码质量、边界隔离、验证结果进行严格检查，防止假成功、硬编码、业务词污染和执行链路绕路。

### 1.2 rule.txt 核心约束

- 禁止硬写代码。
- 禁止业务词汇进入代码。
- 保证质量。
- 代码中不要出现生成时测试用的数据，保证代码干净。
- 每个步骤都要明确验证成功后再提交代码。

---

## 2. 总体判断

### 2.1 总体结论

- 已经形成多脑结构，不再把所有功能塞进 `ai_core`。
- `ai_core` 大部分模块已经偏向通用运行时操作系统。
- `auxiliary_brain` 开始承担 runtime capability acquisition、runtime code generation、sandbox validation、registry registration 等职责。
- `verification_brain`、`repair_brain`、`presentation_brain` 已经被拆出，符合“验证、修复、表达分离”的方向。
- `perception_brain`、`memory_brain`、`evidence_engine` 也已经具备独立职责。

修正的风险：

- `ai_core/runtime` 文件较多，仍可能承担过重，需要进一步确认是否存在“主脑直接实现具体能力”的残留。
- `auxiliary_brain` 中仍有少量示例型业务词注释，例如 `Fukuoka`、`Tokyo`，虽然不是能力逻辑，但违反“业务词汇不进入代码”的严格标准。
- `CapabilityClassifier` 当前使用固定 marker 判断 runtime-native / external-evidence-required，属于“结构性关键词规则”，不是具体业务词，但仍需要防止未来继续膨胀成硬编码规则表。
- `apps/api/server.py` 聚合了较多服务实例与 API 入口逻辑，后续应继续拆分，避免 API 层变成第二个大脑。

---

## 3. 整体架构图

```text
User / UI
   │
   ▼
apps/api/server.py
   │
   ▼
perception_brain
   │  原始输入、多媒体、文件、文本统一标准化
   ▼
ai_core.input_parsing
   │  结构化输入，不判断业务执行
   ▼
ai_core.intent_recognition / interaction
   │  识别意图、任务类型、能力需求、缺失信息
   ▼
auxiliary_brain.parameters + memory_brain
   │  参数补全、上下文绑定、会话状态判断
   ▼
ai_core.workflow / graph / orchestration
   │  生成执行计划、主图、子图、Agent 图、锁定执行方式
   ▼
verification_brain
   │  执行前验证：schema、参数、能力、审批
   ▼
runtime kernel / ai_core.executors / registered tools
   │  只执行计划，不重新判断意图，不重新选择能力
   ▼
evidence_engine + trace / provenance
   │  记录证据、执行来源、可观测信息
   ▼
verification_brain.result_verification
   │  验证真实执行、结果满足度、可信度
   ▼
repair_brain
   │  按计划修复 schema / 参数 / fallback / 失败原因
   ▼
presentation_brain
   │  最终汇总，不重新搜索，不制造新事实
   ▼
Final Answer / Artifacts / Trace Summary
```

---

## 4. 每个脑的设计要点与功能

## 4.1 ai_core：主脑 / 通用运行时操作系统

### 定位

`ai_core` 是系统主脑，但不是具体业务能力实现层。它应该只负责通用运行时操作系统能力，包括：

- 输入结构化
- 意图识别
- 工作流规划
- 图规划
- 执行方法锁定
- 通用执行器调度
- 工具注册服务调用
- 模型路由
- 运行时上下文管理
- 安全、审批、配置、事件、可观测

### 当前主要模块

| 模块 | 当前功能 | 设计判断 |
|---|---|---|
| `ai_core/architecture` | 定义 LayerContract、每层允许/禁止决策 | 符合设计，是边界治理核心 |
| `ai_core/input_parsing` | 结构化实体提取、输入字段整理 | 符合，不能进入业务执行判断 |
| `ai_core/interaction` | 会话运行、自然对话、问题生成、交互契约 | 符合，但需避免直接业务决策 |
| `ai_core/workflow` | workflow 生成、状态合并、计划结构 | 符合，必须只规划不执行 |
| `ai_core/graph` | 图结构、图自检、图可视化、边调度 | 符合，负责通用图能力 |
| `ai_core/orchestration` | 工作流运行协调 | 符合，但需确保不在执行阶段重规划 |
| `ai_core/execution` | 结果分类、候选策略、证据质量、延续执行 | 基本符合，但需防止执行层重新判断意图 |
| `ai_core/executors` | LLM、工具、MCP、workflow、human review 等通用执行器 | 符合，执行器必须只按 plan 执行 |
| `ai_core/tools` | 注册工具服务、通用工具 runner、schema validator | 符合，但生成能力应放在 auxiliary_brain/runtime/generated |
| `ai_core/runtime` | runtime bootstrap、observability、scheduler、capability gate 等 | 功能合理，但体量较大，需要持续瘦身 |
| `ai_core/llm` | provider router、model matcher、cache、token 记录 | 符合模型调度层定位 |
| `ai_core/context` | session memory、prompt budget、context reducer、reuse store | 符合上下文治理，但不要写业务规则 |
| `ai_core/research` | 通用外部资料发现、endpoint 验证、repository 分析 | 允许存在，但必须是通用 evidence 能力 |
| `ai_core/web_evidence_optimizer` | 搜索 query 规划、证据压缩与优化 | 符合通用证据处理 |
| `ai_core/security` | 安全策略、路径保护等 | 符合 |
| `ai_core/approval` | 人工确认 gate | 符合 |
| `ai_core/validation` | 通用校验 | 符合 |
| `ai_core/presentation` | 旧式表达相关模块 | 建议逐步迁移到 `presentation_brain`，避免职责重复 |
| `ai_core/feedback_repair` | 旧式修复命名空间 | 建议逐步迁移到 `repair_brain` |

### ai_core 的禁止事项

`ai_core` 不应出现：

- 具体业务能力实现，例如天气、邮件、酒店、旅游、Shopify、SharePoint 等。
- 根据具体词汇直接选择工具。
- 执行阶段重新判断意图。
- fallback 自己临时决定搜索/API/LLM。
- 生成能力代码直接写在 `ai_core` 内。
- 测试用固定数据或示例业务城市/邮箱/URL。

### 当前风险

1. `ai_core/runtime` 过大，建议继续拆分：
   - runtime kernel
   - runtime observability
   - runtime capability gateway
   - runtime scheduler
   - runtime registry access

2. `ai_core/presentation` 与 `presentation_brain` 有职责重叠风险。

3. `ai_core/feedback_repair` 与 `repair_brain` 有职责重叠风险。

---

## 4.2 auxiliary_brain：辅助脑 / 能力生成与任务协作层

### 定位

`auxiliary_brain` 是辅助脑，负责主脑不应直接承担的动态生成、补全、协作、能力采集工作。

它不是业务能力库，而是“能力生成和治理工厂”。

### 当前主要模块

| 模块 | 当前功能 | 设计判断 |
|---|---|---|
| `auxiliary_brain/capability_acquisition` | 能力分类、蓝图生成、代码生成、沙箱验证、注册、修复 | 符合核心方向，是 v21 最重要模块 |
| `auxiliary_brain/runtime_codegen` | 动态值硬编码检测、运行时变量推断 | 符合 rule，防止生成代码写死数据 |
| `auxiliary_brain/parameters` | Agent 参数契约、参数槽管理 | 符合 requirement_completion 职责 |
| `auxiliary_brain/delegation` | Agent 委托、TaskMindGraph、协作执行 | 符合多 Agent 任务协作 |
| `auxiliary_brain/studio` | Agent Studio 服务、结构化步骤规划、语义规划、命令路由 | 符合 UI/配置/运行时任务装配 |
| `auxiliary_brain/protocols` | 主脑与辅助脑交互协议 | 符合边界治理 |
| `auxiliary_brain/storage` | JSON 存储 | 符合辅助脑内部持久化 |
| `auxiliary_brain/feedback_repair` | 辅助脑侧修复命名空间 | 合理，但需与 repair_brain 边界明确 |

### Capability Acquisition 标准流程

```text
Capability Request
   ↓
Capability Classification Layer
   ↓
Capability Blueprint
   ↓
Capability Specification
   ↓
LLM Code Generation
   ↓
Sandbox Verification
   ↓
Capability Registration
   ↓
Execution Verification
```

### 关键设计要求

- 先判断能力属于 runtime-native、dependency-backed、external-evidence-required 哪类。
- 对 basic / standard-library / no-network / local-runtime 的能力，不应强制 web evidence。
- 对需要外部 API、SDK、协议、认证的能力，必须要求 evidence 或用户配置。
- 生成代码必须在 `runtime/generated` 或等价运行时目录，不进入 `ai_core`。
- 注册前必须通过 sandbox validation。
- 生成代码必须使用 input / connection / secret schema，不得把动态值写入源码。

### 当前风险

1. `CapabilityClassifier` 有结构性 marker 列表。它目前不是业务词，但仍是规则表。建议后续把 marker 移到 runtime policy 配置文件，避免代码中持续累积判断词。

2. `auxiliary_brain/parameters/agent_parameter_contract.py` 和 `auxiliary_brain/delegation/delegation_runtime.py` 注释中出现 `Fukuoka`、`Tokyo` 这种示例业务词。虽然不是实际逻辑，但按严格 rule 仍应清理为 `example_location`、`location_value`。

3. `capability_acquisition/acquisition_router.py` 体量较大，建议拆为：
   - classifier
   - identity extractor
   - planner caller
   - blueprint materializer
   - dependency resolver
   - artifact generator
   - sandbox validator
   - registry writer
   - execution verifier

---

## 4.3 perception_brain：感知脑 / 输入标准化层

### 定位

负责把用户输入、文件、图片、音频、视频等统一转为可供主脑处理的标准输入包。

### 当前模块

| 模块 | 功能 |
|---|---|
| `perception_brain/service.py` | 感知脑服务入口 |
| `perception_brain/modality_router.py` | 输入模态路由 |
| `perception_brain/contracts.py` | ArtifactObservation、NormalizedInputPackage 等契约 |
| `processors/text_document.py` | 文本文档抽取，支持 txt / md / json / csv / pdf / docx 等 |
| `processors/image.py` | 图片感知 |
| `processors/audio_video.py` | 音频、视频感知 |
| `processors/base.py` | 感知处理器基类 |

### 设计边界

允许：

- 识别输入类型。
- 抽取文本和 metadata。
- 生成 artifact summary。
- 保留原始输入引用。

禁止：

- 判断业务怎么执行。
- 选择工具。
- 生成 workflow。
- 直接调用业务能力。

---

## 4.4 memory_brain：记忆脑 / 上下文与会话状态层

### 定位

负责会话状态、历史上下文、用户确认参数、任务挂起状态、可共享摘要。

### 当前模块

| 模块 | 功能 |
|---|---|
| `memory_brain/contracts.py` | MemoryRecord 数据契约 |
| `memory_brain/store.py` | RuntimeMemoryStore，保存和读取运行时记忆 |

### 设计边界

允许：

- 判断当前输入是否是补充参数、继续任务、新任务、取消/暂停、普通聊天。
- 管理 session / task 状态。
- 输出 clean_context。
- 多 Agent 之间只共享安全摘要。

禁止：

- 重新判断业务意图。
- 选择执行方法。
- 执行工具。
- 将 peer result 原文注入独立 Agent。

---

## 4.5 evidence_engine：证据引擎 / 证据收集与裁剪层

### 定位

负责证据收集、读取、整理，为验证脑和最终表达提供可信材料。

### 当前模块

| 模块 | 功能 |
|---|---|
| `evidence_engine/contracts.py` | EvidenceRequest、EvidenceItem、EvidencePackage |
| `evidence_engine/collector.py` | RuntimeEvidenceCollector，收集运行证据 |

### 设计边界

允许：

- 读取指定 evidence source。
- 生成 evidence package。
- 记录 collected_at、source、confidence 等元信息。

禁止：

- 代替 workflow_planning 做新搜索决策。
- 在 final_synthesis 阶段补造新事实。

---

## 4.6 verification_brain：验证脑 / 魔鬼检验层

### 定位

验证脑是第三角色“魔鬼检验者”的系统化实现。

### 当前模块

| 模块 | 功能 |
|---|---|
| `verification_brain/contracts.py` | VerificationExpectation、VerificationResult |
| `verification_brain/engine.py` | RuntimeVerificationBrain |
| `verification_brain/foundation.py` | failure report、验证记录、用户反馈确认 |

### 验证职责

- 执行前验证：schema、参数、能力是否存在、审批是否完成。
- 执行后验证：是否真实执行、结果是否满足 step、可信度是否达标。
- 生成 failure report。
- 不允许假成功。
- 不允许把“计划成功”说成“执行成功”。

### 禁止事项

- 不重新选择工具。
- 不自己决定新的 fallback。
- 不制造成功结论。
- 不吞掉失败原因。

---

## 4.7 repair_brain：修复脑 / 失败修复与恢复层

### 定位

负责根据 verification_brain 的失败报告生成修复计划。

### 当前模块

| 模块 | 功能 |
|---|---|
| `repair_brain/contracts.py` | RepairRequest、RepairPlan |
| `repair_brain/brain.py` | RuntimeRepairBrain |
| `repair_brain/compat.py` | 兼容层 |

### 修复职责

- JSON schema 修复。
- 参数错误回到 requirement_completion。
- 工具失败按 workflow plan 中允许的 fallback 处理。
- 多次失败后输出明确失败原因。

### 禁止事项

- 不新增业务规则。
- 不静默改 execution_method。
- 不绕过验证直接注册能力。

---

## 4.8 presentation_brain：表达脑 / 最终汇总层

### 定位

负责把已验证的材料组织成用户可理解的最终答案。

### 当前模块

| 模块 | 功能 |
|---|---|
| `presentation_brain/contracts.py` | PresentationRequest、PresentationResult |
| `presentation_brain/brain.py` | PresentationBrain |
| `presentation_brain/failure_message_renderer.py` | 失败信息用户化表达 |
| `presentation_brain/profile_registry.py` | 表达风格配置 |
| `presentation_brain/compat.py` | 兼容层 |

### 设计边界

允许：

- 汇总 accepted_material。
- 根据 presentation profile 调整格式。
- 输出 public trace summary。
- 展示失败原因。

禁止：

- 重新执行。
- 重新搜索。
- 制造新事实。
- 把未验证结果包装成成功结果。

---

## 4.9 task_runtime：任务运行时版本层

### 定位

保存任务运行时修订、版本、执行结构，用于任务重复执行、调度、恢复和追踪。

### 当前模块

| 模块 | 功能 |
|---|---|
| `task_runtime/contracts.py` | TaskRuntimeRevision |

### 设计边界

- 只存储任务运行结构和版本。
- 不写具体任务业务逻辑。
- 不代替 workflow planner。

---

## 4.10 apps/api：API 与 UI 接入层

### 定位

系统入口层，负责 HTTP API、SSE、上传文件、运行任务、注册工具执行、Agent Studio 交互。

### 当前主要文件

| 文件 | 功能 |
|---|---|
| `apps/api/server.py` | FastAPI 主入口，聚合 runtime、studio、perception、tool、approval、scheduler 等服务 |

### 当前风险

`apps/api/server.py` 职责较重。建议拆分为：

- chat routes
- artifact routes
- runtime tool routes
- agent studio routes
- scheduler routes
- runtime console routes
- feedback repair routes

API 层应该只是入口和协议转换层，不能成为业务判断层或第二主脑。

---

## 5. ai_core 十层主流程对照

| Design-Concept 层 | v对应模块 | 当前评价 |
|---|---|---|
| 1. input_parsing | `perception_brain` + `ai_core/input_parsing` | 基本符合，感知与清洗分离更合理 |
| 2. intent_recognition | `ai_core/interaction`、`ai_core/modules`、`ai_core/workflow` 部分 | 需要确认具体实现是否过度依赖关键词 |
| 3. requirement_completion | `auxiliary_brain/parameters`、`AgentStudioService` | 符合方向 |
| 4. context_awareness | `memory_brain`、`ai_core/context` | 符合方向，但边界需继续统一 |
| 5. workflow_planning | `ai_core/workflow`、`ai_core/graph`、`ai_core/orchestration` | 符合方向 |
| 6. pre_execution_validation | `verification_brain`、`ai_core/validation` | 符合方向，建议统一到 verification_brain |
| 7. execution | `ai_core/executors`、`ai_core/runtime`、registered tools | 符合，但必须只执行 plan |
| 8. result_verification | `verification_brain`、`ai_core/execution/*validator*` | 符合，但建议集中边界 |
| 9. feedback_repair | `repair_brain`、`auxiliary_brain/capability_acquisition/repair_coordinator.py` | 符合，但需防止重复修复入口 |
| 10. final_synthesis | `presentation_brain`、`ai_core/presentation` | 方向符合，建议减少 ai_core/presentation 重复 |

---

## 6. 硬编码与业务词检查结果

### 6.1 明显具体业务能力硬编码

在本次快速扫描中，未发现 `ai_core` 中直接硬写天气、SMTP、Gmail、Shopify、酒店、旅游、SharePoint 等具体能力实现。

这比旧版更符合：

```text
ai_core 只做通用大脑与运行时操作系统；具体能力由运行时生成、组合、执行、验证。
```

### 6.2 仍需清理的业务词残留

发现少量示例性业务词：

| 文件 | 内容类型 | 风险 |
|---|---|---|
| `auxiliary_brain/parameters/agent_parameter_contract.py` | 注释中出现 `Fukuoka`、`Tokyo` 示例 | 违反严格“业务词不入代码”标准 |
| `auxiliary_brain/delegation/delegation_runtime.py` | 注释中出现 `topic=fukuoka` 示例 | 应改为 `topic=example_topic` |

建议改法：

```text
Fukuoka / Tokyo     → example_location / location_value
for Fukuoka         → for <location_value>
topic=fukuoka       → topic=example_topic
```

### 6.3 结构性 marker 是否算硬编码

`CapabilityClassifier` 中存在以下 marker：

- standard library
- no external package
- offline
- do not call external network
- not hardcoded
- external api
- oauth
- browser automation
- third-party sdk

这些不是业务词，而是运行时能力分类的结构性约束词。当前可以接受，但建议迁移到配置文件，例如：

```text
runtime/configs/capability_classification_policy.json
```

这样可以避免代码继续变成规则表。

---

## 7. 三个角色验收意见

## 7.1 高端设计者验收

### 通过点

- 多脑结构已经形成。
- `ai_core` 与 `auxiliary_brain` 职责开始分离。
- 能力生成链路已经迁移到 auxiliary_brain。
- LayerContract 已经明确每层允许和禁止的决策。
- verification / repair / presentation 被拆出，符合架构方向。

### 不足点

- `ai_core/runtime` 仍然偏重，长期看应继续内聚为 runtime kernel + runtime services。
- `ai_core/presentation`、`ai_core/feedback_repair` 与新脑模块存在职责重叠。
- capability acquisition router 过大，建议拆成多个职责单一的组件。

### 设计结论

v21 可以作为“多脑架构过渡版”，但还不是最终纯净版。

---

## 7.2 高级代码实现者验收

### 通过点

- 目录结构清晰度明显提升。
- 运行时能力生成、验证、注册链路已有实际代码支撑。
- 生成代码硬编码检测器已经存在。
- 注册工具执行服务和 schema validation 已经存在。
- API 层已经能连接 runtime、studio、perception、tool、approval、scheduler 等服务。

### 不足点

- 大文件仍然较多，后续维护成本偏高。
- 部分兼容层和旧模块还没有完全迁移。
- 一些命名仍可能导致边界混乱，例如 ai_core 中保留 presentation/feedback_repair。
- 注释示例中有业务词残留。

### 实现结论

代码实现方向正确，但需要进行“边界清洁”和“大文件拆分”。

---

## 7.3 魔鬼检验者验收

### 通过点

- 未发现 ai_core 直接写死具体业务能力的明显问题。
- 已加入动态值硬编码检测工具。
- 能力注册前存在 sandbox validation 链路。
- LayerContract 明确了 late-layer 不允许 replan 的原则。

### 阻塞级问题

本次没有发现必须立即阻塞架构文档提交的阻塞级问题。

### 必须修复问题

1. 清理所有示例业务词。
2. 把 `CapabilityClassifier` marker 配置化。
3. 拆分 `acquisition_router.py`，降低单文件职责复杂度。
4. 统一 `feedback_repair` 到 `repair_brain`。
5. 统一 `presentation` 到 `presentation_brain`。
6. API 层拆 routes，避免 server.py 无限膨胀。

### 魔鬼结论

v21 的设计方向可以继续，但不能再继续往 `ai_core` 塞功能。下一版重点不是增加业务能力，而是清理边界、减少重复、加强验证报告。

---

## 8. 推荐的目标目录结构

```text
cdac-nesthub/
├── ai_core/
│   ├── architecture/
│   ├── input_parsing/
│   ├── intent_recognition/
│   ├── workflow/
│   ├── graph/
│   ├── orchestration/
│   ├── executors/
│   ├── runtime_kernel/
│   ├── llm/
│   ├── context/
│   ├── security/
│   ├── approval/
│   └── validation_contracts/
│
├── auxiliary_brain/
│   ├── capability_acquisition/
│   │   ├── classification/
│   │   ├── identity/
│   │   ├── blueprint/
│   │   ├── specification/
│   │   ├── code_generation/
│   │   ├── sandbox_validation/
│   │   ├── registration/
│   │   └── execution_verification/
│   ├── runtime_codegen/
│   ├── parameters/
│   ├── delegation/
│   ├── studio/
│   └── protocols/
│
├── perception_brain/
├── memory_brain/
├── evidence_engine/
├── verification_brain/
├── repair_brain/
├── presentation_brain/
├── task_runtime/
├── apps/
│   └── api/
│       ├── routes/
│       ├── schemas/
│       └── server.py
│
├── runtime/
│   ├── generated/
│   ├── registry/
│   ├── configs/
│   ├── logs/
│   └── traces/
│
└── docs/
    ├── architecture/
    └── verification/
```

---

## 9. 下一版修改清单

### P0：必须完成

1. 清理代码中的示例业务词。
2. 确认 `ai_core` 不包含具体能力实现。
3. capability acquisition 全链路输出统一 trace。
4. sandbox validation 失败时不允许 registry 写入。
5. final answer 必须区分：计划完成、生成完成、验证完成、注册完成、执行完成。

### P1：建议完成

1. 拆分 `acquisition_router.py`。
2. 拆分 `apps/api/server.py`。
3. 把 `CapabilityClassifier` marker 移到配置。
4. 合并或废弃 `ai_core/presentation`，统一到 `presentation_brain`。
5. 合并或废弃 `ai_core/feedback_repair`，统一到 `repair_brain`。

### P2：持续优化

1. 增加架构边界自动扫描。
2. 增加业务词黑名单扫描，但黑名单放配置，不写在核心逻辑。
3. 增加生成代码洁净度报告。
4. 增加 capability acquisition lifecycle 可视化。
5. 增加每个脑的 contract test。

---

## 10. 最终结论

v21 已经基本进入正确方向：

```text
ai_core = 通用主脑 + 运行时操作系统
auxiliary_brain = 能力生成、参数补全、任务协作、运行时代码治理
perception_brain = 输入感知
memory_brain = 上下文记忆
verification_brain = 魔鬼验证
repair_brain = 修复恢复
presentation_brain = 最终表达
evidence_engine = 证据收集
task_runtime = 任务运行时版本
```

但 v21 还不能称为完全纯净版。下一版的重点应是：

```text
少加功能，多清边界；
少写规则，多做配置；
少说成功，多做验证；
具体能力永远生成在 runtime 外围，不进入 ai_core。
```
