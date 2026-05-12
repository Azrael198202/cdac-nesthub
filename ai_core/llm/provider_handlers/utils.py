import json
import re


def build_system_prompt(prompt: dict, schema: dict) -> str:
    return (
        str(prompt.get("system", "")) +
        "\n\nReturn exactly one valid JSON object. No markdown. No explanation." +
        "\nJSON Schema:\n" +
        json.dumps(schema, ensure_ascii=False, indent=2)
    )


def parse_json_content(content: str) -> dict:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?", "", content).strip()
        content = re.sub(r"```$", "", content).strip()
    return json.loads(content)
