"""Extract embedded images from the annexure pages for visual transcription."""
from __future__ import annotations

from pathlib import Path

import pdfplumber

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
OUT = Path(__file__).resolve().parent.parent / "data" / "derived" / "_extracted_images"
OUT.mkdir(parents=True, exist_ok=True)

TARGETS = {
    "03_Cancellation_and_Refund_Policy_v2.pdf": [2],
    "04_Late_Return_and_Damage_Penalty_Schedule.pdf": [3],
    "05_EV_User_Guide_and_FAQ.pdf": [2],
}

for fname, pages in TARGETS.items():
    path = RAW / fname
    stem = path.stem
    with pdfplumber.open(path) as pdf:
        for pno in pages:
            page = pdf.pages[pno - 1]
            # Render the whole page at high resolution as a fallback/context image
            im = page.to_image(resolution=250)
            out_path = OUT / f"{stem}_p{pno}_full.png"
            im.save(str(out_path))
            print(f"saved {out_path}")

            # Also try to crop individual embedded images
            for idx, img in enumerate(page.images, start=1):
                try:
                    x0, top, x1, bottom = img["x0"], img["top"], img["x1"], img["bottom"]
                    cropped = page.crop((x0, top, x1, bottom))
                    cim = cropped.to_image(resolution=250)
                    cpath = OUT / f"{stem}_p{pno}_img{idx}.png"
                    cim.save(str(cpath))
                    print(f"saved {cpath}")
                except Exception as e:
                    print(f"could not crop image {idx} on {fname} p{pno}: {e}")
