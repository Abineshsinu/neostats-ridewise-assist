"""
Builds a version-aware, section-level keyword index over the policy PDFs
(plus the transcribed annexures) and answers search queries with BM25. No
embeddings, no vector DB — the hosted LLM has no embeddings endpoint
(confirmed in Phase 0) and five short documents don't need semantic search.

Ingestion is generic: every *.pdf in data/raw is parsed for its own header
metadata (doc id, title, version, effective date, scope) and chunked by
numbered section, so a new policy version can be added by dropping a PDF
into data/raw and re-running build_index() — no code changes beyond the
rules config for any new numeric rule values.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pdfplumber
from rank_bm25 import BM25Okapi

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
DERIVED_DIR = Path(__file__).resolve().parent.parent / "data" / "derived"

HEADER_RE = re.compile(r"(RW-POL-\d+)\s*[·\-]\s*v?([\d.]+)", re.IGNORECASE)
DOC_LINE_RE = re.compile(r"Document\s+(RW-POL-\d+)\s*[·\-]\s*Version\s+([\d.]+)\s*[·\-]?\s*(.*)")
# A real section header always has a literal "." right after the leading
# number (either "N." for a top-level heading or "N.M" for a sub-section).
# Table rows like "24 hours or more 100%" have no such period and must not
# be mistaken for a new section — that would fragment tables away from
# their heading.
SECTION_RE = re.compile(r"^(\d+\.\d+)\s+(.+)$")
TOP_LEVEL_SECTION_RE = re.compile(r"^(\d+)\.\s+([A-Z].+)$")


@dataclass
class PolicyChunk:
    doc_id: str
    title: str
    version: str
    scope: str
    section: str
    text: str
    source_file: str
    page: int


def _parse_pdf(path: Path) -> list[PolicyChunk]:
    chunks: list[PolicyChunk] = []
    with pdfplumber.open(path) as pdf:
        full_text_lines: list[tuple[int, str]] = []
        for pno, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            for line in text.split("\n"):
                full_text_lines.append((pno, line))

    doc_id, version, title, scope = "UNKNOWN", "", path.stem, ""
    for _, line in full_text_lines[:3]:
        m = HEADER_RE.search(line)
        if m:
            doc_id = m.group(1).upper()
            version = m.group(2)
            break
    for _, line in full_text_lines[:6]:
        m = DOC_LINE_RE.search(line)
        if m:
            doc_id = m.group(1).upper()
            version = m.group(2)
            if m.group(3):
                scope = m.group(3).strip()
    for _, line in full_text_lines[:6]:
        if line.strip() and not line.startswith("RW-POL") and not line.startswith("Document"):
            title = line.strip()
            break

    # Pick up an explicit "Scope." paragraph if present (more precise than the header line).
    for i, (_, line) in enumerate(full_text_lines):
        if line.strip().startswith("Scope."):
            scope = line.strip()
            break

    current_section = "0"
    current_page = 1
    buffer: list[str] = []

    def flush():
        if buffer:
            text = " ".join(buffer).strip()
            if text:
                chunks.append(PolicyChunk(doc_id, title, version, scope, current_section, text, path.name, current_page))

    for pno, line in full_text_lines:
        stripped = line.strip()
        if not stripped:
            continue
        m = SECTION_RE.match(stripped) or TOP_LEVEL_SECTION_RE.match(stripped)
        if m:
            flush()
            buffer = [stripped]
            current_section = m.group(1)
            current_page = pno
        else:
            buffer.append(stripped)
    flush()

    return chunks


def _parse_annexures_md() -> list[PolicyChunk]:
    """The derived annexure transcription is itself searchable policy content."""
    path = DERIVED_DIR / "policy_annexures.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    sections = re.split(r"\n## ", text)
    chunks = []
    for sec in sections:
        sec = sec.strip()
        if not sec or sec.startswith("# "):
            continue
        heading = sec.split("\n", 1)[0]
        body = sec
        doc_id_match = re.search(r"RW-POL-\d+", body)
        doc_id = doc_id_match.group(0) if doc_id_match else "ANNEXURE"
        chunks.append(PolicyChunk(
            doc_id=doc_id,
            title=f"Annexure: {heading}",
            version="",
            scope="transcribed from scanned image, see data/derived/policy_annexures.md",
            section=heading,
            text=body,
            source_file="policy_annexures.md",
            page=0,
        ))
    return chunks


def build_index() -> tuple[list[PolicyChunk], BM25Okapi]:
    chunks: list[PolicyChunk] = []
    for pdf_path in sorted(RAW_DIR.glob("*.pdf")):
        chunks.extend(_parse_pdf(pdf_path))
    chunks.extend(_parse_annexures_md())

    tokenized = [_tokenize(c.text) for c in chunks]
    bm25 = BM25Okapi(tokenized)
    return chunks, bm25


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


class PolicySearch:
    def __init__(self) -> None:
        self.chunks, self.bm25 = build_index()

    def search(self, query: str, top_k: int = 5) -> list[tuple[PolicyChunk, float]]:
        tokens = _tokenize(query)
        scores = self.bm25.get_scores(tokens)
        ranked = sorted(zip(self.chunks, scores), key=lambda x: x[1], reverse=True)
        return [(c, s) for c, s in ranked[:top_k] if s > 0]

    def search_for_version(self, query: str, applicable_doc_id: str | None, top_k: int = 5) -> list[tuple[PolicyChunk, float]]:
        """Version-aware search: if a specific booking's applicable doc_id is
        known (e.g. RW-POL-02 for v1, RW-POL-03 for v2), rank its chunks
        first; otherwise return chunks from both versions so the caller can
        present both with their scope."""
        results = self.search(query, top_k=top_k * 2)
        if applicable_doc_id:
            preferred = [r for r in results if r[0].doc_id == applicable_doc_id]
            other = [r for r in results if r[0].doc_id != applicable_doc_id]
            return (preferred + other)[:top_k]
        return results[:top_k]
