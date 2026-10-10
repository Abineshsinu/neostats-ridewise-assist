"""Dump full text of a PDF, page by page, for citation lookup. Read-only, not part of the app."""
from __future__ import annotations

import sys
from pathlib import Path

import pdfplumber

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"


def dump(fname: str) -> None:
    path = RAW / fname
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            print(f"\n===== {fname} — page {i} =====")
            print(page.extract_text() or "(no extractable text)")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    for f in sys.argv[1:]:
        dump(f)
