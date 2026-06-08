from ai_core.model_orchestration.litellm_brain_client import LiteLLMBrainClient
from auxiliary_brain.capability_acquisition.code_generator import RuntimeBlueprintArtifactGenerator


class ProbeClient(LiteLLMBrainClient):
    def __init__(self, names):
        super().__init__()
        self.names = list(names)
        self.pulled = []

    def _ollama_binary(self):
        return "ollama"

    def _ollama_list(self, binary):
        return list(self.names)

    def _ollama_pull(self, binary, model):
        self.pulled.append(model)
        if self._is_ollama_model_pullable(model):
            self.names.append(model)
            return True
        return False


def test_exact_imported_model_is_used_without_pull():
    client = ProbeClient(["qwen3.5:4b-q4_k_m"])
    assert client._ensure_ollama_model("qwen3.5:4b-q4_k_m") == "qwen3.5:4b-q4_k_m"
    assert client.pulled == []


def test_custom_missing_model_is_not_blindly_pulled():
    client = ProbeClient(["qwen3:4b"])
    resolved = client._ensure_ollama_model("qwen3.5:4b-q4_k_m")
    assert resolved == "qwen3:4b"
    assert "qwen3.5:4b-q4_k_m" not in client.pulled


def test_pullable_code_model_can_be_prepared():
    client = ProbeClient([])
    resolved = client._ensure_ollama_model("qwen2.5-coder:7b")
    assert resolved == "qwen2.5-coder:7b"
    assert "qwen2.5-coder:7b" in client.pulled


def test_basic_generation_does_not_escalate_to_critical():
    generator = RuntimeBlueprintArtifactGenerator(llm_client=ProbeClient([]))
    complexities = [item["complexity"] for item in generator._generation_attempts("basic")]
    assert "critical" not in complexities
    assert complexities == ["basic", "basic", "basic"]


if __name__ == "__main__":
    test_exact_imported_model_is_used_without_pull()
    test_custom_missing_model_is_not_blindly_pulled()
    test_pullable_code_model_can_be_prepared()
    test_basic_generation_does_not_escalate_to_critical()
    print("v23.8 provider routing verification passed")
