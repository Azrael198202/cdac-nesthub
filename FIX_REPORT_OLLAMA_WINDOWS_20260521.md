# 2026-05-21 修复报告：Windows 默认切换回 Ollama

## 结论

vLLM 不适合作为 Windows 开发环境的默认本地 provider。本次修复把默认本地模型运行时切换回 Ollama，并将 vLLM 改为显式启用的可选 Linux/GPU provider。

## 修复点

1. 默认路由从 `vllm -> ollama` 改为 `ollama -> openai -> claude`。
2. `input_parsing / intent_recognition / workflow_planning / reasoning / synthesis` 默认优先使用 Ollama。
3. `code_generation` 默认优先使用 `ollama_coder_qwen25`。
4. `vllm` 和 `vllm_coder` 默认 `enabled: false`。
5. 只有设置 `AI_CORE_ENABLE_VLLM=1` 时，vLLM 才允许进入路由。
6. `UserModelSelectionStore` 默认从 `api_only` 改为 `local_only`，初始模型为 `qwen3:8b`。
7. Ollama 缺失时 fail fast，0.6 秒左右返回结构化失败，不再等待 vLLM 或长时间超时。
8. 保持 ai_core 不写业务词或业务逻辑，只调整 provider/runtime 策略。

## Windows 推荐启动步骤

```powershell
ollama --version
ollama serve
ollama pull qwen3:8b
ollama pull qwen3:4b
ollama pull qwen2.5-coder:7b
```

然后启动项目。

## 可选：Linux/GPU 环境启用 vLLM

```bash
export AI_CORE_ENABLE_VLLM=1
python -m pip install -r requirements-vllm.txt
```

Windows 下不建议启用 vLLM。

## Sandbox 验证

```bash
PYTHONPATH=. python tests/smoke_runtime_no_provider.py
```

结果：

- 不再尝试启动 vLLM
- 默认路由为 Ollama
- 没有 Ollama 可执行文件时快速结构化失败
- 不再 fake completed
