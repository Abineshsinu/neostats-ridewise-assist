"""Locate pages mentioning the annexures/figures we need to transcribe, and list embedded images per page."""
from __future__ import annotations

from pathlib import Path

import pdfplumber

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"

TARGETS = {
    "03_Cancellation_and_Refund_Policy_v2.pdf": ["Annexure 1", "annexure"],
    "04_Late_Return_and_Damage_Penalty_Schedule.pdf": ["Annexure A", "annexure", "grace"],
    "05_EV_User_Guide_and_FAQ.pdf": ["Figure 2", "figure", "battery"],
}

for fname, keywords in TARGETS.items():
    path = RAW / fname
    print(f"\n=== {fname} ===")
    with pdfplumber.open(path) as pdf:
        print(f"total pages: {len(pdf.pages)}")
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            hit = any(kw.lower() in text.lower() for kw in keywords)
            n_images = len(page.images)
            if hit or n_images > 0:
                print(f"  page {i}: keyword_hit={hit} images={n_images}")
                if hit:
                    snippet = text[:300].replace("\n", " ")
                    print(f"    text snippet: {snippet}")
