# AI Core Boundary Migration

本次重构目标：将不属于 `ai_core` 通用大脑/运行时操作系统边界的实现内容移动到 `auxiliary_brain`，同时保留兼容 facade，保证原 import 路径和执行逻辑不变。

## 移动原则

- `ai_core` 保留：输入清洗、意图识别、上下文、workflow/graph、执行契约、结果验证、最终汇总等通用运行时 OS 职责。
- `auxiliary_brain` 承接：运行时工具生成、能力获取、沙箱验证、外部研究、媒体能力、模型/Provider 生命周期、Artifact 管理、Runtime Studio/Observability、Schedule Runner 等可执行/可扩展实现。
- 原 `ai_core.*` import 不删除，改为 facade 转发，降低一次性迁移风险。

## 移动列表

- `ai_core/artifacts` -> `auxiliary_brain/artifacts`
- `ai_core/dependencies` -> `auxiliary_brain/dependencies`
- `ai_core/environment` -> `auxiliary_brain/environment`
- `ai_core/media` -> `auxiliary_brain/media`
- `ai_core/models` -> `auxiliary_brain/models`
- `ai_core/modules` -> `auxiliary_brain/runtime_modules`
- `ai_core/providers` -> `auxiliary_brain/providers`
- `ai_core/research` -> `auxiliary_brain/research`
- `ai_core/sandbox` -> `auxiliary_brain/sandbox`
- `ai_core/tools` -> `auxiliary_brain/runtime_tools`
- `ai_core/web_evidence_optimizer` -> `auxiliary_brain/web_evidence_optimizer`
- `ai_core/runtime/capability` -> `auxiliary_brain/runtime/capability`
- `ai_core/runtime/external_runtimes` -> `auxiliary_brain/runtime/external_runtimes`
- `ai_core/runtime/generated_execution` -> `auxiliary_brain/runtime/generated_execution`
- `ai_core/runtime/learning` -> `auxiliary_brain/runtime/learning`
- `ai_core/runtime/observability` -> `auxiliary_brain/runtime/observability`
- `ai_core/runtime/scheduler` -> `auxiliary_brain/runtime/scheduler`
- `ai_core/runtime/self_repair` -> `auxiliary_brain/runtime/self_repair`

## 兼容方式

每个被移动的 `ai_core` Python 文件保留同名 wrapper，例如：

```python
from auxiliary_brain.runtime_tools.runtime_tool_registry import *
```

这样现有代码仍可通过旧路径运行，后续可以逐步把 import 改成新路径。

## 验证

已执行 `python -m compileall` 对主要源码目录进行语法验证。
