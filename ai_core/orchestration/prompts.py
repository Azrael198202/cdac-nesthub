from __future__ import annotations


def prompt_for_step(step: str, user_text: str, context: dict | None = None) -> str:
    context = context or {}
    if step == "input_parsing":
        return f"Normalize and parse the user input. Return JSON. User input: {user_text}"
    if step == "intent_recognition":
        return f"Intent Recognition. Classify this request and return JSON with intent_type, confidence, tasks, requires_tools, requires_human_approval. User input: {user_text}"
    if step == "context_awareness":
        return f"Context Awareness. Use memory and knowledge to enrich context. User input: {user_text}. Context: {context}"
    if step == "workflow_planning":
        return f"Workflow Planning. Return JSON workflow with nodes for the request. User input: {user_text}. Context: {context}"
    if step == "feedback_learning":
        return f"Feedback Learning. Summarize learning data. User input: {user_text}. Context: {context}"
    return user_text
