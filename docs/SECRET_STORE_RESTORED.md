# SecretStore restored

`ai_core/secrets/secret_store.py` is source code and must be included in clean packages.

Clean packaging should exclude runtime secret **values** under `runtime/configs/secrets/`, but must not exclude the `ai_core/secrets` source package.

When a user enters a provider key from Agent Studio, the runtime persists it through `SecretStore` to `runtime/configs/secrets/secrets.json`, mirrors it to process memory, and sets `os.environ` for immediate reuse by later participants.
