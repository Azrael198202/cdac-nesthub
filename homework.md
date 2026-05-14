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

# homework 1.1.1

一阶段：意图解析与参数提取 (Reasoning)
当我接收到你的请求时，我首先会进行语义分析：

识别意图：用户想要查询天气（Weather Forecast）。

提取关键参数：

地点：福冈，日本 (Fukuoka, Japan)。

时间：明天 (Tomorrow，我会根据当前的系统时间计算出具体的日期)。

详情程度：用户要求“Detailed”（详细），这意味着我不仅要提供气温，还要关注降水概率、风速、湿度等。

 没有分析出来 “Detailed”（详细）这个概念，会影响后续的内容。


第二阶段：工具调用决策 (Tool Calling)
我本身并不实时连接气象卫星，但我拥有“工具库”（Tools）。

选择工具：我会决定调用类似 Google Search 或专门的天气 API 接口。

构造查询：我会生成一个结构化的指令，例如：search_weather(location="Fukuoka", date="2024-XX-XX")。

发送请求：系统根据我的指令去抓取实时数据。

后续是不是需要创建工具库，并且读取别人的工具库，导入到自己的系统中来使用。


第三阶段：数据过滤与整合 (Data Processing)
这是最关键的一步。工具返回的数据通常是杂乱的原始信息（JSON 格式或网页快照），可能包含：

每小时气温趋势

紫外线指数

日出日落时间

体感温度

降雨预警

我会根据你要求的 "Detailed"，从海量信息中筛选出最重要的部分，过滤掉无关的广告或冗余链接。

第四阶段：生成最终回答 (Generation)
我会将筛选后的枯燥数据转化为自然语言。我会考虑：

语气：友好且专业。

逻辑：先整体（晴天/雨天），后局部（最高/最低温），再到细节（建议穿衣或带伞）。

语言习惯：既然你用英文提问，我通常会用英文回答，除非你有特殊要求。

实际案例模拟
如果你现在问我这个问题，后台的 Token 往返大致如下：

Input (你): "Could you please check the detailed weather forecast for Fukuoka, Japan tomorrow?" (~15 tokens)

Thought (我): 确定需要调用天气工具，计算出“明天”的具体日期。

Tool Call: 发出查询指令。

Tool Output: 收到数据（例如：18°C-24°C, 阵雨概率 40%, 西北风 15km/h）。

Final Output (我): "Tomorrow in Fukuoka, expect a mix of clouds and sun with a 40% chance of afternoon showers. Highs will be around 24°C..."

# homework 1.2

tasks should be structured objects instead of string array.
Need task_id/task_type/action/parameters.
Booking actions require human confirmation.
Need more missing_information fields.


INTENT_RECOGNITION_PROMPT = """
Regenerate intent_recognition as executable orchestration state.

Requirements:

1. Return valid JSON only.
2. Do not generate explanations, markdown, or natural-language summaries.
3. Do not place missing information inside reason or description fields.
4. All missing information must be represented structurally.
5. tasks must be an array of task objects.
6. Each task object must include:

   * task_id
   * task_type
   * capability_action
   * parameters

     * known
     * missing_required
     * optional
   * depends_on
   * requires_human_confirmation
   * execution_ready
7. task_type must use hierarchical dot notation such as:

   * weather.forecast.query
   * travel.flight.booking
   * finance.expense.record
8. Irreversible or externally committed actions must set:
   requires_human_confirmation=true
   Examples:

   * booking
   * payment
   * purchase
   * reservation
   * deletion
9. If required parameters are missing:

   * execution_ready must be false
10. human_review must be structured:

* required
* reason_codes
* review_items

11. confidence must be structured:

* overall
* intent
* execution_readiness

12. Preserve semantic modifiers from the user request when relevant.
    Examples:

* detailed
* urgent
* cheapest
* nearby

13. Do not infer unavailable required parameters.
14. Focus on executable orchestration state, not conversational explanation.
    """

workflow_plannning

WORKFLOW_PLANNING_PROMPT = """
Regenerate workflow_planning as executable workflow state.

Requirements:

1. Return valid JSON only.
2. Do not explain the workflow in natural language.
3. planned_steps must describe executable orchestration steps.
4. Do not simply copy tasks from intent_recognition.
5. Each planned step must include:

   * step_id
   * step_type
   * objective
   * input_from
   * required_capability
   * execution_ready
   * human_interaction
   * next_action
6. workflow_planning must transform intent tasks into execution-oriented workflow steps.
7. If executable capability is unavailable:

   * create capability_discovery steps
   * create external_solution_discovery steps
   * create sandbox_validation steps if runtime code generation is required
8. Weather or information queries may proceed immediately to:

   * capability discovery
   * external API discovery
   * execution
     if required parameters are available.
9. Booking, payment, reservation, purchase, or destructive actions must include:

   * collect_missing_information
   * confirm_before_execution
   * execution_pending_confirmation
10. blocking_missing_information must be grouped by task_id.
11. required_capabilities must include:

* capability_action
* purpose
* status

12. execution_ready=true only if:

* required parameters exist
* required capability is available or discoverable

13. Workflow steps may dynamically include:

* model_discovery
* github_solution_discovery
* runtime_tool_generation
* docker_sandbox_execution
* verification

14. Focus on executable orchestration planning, not static task description.
    """



Check whether missing_required contains only optional refinement fields.
If yes, call execution_state_repair before marking the step as blocked.
Do not block information retrieval tasks because of optional fields such as:
time_range
output_format
detail_level
language
sorting_preference
Block only when execution is impossible or unsafe.
If required_capability.status is available and execution_ready is true, execute the step.
If capability is unavailable, start capability discovery instead of returning blocked.


# workflow 1.0 