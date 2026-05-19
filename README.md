# AI Runtime OS V2.8.18 Language-Neutral Temporal Alignment Runtime

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
