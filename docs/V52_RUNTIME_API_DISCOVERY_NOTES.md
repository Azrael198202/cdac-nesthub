# v52 Runtime API Discovery / Tool Generation Update

## Goal

v52 strengthens runtime API selection and runtime tool generation without adding business-specific logic to `ai_core`.

`ai_core` remains responsible only for generic orchestration:

- runtime workflow planning
- generic web research
- API documentation evidence collection
- runtime model based API selection
- runtime tool artifact generation
- generic tool installation
- generic execution and provenance

Business/domain concepts, concrete API vendors, endpoints, parameter mappings, and output formatting logic are generated or selected at runtime from user input, runtime context, and external documentation evidence.

## Main changes

### 1. API discovery now includes documentation search and fetch

Updated:

- `ai_core/research/api_discovery.py`
- `ai_core/research/web_research_tool.py`

The discovery flow is now:

```text
user request
  -> runtime workflow step
  -> generic API documentation search queries
  -> fetch candidate documentation pages
  -> ask configured runtime model to select a candidate API
  -> ask runtime model to understand authentication / request parameters / response shape / verification plan
  -> pass selected evidence into runtime tool generation
```

The core does not choose a specific API provider. It only collects evidence and passes that evidence to runtime intelligence.

### 2. Tool generation is blocked when API documentation evidence is insufficient

Updated:

- `ai_core/executors/tool_call_executor.py`

If API discovery cannot produce enough documentation-backed evidence, v52 blocks executable code generation with:

```text
status = api_documentation_evidence_insufficient
```

This prevents the runtime from generating tools using guessed endpoints, guessed parameters, mock data, or hallucinated API usage.

### 3. Runtime semantics are dynamic, not fixed schema fields

v52 does not add fixed fields such as `detail_level` to core schemas.

Instead, runtime request meaning is passed as generic runtime semantics:

```json
{
  "runtime_request_semantics": {
    "original_user_input": "...",
    "objective": "...",
    "action": "...",
    "task_type": "...",
    "known_parameters": {},
    "optional_parameters": {},
    "missing_required": {},
    "runtime_modifiers": [],
    "runtime_constraints": {},
    "output_preferences": {}
  }
}
```

Terms such as “detailed”, “simple”, “latest”, “official”, “compare”, etc. should be preserved dynamically by the runtime planner as modifiers/constraints/output preferences. They are not hardcoded into core.

### 4. Runtime generated tools receive API documentation understanding

Updated:

- `ai_core/tools/runtime_tool_artifact_generator.py`
- `ai_core/tools/runtime_generated_tool_installer.py`

Generated tools now receive:

- `api_discovery`
- `documentation_understanding`
- `runtime_request_semantics`
- `parameter_mapping`
- verification requirements

The generated tool artifact should include:

- `tool.py`
- `tool.json` manifest
- execution claims
- API discovery metadata
- documentation understanding
- parameter mapping
- verification metadata

### 5. Workflow prompts were adjusted

Updated:

- `ai_core/runtime/runtime_template_generator.py`
- `runtime/generated/prompts/*.yaml`

Planning rules now say:

- relative expressions from user input are not missing information
- modifiers, constraints, specificity, and completeness expectations must be preserved as runtime semantics
- external real-world data steps should describe a generic capability
- API providers should not be selected during workflow planning unless the user explicitly supplies one

## Hard boundary check

The following business/provider tokens are not present under `ai_core`:

```text
weather
forecast
Open-Meteo
Fukuoka
```

They may appear only in runtime-generated artifacts, traces, tests, or user inputs.

## Validation performed

```bash
python3 -m py_compile $(find ai_core -name '*.py')
python3 scripts/smoke_test.py
```

Both passed.
