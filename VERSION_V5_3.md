# cdac-nesthub v5.3 runtime-framework-restored

This release is based on v5.2 agent action prompt contract and restores the runtime framework that was removed too aggressively.

Key points:
- Keeps agent_action_planning prompt contract: content / target / action candidates / rules.
- Restores ai_core/runtime framework modules.
- Restores top-level runtime static configs/registry/datasets.
- Excludes runtime-generated artifacts such as generated, traces, checkpoints, cache, tmp, and sessions.
- Keeps business/domain-specific logic out of ai_core; action selection remains driven by runtime prompt contracts and schemas.
