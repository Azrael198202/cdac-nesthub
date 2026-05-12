# homework 0
说明 VS Code 正在用 Homebrew 的 Python 3.14，而不是你安装依赖的环境。

先在项目目录执行：

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt

然后 VS Code 里选择解释器：

Cmd + Shift + P
Python: Select Interpreter
选择：
./.venv/bin/python

ai_core.llm.provider_router.ProviderUnavailableError: No real LLM provider is available. Start Ollama or set OPENAI_API_KEY. Config file: runtime/configs/models/providers.yaml. Last error: None
INFO:     127.0.0.1:60364 - "GET /api/events/8359d50fbd6d HTTP/1.1" 200 OK

ide：trae


# homework 1

现在这个阶段，其实已经进入了：

Human-in-the-Loop (HITL)

也就是：

LLM → 给出结构化结果
Human → 修正 / 反馈
Core → 学习并优化后续结果

所以现在正确的操作，不是直接点 Approve。

你现在有 4 种操作：

1. Approve

适合：

结果已经满足需求

现在这个结果：

"tasks": [
  "check weather forecast for Tokyo tomorrow",
  "book flight to Tokyo"
]

还不够结构化。

所以：

现在不建议点 Approve
2. Reject & Retry（推荐第一次这样做）

你应该输入：

tasks should be structured objects instead of string array.
Need task_id/task_type/action/parameters.
Booking actions require human confirmation.
Need more missing_information fields.

然后点：

Reject & Retry

这会触发：

human_feedback → runtime state
↓
重新进入 input_parsing
↓
LLM 带着人类反馈重新生成

这就是：

AI Self-Correction Loop
3. Modify JSON & Continue（推荐第二阶段使用）

这是：

你直接教 AI 正确结构

例如你直接修改成：

{
  "language": "en",
  "intent_type": "multi_step_action_request",
  "tasks": [
    {
      "task_id": "task_1",
      "task_type": "weather_forecast",
      "action": "check_weather_forecast",
      "location": "Tokyo",
      "date": "tomorrow"
    },
    {
      "task_id": "task_2",
      "task_type": "flight_search_or_booking",
      "action": "prepare_flight_booking",
      "destination": "Tokyo",
      "requires_final_human_confirmation": true
    }
  ],
  "missing_information": [
    "departure_city",
    "travel_date",
    "passenger_details",
    "final_booking_confirmation"
  ],
  "required_capabilities": [
    "weather_forecast_api",
    "flight_search_api",
    "human_confirmation"
  ]
}

然后：

Modify JSON & Continue

这会：

把“正确结构”直接注入 workflow state

后续：

intent_recognition
workflow_planning
execution

都会基于你修正后的 JSON。

4. Edit JSON（最重要）

你现在其实已经接近：

Runtime Teaching System

也就是说：

Human 不只是审批
Human 在训练 AI Core

你应该：

Edit JSON
↓
修改成标准结构
↓
Modify JSON & Continue

# homework 1.1 
Runtime Learning

当用户：

Modify JSON & Continue

时：

core 应自动：

1. 记录 original_output
2. 记录 modified_output
3. 形成 correction dataset
4. 写入 runtime/datasets/corrections.jsonl
5. 更新 prompt optimization memory

例如：

{
  "node": "input_parsing",
  "original_output": {...},
  "human_corrected_output": {...},
  "feedback": "tasks should be structured objects"
}
后续效果

下一次：

类似任务

时：

core 会自动：

从 correction memory 检索
↓
自动强化 prompt
↓
减少错误

这才是真正的：

Self-Evolving Runtime AI Core

# homework 1.2

tasks should be structured objects instead of string array.
Need task_id/task_type/action/parameters.
Booking actions require human confirmation.
Need more missing_information fields.


intent

Please regenerate this node output as executable orchestration state, not as explanation.

Requirements:
1. Do not put missing information inside reason.
2. Output missing information as structured fields.
3. tasks must be an array of objects.
4. Each task must include:
   - task_id
   - task_type using dot notation, such as weather.forecast.query or travel.flight.booking
   - capability_action
   - parameters.known
   - parameters.missing_required
   - parameters.optional
   - depends_on
   - requires_human_confirmation
   - execution_ready
5. Booking, payment, purchase, reservation, and irreversible actions must set requires_human_confirmation=true.
6. If required parameters are missing, execution_ready must be false.
7. Use human_review object instead of plain requires_human_review boolean.
8. Confidence should be structured:
   - overall
   - intent
   - execution_readiness
9. Do not explain the correction in reason.
10. Return valid JSON only.