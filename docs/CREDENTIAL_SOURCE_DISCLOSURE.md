# Credential Source Disclosure

This version makes credential recovery explicit and auditable.

When a credential-protected provider or API is available, the runtime now passes provider/source metadata into the pending action and UI:

- provider/API name
- source URL when available
- secret key name
- candidate sources considered
- continue-with-key and continue-without-key choices

The UI no longer shows only a generic key prompt when source metadata exists. If a provider does not declare a concrete credential source, the prompt still allows the user to skip that provider and continue with fallback methods.

The implementation is generic and does not hardcode domain-specific providers. Source metadata is derived from runtime candidate/provider contracts.
