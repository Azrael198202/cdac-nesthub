# Web Evidence Pipeline Update

## 修改目的

这次修改明确区分：

- `ai_core`：只判断是否需要外部信息、锁定通用执行方式、定义 evidence contract、阻止无证据最终回答。
- `auxiliary_brain`：负责搜索引擎 URL 发现、网页抓取、证据验证输入材料的准备。

没有在 `ai_core` 中加入天气、邮件、Gmail、Fukuoka 等业务关键词。

## 网站 URL 如何确定

默认不是模型直接生成 URL，也不是写死业务网站。

流程为：

1. LLM intent 判断是否需要 web search。
2. workflow planning 锁定 `execution_method=web_search`。
3. `auxiliary_brain.research.GenericWebResearchTool` 根据 query 通过搜索引擎发现候选 URL。
4. 对候选 URL 执行 fetch。
5. 用通用 evidence verifier 判断抓取文本是否与用户请求匹配。
6. 只有 verification passed 的 source material 才能进入 final synthesis。

## 当前支持的搜索引擎 Provider

当前已定义：

1. `duckduckgo_html`
   - 默认 provider
   - 不需要 API Key
   - 使用 DuckDuckGo HTML 搜索页

2. `bing_api`
   - 可选
   - 需要环境变量：
     - `AI_CORE_WEB_SEARCH_PROVIDER=bing_api`
     - `BING_SEARCH_ENDPOINT`
     - `BING_SEARCH_API_KEY`

3. `google_custom_search`
   - 可选
   - 需要环境变量：
     - `AI_CORE_WEB_SEARCH_PROVIDER=google_custom_search`
     - `GOOGLE_CSE_ID`
     - `GOOGLE_API_KEY`

4. `auto`
   - 默认模式
   - 如果 Bing / Google 配置存在，会优先尝试
   - 否则自动回退 DuckDuckGo HTML

## 修改文件

### ai_core/interaction/conversation_core_runtime.py

- 增加 LLM Web Search Decision 逻辑。
- 不再仅凭 `newest/latest/current` 等词强制进入 web search。
- `external_information_signals` 只作为观察信号，不作为唯一决策。
- 增加 `web_search_decision` 合同。
- web search 执行后强制验证 evidence。
- verification 未通过时，不允许 final_synthesis 调用模型补答案。
- final answer 必须来自 verified source material，否则输出明确失败原因。

### auxiliary_brain/research/web_research_tool.py

- 明确 URL discovery method。
- 支持 provider config 输出。
- 默认 DuckDuckGo HTML。
- 可选 Bing API。
- 可选 Google Custom Search API。
- 每次搜索返回：
  - `provider_config`
  - `attempts`
  - `results`
  - `search_strategy`

## 验证

- `python -m compileall -q ai_core auxiliary_brain apps`
- `python scripts/verify_ai_core_boundary.py`

均通过。
