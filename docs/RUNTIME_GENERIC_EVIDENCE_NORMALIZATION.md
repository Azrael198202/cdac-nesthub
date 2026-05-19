# Runtime Generic Evidence Normalization

This version adds a generic evidence normalization stage between raw source retrieval and final answer synthesis.

The stage does not contain domain-specific vocabulary or fixed request terms. It reads only runtime-provided contracts:

- known parameters from previous nodes
- normalized runtime values
- generated aliases
- source text blocks
- generic numeric and unit patterns
- output quality requirements

Pipeline:

```text
retrieved source material
  -> visible block extraction
  -> runtime-value alignment
  -> compact evidence selection
  -> structured observation records
  -> quality gate
  -> final synthesis from normalized facts only
```

Important rule:

```text
ai_core must not decide target meaning by hard-coded words.
All target matching comes from runtime state created by parsing, intent, and planning nodes.
```

This prevents full-page source dumps, menu text, navigation fragments, and unrelated long sections from becoming final answers.
