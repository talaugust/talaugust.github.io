#!/usr/bin/env python3
"""extract_preview — generate preview PNGs from the first page of source PDFs.

For each filename listed in `missing_pngs`, looks for a matching PDF in
assets/pdf/ (same stem), renders its first page at 200 DPI, and writes the
PNG to assets/img/publication_preview/.

Requires PyMuPDF (install with: pip install pymupdf).
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    print("error: PyMuPDF not installed. Install with: pip install pymupdf", file=sys.stderr)
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parent
MISSING_PNGS = REPO_ROOT / "missing_pngs"
PDF_DIR = REPO_ROOT / "assets" / "pdf"
PREVIEW_DIR = REPO_ROOT / "assets" / "img" / "publication_preview"
DPI = 200


def main() -> int:
    if not MISSING_PNGS.is_file():
        print(f"error: {MISSING_PNGS} not found. Run check_papers first.", file=sys.stderr)
        return 2

    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

    pngs = [line.strip() for line in MISSING_PNGS.read_text().splitlines() if line.strip()]

    extracted: list[str] = []
    no_source: list[str] = []
    errors: list[tuple[str, str]] = []

    for png_name in pngs:
        stem = Path(png_name).stem
        pdf_path = PDF_DIR / f"{stem}.pdf"
        out_path = PREVIEW_DIR / png_name

        if not pdf_path.is_file():
            no_source.append(png_name)
            print(f"  skip   {png_name} (no {pdf_path.name})")
            continue

        try:
            with fitz.open(pdf_path) as doc:
                if doc.page_count == 0:
                    errors.append((png_name, "empty pdf"))
                    continue
                pix = doc[0].get_pixmap(dpi=DPI)
                pix.save(out_path)
            extracted.append(png_name)
            print(f"  wrote  {png_name}")
        except Exception as e:
            errors.append((png_name, str(e)))
            print(f"  error  {png_name}: {e}", file=sys.stderr)

    print(f"\nExtracted: {len(extracted)} | no source PDF: {len(no_source)} | errors: {len(errors)}")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
