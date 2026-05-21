# v3.1.1 Conversation Core Runtime

Ordinary Agent Studio messages now enter a generic AI-core conversation pipeline instead of bypassing the runtime.

Stages:
1. input_parsing
2. intent_recognition
3. context_awareness
4. workflow_planning
5. execution
6. output

The result remains user-facing in the UI. Internal stage data is kept in the response payload and trace files for debugging, but the visible answer is not raw JSON.

The implementation is generic and does not add domain/task-specific logic.
