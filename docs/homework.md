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

workflow_plannning

Regenerate workflow_planning as executable workflow state.

Requirements:
1. Do not simply copy tasks from intent_recognition.
2. planned_steps must describe workflow execution steps, not original tasks.
3. Each step must include:
   - step_id
   - step_type
   - objective
   - input_from
   - required_capability
   - execution_ready
   - human_interaction
   - next_action
4. Split flight booking into:
   - collect_missing_information
   - confirm_booking_before_execution
   - booking_execution_pending
5. Weather query can be executable immediately.
6. Flight booking must not execute because required information is missing.
7. blocking_missing_information must be grouped by task_id.
8. required_capabilities must include capability purpose and status.
9. Return valid JSON only.



## input_parsing
Reject & Retry input_parsing.

Required fixes:
1. Return valid JSON only.
2. tasks must remain a string array according to the current schema.
3. Do not output natural-language task descriptions.
4. tasks should contain normalized executable task identifiers, for example:
   - "weather_forecast.query"
   - "weather_forecast.detailed_query"
5. Extract entities from the original input:
   - location
   - date_expression
   - semantic_modifiers
6. Preserve semantic modifiers such as "detailed".
7. Normalize relative temporal expressions using runtime_context.current_date and runtime_context.timezone.
8. If the schema supports parsed_entities, include:
   - location
   - date_expression
   - date
   - semantic_modifiers
9. date must use ISO format YYYY-MM-DD.
10. Do not add missing_information if location and date are already present or resolvable.
11. required_capabilities must remain a string array according to the current schema.
12. required_capabilities should describe generalized runtime capabilities, not implementation-specific APIs.
13. Replace implementation-specific values like:
   - "weather_forecast_api"
   with generalized capabilities such as:
   - "weather_forecast"
   - "external_information_lookup"
14. Do not add fields that are not accepted by the current schema.


## intent
Reject & Retry intent_recognition.

Required fixes:
1. tasks may remain a string array if required by the current schema.
2. Do not use natural-language task descriptions.
3. Add parsed_entities if supported by the schema.
4. parsed_entities should include:
   - location
   - date_expression
   - date
   - semantic_modifiers
5. Preserve both:
   - original temporal expression
   - normalized ISO date
6. confidence must be a structured object including:
   - overall
   - intent
   - execution_readiness
7. Do not force workflow_planning to re-extract entities already resolved in intent_recognition.
8. Return valid JSON only.

## workflow
Reject & Retry workflow_planning.

Required fixes:
1. Return valid JSON only.
2. planned_steps must be an array of executable step objects, not strings.
3. Do not output planned_steps like:
   "weather_forecast.detailed_query"
4. Do not create human_interaction fields for information already available from input_parsing or intent_recognition.
5. If location, date/date_expression, and semantic_modifiers are already known, human_interaction.required must be false.
6. Each planned step must include:
   - step_id
   - step_type
   - objective
   - input_from
   - required_capability
   - parameters
   - execution_ready
   - human_interaction
   - next_action
7. parameters must include:
   - known
   - missing_required
   - optional
8. parameters.known must include:
   - location
   - date_expression
   - date
   - semantic_modifiers
9. If missing_required is empty, execution_ready must be true.
10. next_action should be capability_resolution_or_execute.
11. Return no human input request unless required fields are actually missing.


当input_parsing改好了生成正确的json之后，
{
  "language": "en",
  "intent_type": "weather_forecast",
  "tasks": [
    "get detailed weather forecast for fukuoka tomorrow"
  ],
  "missing_information": [],
  "required_capabilities": [
    "weather_forecast_access"
  ],
  "safety_notes": [],
  "original_input": "could you please check the detailed weather forecast for fukuoka tomorrow?",
  "_executor_type": "llm_json",
  "_node_id": "input_parsing",
  "_adapter_id": "input_parsing_adapter"
}


调整后的
{
  "language": "en",
  "intent_type": "weather_forecast",
  "tasks": [
    {
      "task_id": "weather_forecast.detailed_query",
      "task_type": "weather_forecast",
      "action": "query",
      "parameters": {
        "location": "Fukuoka",
        "date_expression": "tomorrow",
        "date": "2023-10-06",
        "semantic_modifiers": [
          "detailed"
        ]
      }
    }
  ],
  "missing_information": [],
  "required_capabilities": [
    "weather_forecast"
  ],
  "original_input": "could you please check the detailed weather forecast for fukuoka tomorrow?",
  "_executor_type": "llm_json",
  "_node_id": "input_parsing",
  "_adapter_id": "input_parsing_adapter"
}


为什么intent又需要调整呢，例如task

有问题的intent
{
  "intent_type": "weather_forecast",
  "confidence": 0.95,
  "tasks": [
    "weather_forecast.detailed_query"
  ],
  "requires_human_review": false,
  "reason": "The intent to retrieve a detailed weather forecast for Fukuoka tomorrow is clear and correctly categorized.",
  "parsed_entities": {
    "location": "Fukuoka",
    "date_expression": "tomorrow",
    "date": "2023-10-06",
    "semantic_modifiers": [
      "detailed"
    ]
  },
  "required_capabilities": [
    "weather_forecast"
  ],
  "_executor_type": "llm_json",
  "_node_id": "intent_recognition",
  "_adapter_id": "intent_recognition_adapter"
}

重新生成的
{
  "intent_type": "weather_forecast",
  "confidence": {
    "overall": 0.95,
    "intent": 0.95,
    "execution_readiness": 0.95
  },
  "tasks": [
    {
      "task_id": "weather_forecast.detailed_query",
      "task_type": "weather_forecast",
      "action": "query",
      "parameters": {
        "location": "Fukuoka",
        "date_expression": "tomorrow",
        "date": "2023-10-06",
        "semantic_modifiers": [
          "detailed"
        ]
      }
    }
  ],
  "requires_human_review": false,
  "parsed_entities": {
    "location": "Fukuoka",
    "date_expression": "tomorrow",
    "date": "2023-10-06",
    "semantic_modifiers": [
      "detailed"
    ]
  },
  "required_capabilities": [
    "weather_forecast"
  ],
  "_executor_type": "llm_json",
  "_node_id": "intent_recognition",
  "_adapter_id": "intent_recognition_adapter"
}



### 新版本作业

1. 运行时，根据作业的内容，咨询openai或者其他模型，给出适合作业的最好的模型，
   加入到模型的配置文件中，并作为知识点，之后遇到类似的业务，都使用这个模型。
2. 建立多模型的选择，特别是api的模型，需要api key的模型。特别在input_parsing, intent, workflow 等阶段。
3. 通过强大的api 外部模型，可以对业务流程进行修改。