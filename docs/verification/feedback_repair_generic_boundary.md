# Feedback Repair Generic Boundary

Feedback repair is a generic failure-closure layer. It may classify errors by
structural signals, such as parameter, configuration, secret, external service,
validation, and implementation failures.

It must not contain capability-specific branches or fixed business terms. A
specific generated runtime tool may contain protocol or provider implementation
details, but the feedback-repair layer must only consume runtime contracts,
trace envelopes, schema validation results, and error metadata.

The verification script `tools/verify_feedback_repair_generic_boundary.py`
checks the feedback-repair source paths for disallowed capability-specific terms
and runs generic behavioral checks for:

- parameter failure proposal
- secret failure classification
- external service failure classification
- implementation failure patch request creation
- trace writing under `runtime/traces/feedback_repair/`
