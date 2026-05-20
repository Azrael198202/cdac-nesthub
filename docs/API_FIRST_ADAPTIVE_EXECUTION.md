# API-first adaptive execution

This version demotes page scraping to the last fallback.

Generic flow:

1. Ask the configured high-quality model route for structured API candidates.
2. Prefer free or no-credential API candidates.
3. Verify endpoint/response shape before generating executable code.
4. If an API requires a credential, surface the provider/source and the exact secret name in the UI.
5. If the user provides the key, persist it through `SecretStore` and resume.
6. If the user skips the key or the API path fails, continue to web evidence.
7. Web evidence may use browser/network observation and DOM/table fallback, but it cannot override the API-first result contract.

The implementation remains domain-neutral. It does not embed task-specific provider names or business keywords in core runtime logic.
