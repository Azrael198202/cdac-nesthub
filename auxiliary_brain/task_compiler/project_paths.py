from __future__ import annotations

from pathlib import Path
import os


_DEFAULT_PROMPT_PROFILES: dict[str, str] = {
    "source_retrieval": """You are executing a compiled source retrieval step. Use only the locked execution contract, source contract, and provided inputs. Retrieve source material in the declared order. Do not claim relevance unless concrete material was extracted. Return structured evidence and presentation-ready output.""",
    "document_composition": """You are executing a compiled document composition step. Use only provided task context, resolved bindings, and verified step inputs. Do not invent facts. Produce the requested document output according to the presentation contract.""",
    "capability_acquisition": """You are executing a compiled capability acquisition step. Follow the capability contract, validation requirements, sandbox policy, and registration policy. Do not hard-code runtime values or secrets. Return implementation status and verification evidence.""",
    "capability_execution": """You are executing a compiled capability execution step. Follow the locked execution contract and input bindings. Do not re-plan, re-select tools, or guess prompts at runtime. Return structured result, verification material, and presentation fields.""",
    "workflow_compile": """You are executing a compiled workflow compilation step. Transform the supplied task graph into stable step contracts, bindings, execution plan, validation report, and exportable presentation metadata. Do not use runtime template parsing.""",
    "verification": """You are executing a compiled verification step. Check whether the step result satisfies the declared contract using available evidence. Report pass, warnings, errors, and repair recommendations without inventing missing evidence.""",
    "presentation": """You are executing a compiled presentation step. Convert verified results into user-facing presentation output and exportable outputs. Do not include failure messages in exportable outputs.""",
    "json_planning": """You are executing a compiled JSON planning step. Return strict JSON that conforms to the declared schema and uses only the provided input, context, and contracts.""",
}


def project_root() -> Path:
    """Return repository root without depending on process working directory.

    Resolution order:
    1. explicit environment override
    2. parents of this source file
    3. current working directory and its parents
    4. conservative source-relative fallback
    """
    for key in ("AI_OS_PROJECT_ROOT", "CDAC_NESTHUB_PROJECT_ROOT", "PROJECT_ROOT"):
        value = os.environ.get(key)
        if value:
            path = Path(value).expanduser().resolve()
            if path.exists():
                return path
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "ai_core").is_dir() and (parent / "auxiliary_brain").is_dir():
            return parent
    cwd = Path.cwd().resolve()
    for parent in (cwd, *cwd.parents):
        if (parent / "ai_core").is_dir() and (parent / "auxiliary_brain").is_dir():
            return parent
    return current.parents[2]


def runtime_dir() -> Path:
    return project_root() / "runtime"


def prompt_profile_dir() -> Path:
    return runtime_dir() / "prompt_profiles"


def generated_tasks_dir() -> Path:
    return runtime_dir() / "generated" / "tasks"


def tool_registry_path() -> Path:
    return runtime_dir() / "registry" / "tool_registry.json"


def ensure_prompt_profiles(base: Path | None = None) -> Path:
    """Ensure built-in generic prompt profiles exist before compile validation.

    Prompt content is generic and domain-neutral. This keeps task execution locked
    to creation-time prompt profile ids without failing when a runtime data
    directory has not been bootstrapped yet.
    """
    profile_dir = base or prompt_profile_dir()
    profile_dir.mkdir(parents=True, exist_ok=True)
    for profile_id, content in _DEFAULT_PROMPT_PROFILES.items():
        path = profile_dir / f"{profile_id}.prompt"
        if not path.exists() or not path.read_text(encoding="utf-8", errors="ignore").strip():
            path.write_text(content.strip() + "\n", encoding="utf-8")
    return profile_dir
