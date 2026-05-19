# AI Runtime OS V2.8.19 Source-Row Evidence Alignment Runtime

This package keeps the V2.8.x agent-studio / ai_core delegation architecture and replaces hard-coded natural-language temporal aliases with runtime-driven temporal alias generation.

Key changes:

- `ai_core` no longer hard-codes English month names for date alignment.
- Date alignment uses numeric aliases generated from normalized runtime dates.
- Natural-language aliases are supplied by runtime state or generated contracts, not static source code.
- `date_aligned_record_extractor.py` remains, but it is now a generic temporal row/record aligner.
- Multilingual support is handled by runtime-generated `temporal_aliases.json` or by LLM/runtime parsing outputs.
- Runtime output folders are clean; only `runtime/.gitkeep` is included.

Optional runtime alias contract:

```json
{
  "2026-05-19": ["19 May", "5月19日", "19 mai"],
  "2026-05-20": ["20 May", "5月20日", "20 mai"]
}
```

Place it at either:

- `runtime/generated/contracts/temporal_aliases.json`
- `runtime/configs/semantic/temporal_aliases.json`

These files are runtime/config artifacts and are intentionally not shipped as hard-coded language data.

Excluded from package:

- `__pycache__/`
- `*.pyc`
- `tests/`
- `scripts/`
- runtime generated traces/checkpoints/deliveries/cache


## V2.8.19 Source-Row Evidence Alignment Runtime

- Date-aligned extraction now rejects calendar/menu strips before measurement rows.
- Target records are selected by confidence and target date, so lower-quality row fragments do not override better source-backed records.
- The extractor remains language-neutral: natural-language date aliases are still supplied by runtime state or generated contracts, not hard-coded in ai_core.
- Runtime package excludes generated runtime artifacts, tests, scripts, __pycache__, and *.pyc.


## V2.8.21 Agent Studio Conversational Adaptation Runtime

This version adds a conversation-aware Agent Studio input layer. Natural-language feedback such as result dissatisfaction, re-optimization requests, or model upgrade requests is routed as runtime feedback instead of being rejected as an unknown command. The auxiliary layer records the feedback, requests model escalation for the final-response node, and re-synthesizes the previous task result without restarting completed participant work.

Key runtime behavior:
- command input still creates participants, creates tasks, and executes named tasks;
- conversational feedback is accepted as runtime adaptation input;
- model escalation signals are stored in the generic feedback store;
- re-optimization uses node-level final synthesis where possible;
- completed participant results are reused instead of rerunning the full task.
