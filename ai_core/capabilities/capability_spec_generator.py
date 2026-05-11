import re


class CapabilitySpecGenerator:
    def generate(self, capability_id: str, node_id: str, task_context: dict) -> dict:
        safe_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", capability_id).lower()
        return {
            "capability_id": safe_id,
            "type": "unknown",
            "description": f"Generated placeholder capability for node '{node_id}'. Human or external model should refine this spec.",
            "detect": {"binary": [], "paths": {"windows": [], "linux": [], "darwin": [], "all": []}, "env_keys": []},
            "install": {"windows": [], "linux": [], "darwin": [], "all": []},
            "start": {"mode": "none", "commands": {"windows": [], "linux": [], "darwin": [], "all": []}},
            "verify": {"commands": {"windows": [], "linux": [], "darwin": [], "all": []}, "health_urls": [], "ports": [], "paths": {"windows": [], "linux": [], "darwin": [], "all": []}, "env_keys": []},
            "runtime_register": {"provider_name": "", "tool_name": safe_id, "env_keys": []},
            "security": {"approval_required": True, "risk_level": "unknown"},
        }
