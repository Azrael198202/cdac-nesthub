# cdac-nesthub v23.8 provider routing normalization

This build fixes the model-provider path used by runtime capability acquisition.

Key changes:

- Basic runtime code-generation requests stay on local/basic routes first; they no longer auto-escalate to critical/OpenAI just because a local attempt failed.
- OpenAI provider options remain sanitized for GPT-5-compatible parameters.
- Missing provider secrets are surfaced through the interaction request payload instead of being treated as capability-generation failure.
- Ollama model resolution now distinguishes imported/custom models from pullable catalog models:
  - exact installed model names are honored first;
  - imported models are not blindly pulled;
  - only models listed in `configs/model_resolution.yaml` or `AI_CORE_OLLAMA_PULLABLE_MODELS` are auto-pulled;
  - installed coder/code-capable models are preferred when the requested model is unavailable.
- Capability generation logic remains generic and contains no capability-specific implementation patches.
