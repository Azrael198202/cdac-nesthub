from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

import httpx

from ai_core.config.paths import RUNTIME_DOWNLOADS, RUNTIME_GENERATED, RUNTIME_TRACES
from ai_core.events.event_bus import event_bus
from ai_core.research.web_research_tool import GenericWebResearchTool
from ai_core.research.model_candidate_evaluator import ModelCandidateEvaluator
from ai_core.research.repository_analyzer import GitHubRepositoryAnalyzer
from ai_core.utils.safe_json import safe_json_dumps


@dataclass
class CandidateRiskAssessment:
    risk_level: str
    reasons: list[str]
    requires_human_review: bool
    safe_to_execute_directly: bool


class ExternalSolutionDiscoveryEngine:
    """Generic external capability discovery for runtime self-extension.

    This engine is domain-neutral infrastructure. It does not know or encode any
    business/task-specific solution. It gathers external evidence from generic
    web pages, public source repositories, and model catalog endpoints so the
    runtime intelligence layer can generate a capability-specific workflow,
    tool, module, or model-route proposal.

    External artifacts are treated as untrusted evidence. This class never
    executes downloaded code and never silently installs a model/tool.
    """

    def __init__(self) -> None:
        self.web = GenericWebResearchTool()
        self.request_dir = RUNTIME_GENERATED / "external_discovery_requests"
        self.trace_dir = RUNTIME_TRACES / "external_solution_discovery"
        self.download_dir = RUNTIME_DOWNLOADS / "external_candidates"
        self.request_dir.mkdir(parents=True, exist_ok=True)
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.repository_analyzer = GitHubRepositoryAnalyzer()
        self.model_evaluator = ModelCandidateEvaluator()

    async def discover(
        self,
        *,
        run_id: str,
        node_id: str,
        capability: str,
        step: dict[str, Any],
        user_input: str,
    ) -> dict[str, Any]:
        request = self._build_request(capability=capability, step=step, user_input=user_input)
        request_path = self.request_dir / f"{request['request_id']}.json"
        request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")

        await event_bus.emit(run_id, {
            "type": "EXTERNAL_DISCOVERY_STARTED",
            "title": "External capability discovery started",
            "message": f"Discovering reusable external evidence for capability={capability}",
            "node_id": node_id,
            "result": {"request_id": request["request_id"], "request_path": str(request_path)},
        })

        web_results = await self._search_general_web(run_id=run_id, node_id=node_id, request=request)
        docs = await self._fetch_candidate_documents(run_id=run_id, node_id=node_id, candidates=web_results)
        repositories = await self._search_repositories(run_id=run_id, node_id=node_id, request=request)
        models = await self._search_model_catalogs(run_id=run_id, node_id=node_id, request=request)

        discovery = self._finalize(
            request=request,
            web_results=web_results,
            documents=docs,
            repositories=repositories,
            models=models,
        )

        await event_bus.emit(run_id, {
            "type": "EXTERNAL_DISCOVERY_DONE",
            "title": "External capability discovery completed",
            "message": f"status={discovery.get('status')}",
            "node_id": node_id,
            "result": {
                "status": discovery.get("status"),
                "trace_id": discovery.get("trace_id"),
                "trace_path": discovery.get("trace_path"),
                "web_result_count": len(web_results),
                "document_count": len(docs),
                "repository_count": len(repositories),
                "model_count": len(models),
                "safety_policy": discovery.get("safety_policy"),
            },
        })
        return discovery

    def _build_request(self, *, capability: str, step: dict[str, Any], user_input: str) -> dict[str, Any]:
        request_id = "external_discovery_" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        params = step.get("parameters") if isinstance(step.get("parameters"), dict) else {}
        return {
            "request_id": request_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "capability": capability,
            "user_input": user_input,
            "source_step": step,
            "runtime_request_semantics": {
                "objective": step.get("objective"),
                "action": step.get("action"),
                "task_type": step.get("task_type"),
                "known_parameters": params.get("known", params),
                "optional_parameters": params.get("optional", {}),
                "runtime_modifiers": step.get("modifiers") or params.get("modifiers") or [],
                "runtime_constraints": step.get("constraints") or params.get("constraints") or {},
                "output_preferences": step.get("output_preferences") or params.get("output_preferences") or {},
            },
            "discovery_goals": [
                "find_existing_tools_or_code_examples",
                "find_relevant_documentation_or_markdown_guides",
                "find_candidate_models_when_model_choice_can_improve_the_task",
                "collect_license_installation_usage_and_risk_evidence",
                "do_not_execute_untrusted_code",
            ],
        }

    def _queries(self, request: dict[str, Any]) -> list[str]:
        capability = str(request.get("capability") or "").strip()
        step = request.get("source_step") if isinstance(request.get("source_step"), dict) else {}
        objective = str(step.get("objective") or "").strip()
        action = str(step.get("action") or "").strip()
        user_input = str(request.get("user_input") or "").strip()
        base = " ".join(x for x in [capability, objective, action, user_input] if x) or "runtime capability"
        return [
            f"{base} documentation guide example implementation",
            f"{base} GitHub library tool README license usage",
            f"{base} model benchmark huggingface ollama recommended",
        ]

    async def _search_general_web(self, *, run_id: str, node_id: str, request: dict[str, Any]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for query in self._queries(request):
            try:
                response = await self.web.search(query=query, max_results=6)
                await event_bus.emit(run_id, {
                    "type": "EXTERNAL_WEB_SEARCH_DONE",
                    "title": "External web evidence collected",
                    "message": query,
                    "node_id": node_id,
                    "result": response,
                })
                if isinstance(response, dict):
                    for item in response.get("results", []) or []:
                        if isinstance(item, dict):
                            results.append(item)
            except Exception as exc:
                await event_bus.emit(run_id, {
                    "type": "EXTERNAL_WEB_SEARCH_FAILED",
                    "title": "External web search failed",
                    "message": str(exc),
                    "node_id": node_id,
                    "result": {"query": query},
                })
        return self._dedupe_by_url(results)[:12]

    async def _fetch_candidate_documents(self, *, run_id: str, node_id: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        documents: list[dict[str, Any]] = []
        for item in candidates[:8]:
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            try:
                doc = await self.web.fetch(url=url, max_chars=10000)
                if isinstance(doc, dict) and doc.get("status") == "success":
                    documents.append({"source_search_result": item, "document": doc, "assessment": self._assess_document(item, doc)})
            except Exception as exc:
                await event_bus.emit(run_id, {
                    "type": "EXTERNAL_DOCUMENT_FETCH_FAILED",
                    "title": "External document fetch failed",
                    "message": str(exc),
                    "node_id": node_id,
                    "result": {"url": url},
                })
        return documents

    async def _search_repositories(self, *, run_id: str, node_id: str, request: dict[str, Any]) -> list[dict[str, Any]]:
        query_base = " ".join(self._queries(request)[:1])
        api_url = "https://api.github.com/search/repositories?q=" + quote_plus(query_base) + "&sort=stars&order=desc&per_page=8"
        repositories: list[dict[str, Any]] = []
        try:
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers={"User-Agent": "AI-Core-Runtime/1.0"}) as client:
                response = await client.get(api_url)
                response.raise_for_status()
                payload = response.json()
            for repo in payload.get("items", []) or []:
                if not isinstance(repo, dict):
                    continue
                record = {
                    "name": repo.get("full_name"),
                    "url": repo.get("html_url"),
                    "description": repo.get("description"),
                    "stars": repo.get("stargazers_count"),
                    "forks": repo.get("forks_count"),
                    "language": repo.get("language"),
                    "license": (repo.get("license") or {}).get("spdx_id") if isinstance(repo.get("license"), dict) else None,
                    "updated_at": repo.get("updated_at"),
                    "default_branch": repo.get("default_branch"),
                    "archived": repo.get("archived"),
                    "risk_assessment": asdict(self._assess_repository(repo)),
                }
                if record.get("url") and not record.get("archived"):
                    record["repository_analysis"] = self.repository_analyzer.analyze(
                        str(record["url"]),
                        request_id=str(request.get("request_id") or "external_discovery"),
                    )
                repositories.append(record)
            await event_bus.emit(run_id, {
                "type": "GITHUB_REPOSITORY_SEARCH_DONE",
                "title": "Repository candidates collected",
                "message": f"{len(repositories)} candidate(s)",
                "node_id": node_id,
                "result": {"api_url": api_url, "repositories": repositories},
            })
        except Exception as exc:
            await event_bus.emit(run_id, {
                "type": "GITHUB_REPOSITORY_SEARCH_FAILED",
                "title": "Repository search failed",
                "message": str(exc),
                "node_id": node_id,
                "result": {"api_url": api_url},
            })
        return repositories

    async def _search_model_catalogs(self, *, run_id: str, node_id: str, request: dict[str, Any]) -> list[dict[str, Any]]:
        query = str(request.get("capability") or "") or str(request.get("user_input") or "runtime task")
        hf_url = "https://huggingface.co/api/models?search=" + quote_plus(query) + "&limit=8"
        models: list[dict[str, Any]] = []
        try:
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers={"User-Agent": "AI-Core-Runtime/1.0"}) as client:
                response = await client.get(hf_url)
                response.raise_for_status()
                payload = response.json()
            if isinstance(payload, list):
                for model in payload:
                    if not isinstance(model, dict):
                        continue
                    record = {
                        "source": "huggingface",
                        "model_id": model.get("modelId") or model.get("id"),
                        "downloads": model.get("downloads"),
                        "likes": model.get("likes"),
                        "pipeline_tag": model.get("pipeline_tag"),
                        "tags": model.get("tags", [])[:20] if isinstance(model.get("tags"), list) else [],
                        "last_modified": model.get("lastModified"),
                        "url": "https://huggingface.co/" + str(model.get("modelId") or model.get("id") or ""),
                        "risk_assessment": asdict(CandidateRiskAssessment(
                            risk_level="review_required",
                            reasons=["model weights and license must be reviewed before download or execution"],
                            requires_human_review=True,
                            safe_to_execute_directly=False,
                        )),
                    }
                    record["model_evaluation"] = self.model_evaluator.evaluate(record, task_context=request)
                    models.append(record)
            await event_bus.emit(run_id, {
                "type": "MODEL_CATALOG_SEARCH_DONE",
                "title": "Model candidates collected",
                "message": f"{len(models)} candidate(s)",
                "node_id": node_id,
                "result": {"catalog_url": hf_url, "models": models},
            })
        except Exception as exc:
            await event_bus.emit(run_id, {
                "type": "MODEL_CATALOG_SEARCH_FAILED",
                "title": "Model catalog search failed",
                "message": str(exc),
                "node_id": node_id,
                "result": {"catalog_url": hf_url},
            })
        return models

    def _assess_repository(self, repo: dict[str, Any]) -> CandidateRiskAssessment:
        reasons: list[str] = []
        if repo.get("archived"):
            reasons.append("repository is archived")
        if not repo.get("license"):
            reasons.append("license metadata is missing")
        if int(repo.get("stargazers_count") or 0) < 25:
            reasons.append("low public usage signal")
        if not repo.get("html_url"):
            reasons.append("repository URL is missing")
        if not reasons:
            reasons.append("still requires sandbox verification before use")
        risk_level = "medium" if len(reasons) <= 1 else "high"
        return CandidateRiskAssessment(
            risk_level=risk_level,
            reasons=reasons,
            requires_human_review=True,
            safe_to_execute_directly=False,
        )

    def _assess_document(self, item: dict[str, Any], doc: dict[str, Any]) -> dict[str, Any]:
        text = str(doc.get("text_excerpt") or "").lower()
        signals = []
        for token in ["install", "usage", "license", "api", "example", "parameters", "authentication", "readme"]:
            if token in text:
                signals.append(token)
        return {
            "evidence_signals": signals,
            "risk_assessment": asdict(CandidateRiskAssessment(
                risk_level="review_required",
                reasons=["external document is evidence only and must be validated before code generation"],
                requires_human_review=False,
                safe_to_execute_directly=False,
            )),
            "source_url": item.get("url") or doc.get("url"),
        }

    def _finalize(
        self,
        *,
        request: dict[str, Any],
        web_results: list[dict[str, Any]],
        documents: list[dict[str, Any]],
        repositories: list[dict[str, Any]],
        models: list[dict[str, Any]],
    ) -> dict[str, Any]:
        trace_id = "external_discovery_" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        trace_path = self.trace_dir / f"{trace_id}.json"
        status = "success" if any([web_results, documents, repositories, models]) else "no_external_evidence"
        record = {
            "status": status,
            "request": request,
            "web_results": web_results,
            "documents": documents,
            "repositories": repositories,
            "models": models,
            "safety_policy": {
                "external_code_is_untrusted": True,
                "direct_execution_allowed": False,
                "must_verify_in_sandbox_before_registration": True,
                "must_preserve_license_and_source_provenance": True,
                "model_download_requires_explicit_policy_or_human_approval": True,
                "repository_clone_is_evidence_only": True,
                "dependency_scan_required_before_install": True,
                "sandbox_execution_required_before_registry": True,
            },
            "trace_id": trace_id,
            "trace_path": str(trace_path),
        }
        trace_path.write_text(safe_json_dumps(record, indent=2), encoding="utf-8")
        return record

    def _dedupe_by_url(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        output: list[dict[str, Any]] = []
        for item in items:
            url = str(item.get("url") or "").strip()
            key = url or json.dumps(item, ensure_ascii=False, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            output.append(item)
        return output
