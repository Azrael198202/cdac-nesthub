from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str


class SettingsRequest(BaseModel):
    provider: str = "auto"
    openai_api_key: str | None = None
    openai_model: str | None = None
    ollama_model: str | None = None
    ollama_base_url: str | None = None
