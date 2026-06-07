from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from perception_brain.contracts import ArtifactObservation
from perception_brain.processors.base import BasePerceptionProcessor


class DocumentPerceptionProcessor(BasePerceptionProcessor):
    modality = "document"

    def process(self, artifact: dict) -> ArtifactObservation:
        obs = self._base_observation(artifact, modality="document")
        path = self._path(artifact)
        if not path:
            obs.status = "unavailable"
            obs.warnings.append("artifact_file_not_found")
            return obs
        suffix = path.suffix.lower()
        try:
            if suffix in {".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".xml"}:
                text = self._read_text_like(path)
            elif suffix == ".docx":
                text = self._read_docx(path)
            elif suffix == ".xlsx":
                text = self._read_xlsx(path)
            elif suffix == ".pdf":
                text = self._read_pdf(path)
            else:
                text = self._read_text_like(path)
            obs.extracted_text = self._clip(text)
            obs.metadata["text_length"] = len(text or "")
            if obs.extracted_text.strip():
                summary, warnings = self._summarize_text(text=obs.extracted_text, modality="document", context={"artifact_id": obs.artifact_id, "filename": obs.name})
                obs.summary = summary
                obs.warnings.extend(warnings)
            else:
                obs.warnings.append("no_text_extracted")
            obs.status = "normalized"
        except Exception as exc:
            obs.status = "failed"
            obs.warnings.append(f"document_processing_failed:{exc.__class__.__name__}:{exc}")
        return obs

    def _read_text_like(self, path: Path) -> str:
        raw = path.read_bytes()
        for enc in ("utf-8", "utf-8-sig", "cp932", "latin-1"):
            try:
                return raw.decode(enc)
            except Exception:
                continue
        return raw.decode("utf-8", errors="replace")

    def _read_docx(self, path: Path) -> str:
        with zipfile.ZipFile(path) as zf:
            names = [name for name in zf.namelist() if name.startswith("word/") and name.endswith(".xml")]
            chunks: list[str] = []
            for name in names:
                if name != "word/document.xml" and not name.startswith("word/header") and not name.startswith("word/footer"):
                    continue
                xml = zf.read(name)
                root = ET.fromstring(xml)
                for elem in root.iter():
                    if elem.tag.endswith("}t") and elem.text:
                        chunks.append(elem.text)
                    elif elem.tag.endswith("}tab"):
                        chunks.append("\t")
                    elif elem.tag.endswith("}br") or elem.tag.endswith("}p"):
                        chunks.append("\n")
            return re.sub(r"\n{3,}", "\n\n", "".join(chunks)).strip()

    def _read_xlsx(self, path: Path) -> str:
        with zipfile.ZipFile(path) as zf:
            shared: list[str] = []
            if "xl/sharedStrings.xml" in zf.namelist():
                root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                for si in root.iter():
                    if si.tag.endswith("}t") and si.text:
                        shared.append(si.text)
            sheet_names = [n for n in zf.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")]
            rows_out: list[str] = []
            for sheet in sheet_names[:5]:
                root = ET.fromstring(zf.read(sheet))
                rows_out.append(f"[{Path(sheet).stem}]")
                row_count = 0
                for row in root.iter():
                    if not row.tag.endswith("}row"):
                        continue
                    cells: list[str] = []
                    for cell in row:
                        if not cell.tag.endswith("}c"):
                            continue
                        cell_type = cell.attrib.get("t")
                        value = ""
                        for v in cell:
                            if v.tag.endswith("}v") and v.text is not None:
                                value = v.text
                                break
                        if cell_type == "s":
                            try:
                                value = shared[int(value)]
                            except Exception:
                                pass
                        cells.append(value)
                    if any(cells):
                        rows_out.append("\t".join(cells))
                        row_count += 1
                    if row_count >= 40:
                        rows_out.append("...[sheet rows truncated]")
                        break
            return "\n".join(rows_out)

    def _read_pdf(self, path: Path) -> str:
        try:
            import fitz  # type: ignore
            doc = fitz.open(str(path))
            return "\n\n".join(page.get_text() for page in doc[:30])
        except Exception:
            pass
        try:
            from pypdf import PdfReader  # type: ignore
            reader = PdfReader(str(path))
            return "\n\n".join((page.extract_text() or "") for page in reader.pages[:30])
        except Exception:
            pass
        try:
            from PyPDF2 import PdfReader  # type: ignore
            reader = PdfReader(str(path))
            return "\n\n".join((page.extract_text() or "") for page in reader.pages[:30])
        except Exception as exc:
            raise RuntimeError(f"pdf_text_extraction_unavailable:{exc}") from exc
