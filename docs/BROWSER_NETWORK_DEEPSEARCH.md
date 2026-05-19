# Browser Network DeepSearch

This version adds a browser-observable web research path before DOM/text fallback.

## Flow

```text
web_search candidates
  ↓
Playwright browser observation
  ↓
Network request/response capture
  ↓
Structured JSON/API-like response extraction
  ↓
Evidence sufficiency gate
  ↓ insufficient
DOM / visible text fallback
  ↓ insufficient
API discovery / api_call escalation
```

## Design rules

- The browser layer is domain-neutral.
- It captures XHR/fetch/API-like responses, content type, status code, headers, and response body.
- Structured JSON responses are preferred over visible text.
- DOM text is only a fallback.
- Discovered browser endpoints are treated as runtime evidence, not automatically registered as permanent public APIs.
- Permanent tool registration still requires a stable provider contract, schema, and credential contract.

## Main modules

- `ai_core/runtime/browser/browser_network_observer.py`
- `ai_core/runtime/browser/structured_response_extractor.py`
- `ai_core/research/deep_web_research.py`
- `ai_core/runtime/evidence/evidence_reducer.py`

## Why this improves quality

HTML pages often mix navigation, coordinates, altitude, menus, ads, and data blocks. Browser network observation can discover the actual structured responses used by the page, reducing noisy extraction and improving final answer readability.
