#!/usr/bin/env python3
"""check_new_papers — find papers on Semantic Scholar that are not yet in papers.bib.

Pulls the author's paper list from the Semantic Scholar API (free, no key),
matches each paper against papers.bib by arXiv id or title, and prints a
ready-to-paste BibTeX entry for every paper that is missing. Entries follow
the site conventions (see check_papers.py): bibkey like Song2026ParseJargon,
pdf = {<bibkey>.pdf}, preview = {<bibkey>.png}.

  --add       append the missing entries to papers.bib
  --download  fetch open-access PDFs (arXiv / ACL Anthology / etc.) into
              assets/pdf/<bibkey>.pdf

Papers you never want listed (misattributed, duplicates, abstracts) go in
_bibliography/s2_ignore.txt — one Semantic Scholar paperId or exact title per
line; lines starting with # are comments.

Typical flow after a new paper appears:
  python check_new_papers.py --add --download
  python check_papers.py          # verify fields, list missing assets
  python extract_preview.py       # make preview PNGs from the PDFs
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from check_papers import BIB_PATH, PDF_DIR, find_entries, find_field, normalize_bibkey

REPO_ROOT = Path(__file__).resolve().parent
IGNORE_PATH = REPO_ROOT / "_bibliography" / "s2_ignore.txt"
S2_AUTHOR_ID = "50509991"  # semanticscholar_id in _config.yml
S2_URL = "https://api.semanticscholar.org/graph/v1/author/{id}/papers"
S2_FIELDS = "title,year,venue,externalIds,openAccessPdf,authors"
USER_AGENT = "talaugust.github.io check_new_papers.py"
TITLE_MATCH_RATIO = 0.9

# Semantic Scholar venue name -> booktitle as written elsewhere in papers.bib.
VENUE_NAMES = {
    "International Conference on Human Factors in Computing Systems": "Proceedings of the CHI Conference on Human Factors in Computing Systems (CHI)",
    "Annual Meeting of the Association for Computational Linguistics": "Proceedings of the Association for Computational Linguistics (ACL)",
    "Conference on Empirical Methods in Natural Language Processing": "Conference on Empirical Methods in Natural Language Processing (EMNLP)",
    "North American Chapter of the Association for Computational Linguistics": "In Proceedings of Annual Conference of the North American Chapter of the Association for Computational Linguistics (NAACL)",
    "ACM Symposium on User Interface Software and Technology": "ACM Symposium on User Interface Software and Technology (UIST)",
    "Proc. ACM Hum. Comput. Interact.": "Proceedings of the ACM on Human-Computer Interaction (CSCW)",
    "Conference on Language Modeling": "Conference on Language Modeling (COLM)",
    "International Conference on Web and Social Media": "The International AAAI Conference on Web and Social Media (ICWSM)",
    "Communications of the ACM": "Communications of the ACM (CACM)",
    "arXiv.org": "Arxiv",
}

TITLE_STOPWORDS = {"a", "an", "the", "on", "of", "in", "for", "to", "and", "with", "is", "are", "how", "what", "when", "why", "do", "does", "can"}


def http_get(url: str, retries: int = 5) -> bytes:
    """GET with backoff on 429/5xx (the unauthenticated S2 API rate-limits)."""
    delay = 2.0
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise RuntimeError("unreachable")


def fetch_s2_papers(author_id: str) -> list[dict]:
    papers: list[dict] = []
    offset = 0
    while True:
        url = f"{S2_URL.format(id=author_id)}?fields={S2_FIELDS}&limit=100&offset={offset}"
        page = json.loads(http_get(url))
        papers.extend(page.get("data", []))
        if "next" not in page:
            return papers
        offset = page["next"]


def norm_title(title: str) -> str:
    title = re.sub(r"\\[a-zA-Z]+|[{}]", "", title)
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def author_year(key: str) -> tuple[str, str] | None:
    """Bibkeys look like August2020Explain -> ("august", "2020")."""
    m = re.match(r"([A-Za-z]+)(\d{4})", key)
    return (m.group(1).lower(), m.group(2)) if m else None


def load_bib(bib_text: str) -> tuple[list[str], set[str], set[str]]:
    """Return (normalized titles, arXiv ids, bibkeys) found in papers.bib."""
    titles: list[str] = []
    arxiv_ids: set[str] = set()
    keys: set[str] = set()
    for key, start, end in find_entries(bib_text):
        entry = bib_text[start:end]
        keys.add(key)
        title = find_field(entry, "title")
        if title:
            titles.append(norm_title(title[0]))
        arxiv = find_field(entry, "arxiv")
        if arxiv:
            arxiv_ids.add(arxiv[0].strip())
    return titles, arxiv_ids, keys


def load_ignore() -> set[str]:
    if not IGNORE_PATH.is_file():
        return set()
    lines = (line.strip() for line in IGNORE_PATH.read_text().splitlines())
    return {norm_title(line) if " " in line else line for line in lines if line and not line.startswith("#")}


def in_bib(paper: dict, bib_titles: list[str], bib_arxiv: set[str]) -> bool:
    arxiv = (paper.get("externalIds") or {}).get("ArXiv")
    if arxiv and arxiv in bib_arxiv:
        return True
    title = norm_title(paper.get("title") or "")
    if title in bib_titles:
        return True
    return any(
        difflib.SequenceMatcher(None, title, t).ratio() >= TITLE_MATCH_RATIO
        for t in bib_titles
    )


def first_author_last(paper: dict) -> str:
    authors = paper.get("authors") or []
    last = authors[0]["name"].split()[-1] if authors else "Unknown"
    return re.sub(r"[^A-Za-z]", "", last)


def make_bibkey(paper: dict, taken: set[str]) -> str:
    last = first_author_last(paper)
    words = re.findall(r"[A-Za-z0-9]+", paper.get("title") or "")
    word = next((w for w in words if w.lower() not in TITLE_STOPWORDS), words[0] if words else "Paper")
    base = normalize_bibkey(f"{last}{paper.get('year') or ''}{word}")
    key, n = base, 2
    while key in taken:
        key, n = f"{base}{n}", n + 1
    return key


def make_entry(paper: dict, key: str) -> str:
    venue = paper.get("venue") or "Arxiv"
    booktitle = VENUE_NAMES.get(venue, venue)
    authors = " and ".join(a["name"] for a in paper.get("authors") or [])
    review = "non-peer-review" if booktitle == "Arxiv" else "peer-review"
    lines = [
        f"@inproceedings{{{key},",
        f"  title={{{paper.get('title')}}},",
        f"  author={{{authors}}},",
        f"  booktitle={{{booktitle}}},",
        f"  year={{{paper.get('year')}}},",
    ]
    arxiv = (paper.get("externalIds") or {}).get("ArXiv")
    if arxiv:
        lines.append(f"  arxiv={{{arxiv}}},")
    lines += [
        f"  pdf={{{key}.pdf}},",
        f"  preview={{{key}.png}},",
        f"  keywords = {{{review}}}",
        "}",
    ]
    return "\n".join(lines)


def pdf_urls(paper: dict) -> list[str]:
    urls = []
    arxiv = (paper.get("externalIds") or {}).get("ArXiv")
    if arxiv:
        urls.append(f"https://arxiv.org/pdf/{arxiv}")
    oa = ((paper.get("openAccessPdf") or {}).get("url") or "").strip()
    if oa and "doi.org/" not in oa:  # doi.org links land on publisher HTML, not a PDF
        urls.append(oa)
    return urls


def download_pdf(paper: dict, dest: Path) -> str | None:
    """Try each open-access URL; return the one that worked, or None."""
    for url in pdf_urls(paper):
        try:
            data = http_get(url, retries=2)
        except (urllib.error.URLError, TimeoutError):
            continue
        if data.startswith(b"%PDF"):
            dest.write_bytes(data)
            return url
    return None


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--add", action="store_true", help="Append missing entries to papers.bib")
    ap.add_argument("--download", action="store_true", help="Download open-access PDFs into assets/pdf/")
    ap.add_argument("--since", type=int, default=None, help="Only consider papers from this year onward")
    ap.add_argument("--author-id", default=S2_AUTHOR_ID, help="Semantic Scholar author id")
    args = ap.parse_args()

    bib_text = BIB_PATH.read_text()
    bib_titles, bib_arxiv, taken_keys = load_bib(bib_text)
    ignore = load_ignore()

    print(f"Fetching papers for Semantic Scholar author {args.author_id} ...")
    papers = fetch_s2_papers(args.author_id)
    print(f"  {len(papers)} papers on Semantic Scholar, {len(bib_titles)} in papers.bib")

    bib_author_years: dict[tuple[str, str], list[str]] = {}
    for key in sorted(taken_keys):
        if (ay := author_year(key)):
            bib_author_years.setdefault(ay, []).append(key)

    missing, possible_dups, skipped = [], [], 0
    for paper in papers:
        if args.since and (paper.get("year") or 0) < args.since:
            continue
        if paper["paperId"] in ignore or norm_title(paper.get("title") or "") in ignore:
            continue
        # Proceedings front matter and malformed records: no year or a huge author list.
        if not paper.get("year") or len(paper.get("authors") or []) > 50:
            skipped += 1
            continue
        if in_bib(paper, bib_titles, bib_arxiv):
            continue
        same = bib_author_years.get((first_author_last(paper).lower(), str(paper["year"])))
        if same:
            possible_dups.append((paper, same))
        else:
            missing.append(paper)
    missing.sort(key=lambda p: -p["year"])

    if skipped:
        print(f"  skipped {skipped} malformed record(s) (no year or >50 authors)")

    if possible_dups:
        print(f"\n{len(possible_dups)} possible duplicate(s) — same first author + year as an existing entry,")
        print("probably a retitled/preprint version. Not added; put the paperId in s2_ignore.txt if so:\n")
        for paper, same in possible_dups:
            print(f"  {paper['paperId']}  {paper['year']}  {paper['title']}")
            print(f"      vs. {', '.join(same)}")

    if not missing:
        print("\nNo new papers — papers.bib is up to date with Semantic Scholar.")
        return 0

    print(f"\n{len(missing)} new paper(s) not in papers.bib:\n")
    entries = []
    no_pdf = []
    for paper in missing:
        key = make_bibkey(paper, taken_keys)
        taken_keys.add(key)
        entry = make_entry(paper, key)
        entries.append(entry)
        print(f"% S2 paperId: {paper['paperId']}  (add to s2_ignore.txt to skip)")
        print(entry + "\n")

        if args.download:
            dest = PDF_DIR / f"{key}.pdf"
            if dest.exists():
                print(f"  pdf: {dest.name} already exists\n")
            elif (url := download_pdf(paper, dest)):
                print(f"  pdf: downloaded {url} -> assets/pdf/{dest.name}\n")
            else:
                no_pdf.append(key)
                print("  pdf: no open-access PDF found — add it by hand\n")

    if args.add:
        BIB_PATH.write_text(bib_text.rstrip() + "\n\n" + "\n\n".join(entries) + "\n")
        print(f"Appended {len(entries)} entr{'y' if len(entries) == 1 else 'ies'} to {BIB_PATH}")
        print("Review the booktitle/author fields, then run: python check_papers.py && python extract_preview.py")
    else:
        print("(not written — rerun with --add to append these to papers.bib)")

    if no_pdf:
        print(f"\nNeeds a manual PDF in assets/pdf/: {', '.join(no_pdf)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
