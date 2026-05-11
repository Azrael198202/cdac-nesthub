# Runtime Visible AI Core

一个最小可运行的 Config-Driven AI Core 示例。

特点：
- `ai_core` 是固定执行引擎
- `runtime/configs` 定义 workflow / intent / model / tools / prompt
- Web UI 类似 ChatGPT / Codex，可以看到执行过程
- 支持 SSE 流式事件：intent、planning、tool call、approval、final answer
- 示例任务：`Please check the weather forecast for Tokyo tomorrow and then book a flight to Tokyo.`

## 启动

```bash
pip install -r requirements.txt
python main.py
```

打开：

```text
http://127.0.0.1:8000
```

## 测试 API

```bash
python scripts/smoke_test.py
```

## 外部模型

默认会走规则模型 / mock 模型，保证无 API Key 也能跑。
如果需要 OpenAI：

```bash
export OPENAI_API_KEY=你的key
```

然后修改：

```text
runtime/configs/models/model_router.yaml
```
