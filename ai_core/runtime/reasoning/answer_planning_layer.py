from __future__ import annotations

from typing import Any


class AnswerPlanningLayer:
    """Build a final-answer plan from verified facts only.

    The planner is not a search engine and does not use raw excerpts as the
    answer.  It emits a small, auditable plan that final synthesis can render.
    """

    def plan(self, *, user_input: str, resolved_claims: dict[str, Any], language: str = "auto") -> dict[str, Any]:
        facts = resolved_claims.get("facts") if isinstance(resolved_claims, dict) else []
        facts = [f for f in facts if isinstance(f, dict)]
        source_urls = []
        for item in facts:
            url = str(item.get("source_url") or "")
            if url.startswith(("http://", "https://")) and url not in source_urls:
                source_urls.append(url)
        for url in resolved_claims.get("source_urls", []) if isinstance(resolved_claims, dict) else []:
            url = str(url or "")
            if url.startswith(("http://", "https://")) and url not in source_urls:
                source_urls.append(url)

        comparable = [f for f in facts if f.get("kind") == "resolved_comparable_identifier"]
        measurements = [f for f in facts if f.get("kind") == "resolved_measurement"]
        statements = [f for f in facts if f.get("kind") == "source_supported_statement"]

        if comparable:
            focus = comparable[0]
            bullets = []
            supporting = str(focus.get("supporting_text") or "").strip()
            if supporting:
                bullets.append(self._clean(supporting))
            for statement in statements[:3]:
                text = self._clean(str(statement.get("value") or ""))
                if text and text not in bullets:
                    bullets.append(text)
            return {
                "answer_type": "resolved_identifier_summary",
                "status": "ready",
                "primary_fact": focus,
                "bullets": bullets[:4],
                "source_urls": source_urls[:5],
                "constraints": ["use_verified_facts_only", "do_not_dump_raw_source_fields"],
            }

        if measurements:
            return {
                "answer_type": "structured_measurement_summary",
                "status": "ready",
                "primary_fact": measurements[0],
                "measurements": measurements[:6],
                "source_urls": source_urls[:5],
                "constraints": ["use_verified_facts_only", "do_not_dump_raw_source_fields"],
            }

        if statements:
            return {
                "answer_type": "supported_statement_summary",
                "status": "ready",
                "bullets": [self._clean(str(s.get("value") or "")) for s in statements[:4] if str(s.get("value") or "").strip()],
                "source_urls": source_urls[:5],
                "constraints": ["use_verified_facts_only", "do_not_dump_raw_source_fields"],
            }

        return {
            "answer_type": "insufficient_structured_evidence",
            "status": "insufficient",
            "reason": "No verified facts could be resolved from the selected relevant sources.",
            "source_urls": source_urls[:5],
            "constraints": ["do_not_dump_raw_source_fields"],
        }

    def render(self, plan: dict[str, Any]) -> str:
        kind = str(plan.get("answer_type") or "")
        sources = [str(u) for u in plan.get("source_urls", []) if str(u).startswith(("http://", "https://"))]
        lines: list[str] = []
        if kind == "resolved_identifier_summary":
            fact = plan.get("primary_fact") if isinstance(plan.get("primary_fact"), dict) else {}
            value = str(fact.get("value") or "").strip()
            status = str(fact.get("status") or "").strip()
            if value:
                suffix = f" ({status})" if status and status != "unspecified" else ""
                lines.append(f"Verified latest supported value: {value}{suffix}.")
            for bullet in plan.get("bullets", [])[:4]:
                text = self._clean(str(bullet or ""))
                if text and text not in lines:
                    lines.append(f"- {text}")
        elif kind == "structured_measurement_summary":
            lines.append("Verified current structured information:")
            for m in plan.get("measurements", [])[:6]:
                if not isinstance(m, dict):
                    continue
                label = self._friendly_label(str(m.get("label") or "value"))
                value = str(m.get("value") or "").strip()
                unit = str(m.get("unit") or "").strip()
                if value:
                    lines.append(f"- {label}: {value}{unit}")
        elif kind == "supported_statement_summary":
            lines.append("Summary from verified source-supported statements:")
            for bullet in plan.get("bullets", [])[:4]:
                text = self._clean(str(bullet or ""))
                if text:
                    lines.append(f"- {text}")
        else:
            lines.append("I found relevant sources, but could not extract enough structured, verified facts to answer confidently.")

        if sources:
            lines.append("Sources:")
            lines.extend(f"- {url}" for url in sources[:5])
        return "\n".join(line for line in lines if line).strip()

    def _friendly_label(self, label: str) -> str:
        clean = " ".join(str(label or "value").replace("_", " ").split())
        return clean[:1].upper() + clean[1:] if clean else "Value"

    def _clean(self, text: str) -> str:
        return " ".join(str(text or "").split()).strip()[:520]
