#!/usr/bin/env python3
"""check_papers — validate papers.bib entries and their PDF/preview assets.

Enforces these conventions for each entry:
  bibkey  : first letter uppercase, and first letter after the year uppercase
            (e.g., august2020explain -> August2020Explain)
  pdf     = {<bibkey>.pdf}     -> a real file in assets/pdf/
  preview = {<bibkey>.png}     -> a real file in assets/img/publication_preview/

By default, mismatched bibkeys/fields are fixed in place in papers.bib. Use
--dry-run to preview without writing. The final report lists any pdf/preview
files that are still missing from the asset directories.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
BIB_PATH = REPO_ROOT / "_bibliography" / "papers.bib"
PDF_DIR = REPO_ROOT / "assets" / "pdf"
PREVIEW_DIR = REPO_ROOT / "assets" / "img" / "publication_preview"


def find_entries(text: str):
    """Yield (key, entry_start, entry_end) for each top-level @type{key,...} entry."""
    pos = 0
    pattern = re.compile(r"@\w+\s*\{\s*([^,\s]+)\s*,")
    while True:
        m = pattern.search(text, pos)
        if not m:
            return
        key = m.group(1)
        entry_start = m.start()
        open_brace = text.index("{", entry_start)
        depth = 1
        i = open_brace + 1
        while i < len(text) and depth > 0:
            c = text[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            i += 1
        entry_end = i
        yield key, entry_start, entry_end
        pos = entry_end


def normalize_bibkey(key: str) -> str:
    """Capitalize the first letter and the first letter after a 4-digit year.

    Examples:
      feng2025cocoaco -> Feng2025Cocoaco
      august2020explain -> August2020Explain
      Yu2025VOICE -> Yu2025VOICE   (already conformant)
    """
    m = re.search(r"\d{4}", key)
    if not m:
        return key[:1].upper() + key[1:] if key else key
    head = key[: m.start()]
    year = key[m.start() : m.end()]
    tail = key[m.end() :]
    new_head = (head[:1].upper() + head[1:]) if head else head
    new_tail = (tail[:1].upper() + tail[1:]) if tail else tail
    return new_head + year + new_tail


def rename_entry_key(entry_text: str, old_key: str, new_key: str) -> str:
    """Rewrite the bibkey in `@type{key,` at the start of an entry."""
    return re.sub(
        rf"(@\w+\s*\{{\s*){re.escape(old_key)}(\s*,)",
        rf"\1{new_key}\2",
        entry_text,
        count=1,
    )


def find_field(entry_text: str, field_name: str):
    """Return (value, (start, end)) of a top-level field, or None if missing.

    `start` and `end` bracket the whole `name = {value}` chunk so it can be replaced.
    """
    pattern = re.compile(
        rf'(\b{re.escape(field_name)}\s*=\s*)(\{{([^}}]*)\}}|"([^"]*)"|([^,\n}}]+))',
        re.IGNORECASE,
    )
    m = pattern.search(entry_text)
    if not m:
        return None
    if m.group(3) is not None:
        value = m.group(3)
    elif m.group(4) is not None:
        value = m.group(4)
    else:
        value = m.group(5).strip()
    return value, m.span()


def set_field(entry_text: str, field_name: str, new_value: str) -> str:
    """Replace an existing field or insert a new one before the entry's closing brace."""
    found = find_field(entry_text, field_name)
    if found is not None:
        _, (s, e) = found
        return entry_text[:s] + f"{field_name}={{{new_value}}}" + entry_text[e:]

    close = entry_text.rfind("}")
    prefix = entry_text[:close].rstrip()
    suffix = entry_text[close:]
    if not prefix.endswith(","):
        prefix += ","
    return prefix + f"\n    {field_name}={{{new_value}}}\n" + suffix


