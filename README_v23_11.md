# cdac-nesthub v23.11 - Capability Acquisition Regression Stability Fix

## Goal
Restore the capability acquisition path so a generated runtime implementation can move through:

Capability Request -> Blueprint -> LLM Code Generation -> Local Preflight -> Repair -> Sandbox -> Registry

without introducing capability-specific code into `ai_core` or `code_generator.py`.

## Changes

1. **No silent basic-to-medium/critical escalation**
   - `RuntimeBlueprintArtifactGenerator._generation_attempts("basic")` now stays in the `basic` policy band.
   - Failed basic generation attempts are repaired in the same band instead of jumping to hosted/high-complexity routes.

2. **Preflight failure is now repair evidence, not a dead end**
   - The failed preflight details are passed into the next LLM generation attempt.
   - The failure includes stdout/stderr, reason, verification input, and a short generated artifact summary.

3. **Detailed failure visibility**
   - `code_generation` now records:
     - `attempts`
     - `preflight`
     - `failed_artifact`
     - `interaction_request` when needed
   - This prevents generic errors such as `Generated artifact did not pass local runtime preflight` from hiding the real cause.

4. **Generic generation guidance**
   - Added capability-neutral instructions requiring JSON-native output and safe normalization of user/default strings.
   - No Gmail/SMTP/time/zoneinfo/weather-specific implementation logic was added.

5. **Verification**
   - Added `tools/verify_v23_11_preflight_repair_stability.py`.
   - Verified that a first generated artifact failing JSON serialization is repaired into a valid runtime implementation without escalating from basic.

## Verified commands

```bash
PYTHONPATH=. python tools/verify_v23_8_provider_routing.py
PYTHONPATH=. python tools/verify_v23_10_brain_model_route_compat.py
PYTHONPATH=. python tools/verify_v23_11_preflight_repair_stability.py
python -m py_compile auxiliary_brain/capability_acquisition/code_generator.py \
  ai_core/model_orchestration/litellm_brain_client.py \
  ai_core/model_orchestration/brain_model_router.py
```
