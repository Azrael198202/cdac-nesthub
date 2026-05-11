from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str


class ResumeRequest(BaseModel):
    run_id: str
    approved: bool = True
    comment: str | None = None


class SettingsRequest(BaseModel):
    provider: str = "auto"
    openai_api_key: str | None = None
    openai_model: str | None = None
    hf_token: str | None = None
    hf_model: str | None = None
    ollama_model: str | None = None
    ollama_base_url: str | None = None
