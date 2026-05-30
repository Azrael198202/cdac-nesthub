# Basic SMTP Mail Sender Verification

Fix target: runtime autonomous acquisition for `Basic SMTP mail sender`.

Verified locally after patch:

1. Capability artifact generation: passed
   - Generated tool id: `basic_smtp_mail_sender`
   - Not the previous generic `connected_message_delivery_adapter`

2. Capability match contract: passed
   - Required markers found: `smtplib`, `EmailMessage`, `SMTP_SSL`, `send_message`, `smtp_host`, `smtp_port`, `password`, `mock_smtp_verification`
   - Forbidden marker absent: `connected_message_delivery_adapter`

3. Sandbox validation: passed
   - Python compile: passed
   - Unit test: passed
   - Unit test includes both mock SMTP verification and a real local SMTP protocol send using a sandbox socket server.

4. Verification run: passed
   - Verification input uses `transport_mode=mock`
   - Output status: `success`
   - Confirms `smtplib` and `email.message.EmailMessage`

5. Registry update: passed
   - Tool registry status: `enabled`
   - Module registry status: `enabled`

6. Full conversation runtime check: passed
   - Final status: `completed`
   - Final answer correctly reports implemented, sandbox-tested, registered, and verified.

Important fix:
- The previous failure was caused by child Python validation being polluted by IDE/debugger bootstrap (`debugpy`/`pydevd`) and then reported as `blocked_without_verified_evidence`.
- Validation subprocesses now use isolated Python execution with base-interpreter candidates and clean environment.
- The final execution status no longer depends only on web source count when a policy-backed basic runtime capability is successfully generated, tested, verified, and registered.
