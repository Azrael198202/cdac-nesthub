# AI Core Full Runtime Self-Bootstrap v2

完整工程版。

## 核心原则

```text
ai_core = 通用执行引擎，不包含具体业务逻辑
runtime = 运行时生成 configs / workflows / prompts / checkpoints / traces / knowledge
apps = Web/API 交互
tools = 可扩展工具层
```

## 已实现

- Runtime 冷启动
- Provider / model 自检
- 缺 Ollama / 模型时，通过审批自动安装 / 启动 / 下载
- 命令 stdout / stderr 实时显示到页面
- 大处理过程显示进度百分比
- Workflow checkpoint / resume
- Human Review: Approve / Reject
- 中间对话区 stream 显示执行过程
- 右侧 Execution Workflow stream
- 输入框固定底部
- 消息区和右侧事件区独立滚动
- Approval 卡片 UI 修复，不再错位
- 不包含固定业务逻辑

## 启动

```bash
pip install -r requirements.txt
python main.py
```

打开：

```text
http://127.0.0.1:8000
```

## 说明

第一次运行时 `runtime/` 基本为空。系统运行后自动生成：

```text
runtime/configs/environment/providers.yaml
runtime/configs/workflows/base_orchestration.yaml
runtime/configs/models/model_routes.yaml
runtime/configs/capabilities/task_capability_map.yaml
runtime/checkpoints/
runtime/traces/
runtime/knowledge/
runtime/datasets/
```

软件安装、启动服务、下载模型等操作默认需要人工审批。