def report_section(title: str, items, formatter=str) -> None:
    if not items:
        return
    print(f"\n{title}:")
    for item in items:
        print(f"  - {formatter(item)}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without modifying papers.bib",
    )
    ap.add_argument("--bib", default=str(BIB_PATH), help="Path to papers.bib")
    ap.add_argument("--pdf-dir", default=str(PDF_DIR), help="Directory containing PDFs")
    ap.add_argument(
        "--preview-dir",
        default=str(PREVIEW_DIR),
        help="Directory containing preview images",
    )
    args = ap.parse_args()

    bib_path = Path(args.bib)
    pdf_dir = Path(args.pdf_dir)
    preview_dir = Path(args.preview_dir)

    if not bib_path.is_file():
        print(f"error: bib file not found: {bib_path}", file=sys.stderr)
        return 2

    original = bib_path.read_text()

    pdf_files = (
        {p.name for p in pdf_dir.iterdir() if p.is_file()} if pdf_dir.is_dir() else set()
    )
    preview_files = (
        {p.name for p in preview_dir.iterdir() if p.is_file()}
        if preview_dir.is_dir()
        else set()
    )

    renamed_bibkey: list[tuple[str, str]] = []
    added_pdf_field: list[str] = []
    added_preview_field: list[str] = []
    renamed_pdf: list[tuple[str, str, str]] = []
    renamed_preview: list[tuple[str, str, str]] = []
    missing_pdf_file: list[tuple[str, str]] = []
    missing_preview_file: list[tuple[str, str]] = []

    new_text = original
    # Process entries from last to first so earlier offsets stay valid.
    for key, start, end in reversed(list(find_entries(original))):
        entry = new_text[start:end]

        normalized = normalize_bibkey(key)
        if normalized != key:
            renamed_bibkey.append((key, normalized))
            entry = rename_entry_key(entry, key, normalized)
            key = normalized

        expected_pdf = f"{key}.pdf"
        expected_preview = f"{key}.png"

        pdf = find_field(entry, "pdf")
        if pdf is None:
            added_pdf_field.append(key)
            entry = set_field(entry, "pdf", expected_pdf)
            pdf_value = expected_pdf
        elif pdf[0] != expected_pdf:
            renamed_pdf.append((key, pdf[0], expected_pdf))
            entry = set_field(entry, "pdf", expected_pdf)
            pdf_value = expected_pdf
        else:
            pdf_value = pdf[0]

        preview = find_field(entry, "preview")
        if preview is None:
            added_preview_field.append(key)
            entry = set_field(entry, "preview", expected_preview)
            preview_value = expected_preview
        elif preview[0] != expected_preview:
            renamed_preview.append((key, preview[0], expected_preview))
            entry = set_field(entry, "preview", expected_preview)
            preview_value = expected_preview
        else:
            preview_value = preview[0]

        if pdf_value not in pdf_files:
            missing_pdf_file.append((key, pdf_value))
        if preview_value not in preview_files:
            missing_preview_file.append((key, preview_value))

        new_text = new_text[:start] + entry + new_text[end:]

    report_section(
        "Renamed bibkey to match convention",
        sorted(renamed_bibkey),
        lambda t: f"{t[0]} -> {t[1]}",
    )
    report_section("Added missing pdf field", sorted(added_pdf_field))
    report_section("Added missing preview field", sorted(added_preview_field))
    report_section(
        "Renamed pdf field to match bibkey",
        sorted(renamed_pdf),
        lambda t: f"{t[0]}: {t[1]} -> {t[2]}",
    )
    report_section(
        "Renamed preview field to match bibkey",
        sorted(renamed_preview),
        lambda t: f"{t[0]}: {t[1]} -> {t[2]}",
    )
    report_section(
        f"Missing PDF files (expected in {pdf_dir})",
        sorted(missing_pdf_file),
        lambda t: f"{t[0]}: {t[1]}",
    )
    report_section(
        f"Missing preview files (expected in {preview_dir})",
        sorted(missing_preview_file),
        lambda t: f"{t[0]}: {t[1]}",
    )

    bib_changed = new_text != original
    if bib_changed:
        if args.dry_run:
            print("\n(dry-run: papers.bib not modified)")
        else:
            bib_path.write_text(new_text)
            print(f"\nUpdated {bib_path}")
    else:
        print("\nNo bib field changes needed.")

    missing_pdfs_path = REPO_ROOT / "missing_pdfs"
    missing_pngs_path = REPO_ROOT / "missing_pngs"
    missing_pdfs_path.write_text(
        "\n".join(filename for _, filename in sorted(missing_pdf_file)) + ("\n" if missing_pdf_file else "")
    )
    missing_pngs_path.write_text(
        "\n".join(filename for _, filename in sorted(missing_preview_file)) + ("\n" if missing_preview_file else "")
    )
    print(f"\nWrote {missing_pdfs_path} ({len(missing_pdf_file)} entries)")
    print(f"Wrote {missing_pngs_path} ({len(missing_preview_file)} entries)")

    if not missing_pdf_file and not missing_preview_file:
        print("All referenced assets exist.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
