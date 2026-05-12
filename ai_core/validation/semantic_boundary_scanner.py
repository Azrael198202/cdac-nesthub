from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class SemanticBoundaryFinding:
    path: str
    rule_id: str
    pattern: str
    line_number: int
    line_preview: str


class SemanticBoundaryScanner:
    """
    Generic semantic boundary scanner.

    This class contains no business/domain keywords.
    Rules must be supplied from runtime-generated policy/config.
    """

    def scan_path(
        self,
        *,
        target_path: Path,
        rules: list[dict[str, Any]],
        root_path: Path | None = None,
    ) -> list[SemanticBoundaryFinding]:
        root_path = root_path or target_path
        findings: list[SemanticBoundaryFinding] = []

        files = [target_path] if target_path.is_file() else list(target_path.rglob("*.py"))
        base = root_path.parent if root_path.is_file() else root_path

        for file_path in files:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
            try:
                rel = str(file_path.relative_to(base))
            except ValueError:
                rel = str(file_path)
            findings.extend(self.scan_text(text=text, rules=rules, path=rel))

        return findings

    def scan_text(
        self,
        *,
        text: str,
        rules: list[dict[str, Any]],
        path: str = "<memory>",
    ) -> list[SemanticBoundaryFinding]:
        findings: list[SemanticBoundaryFinding] = []

        for idx, line in enumerate(text.splitlines(), start=1):
            for rule in rules:
                if self._matches(line, rule):
                    findings.append(SemanticBoundaryFinding(
                        path=path,
                        rule_id=str(rule.get("id", "unnamed_rule")),
                        pattern=str(rule.get("pattern", "")),
                        line_number=idx,
                        line_preview=line.strip()[:240],
                    ))

        return findings

    def _matches(self, line: str, rule: dict[str, Any]) -> bool:
        pattern = rule.get("pattern")
        if not pattern:
            return False

        mode = rule.get("mode", "regex")
        ignore_case = bool(rule.get("ignore_case", True))

        if mode == "literal":
            return str(pattern).lower() in line.lower() if ignore_case else str(pattern) in line

        flags = re.IGNORECASE if ignore_case else 0
        return re.search(str(pattern), line, flags) is not None
