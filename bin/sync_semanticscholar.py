#!/usr/bin/env python3
"""Sync publications from Semantic Scholar into _bibliography/papers.bib.

Only rewrites the block between the AUTO-SYNCED markers. Anything outside
that block (e.g. manually-added entries not indexed on Semantic Scholar)
is left untouched.
"""
import json
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

AUTHOR_ID = "2289835320"
API_URL = (
    f"https://api.semanticscholar.org/graph/v1/author/{AUTHOR_ID}/papers"
    "?fields=title,year,venue,publicationVenue,externalIds,abstract,authors,"
    "url,publicationDate,publicationTypes,journal"
)
BIB_PATH = Path(__file__).resolve().parent.parent / "_bibliography" / "papers.bib"
BEGIN_MARKER = "%%% BEGIN AUTO-SYNCED (Semantic Scholar, do not edit by hand) %%%"
END_MARKER = "%%% END AUTO-SYNCED (Semantic Scholar) %%%"


def fetch_papers():
    import time

    req = urllib.request.Request(API_URL, headers={"User-Agent": "portfolio-sync/1.0"})
    last_err = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.load(resp)
            return data.get("data", [])
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429:
                wait = 10 * (attempt + 1)
                print(f"Rate limited, retrying in {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
    raise last_err


def escape_bib(value):
    # Balanced braces (e.g. LaTeX math like $M^{-T}$) are valid inside a
    # bibtex field and must be kept; only strip braces that would break
    # the field's own {..} delimiters by being unbalanced.
    if value.count("{") == value.count("}"):
        return value
    return value.replace("{", "").replace("}", "")


def month_name(publication_date):
    if not publication_date:
        return None
    try:
        return datetime.strptime(publication_date, "%Y-%m-%d").strftime("%B").lower()
    except ValueError:
        return None


def format_authors(authors):
    names = [a["name"] for a in authors if a.get("name")]
    return " and ".join(names) if names else "Salman Faroz"


def bib_key(paper):
    doi = paper.get("externalIds", {}).get("DOI")
    if doi:
        return doi
    arxiv = paper.get("externalIds", {}).get("ArXiv")
    if arxiv:
        return f"arXiv.{arxiv}"
    return paper["paperId"]


# Fields we never get from the API but may have been curated by hand on a
# previous sync -- preserved across runs. No preview images: keep every
# entry consistent rather than a mix of some with images, some without.
PRESERVED_FIELDS = ("bibtex_show",)


def parse_preserved_fields(text):
    preserved = {}
    for match in re.finditer(r"@\w+\{([^,]+),(.*?)\n\}", text, re.DOTALL):
        key, body = match.group(1).strip(), match.group(2)
        fields = {}
        for field in PRESERVED_FIELDS:
            m = re.search(rf"{field}\s*=\s*\{{(.*?)\}},", body)
            if m:
                fields[field] = m.group(1).strip()
        if fields:
            preserved[key] = fields
    return preserved


def build_entry(paper, preserved_fields):
    title = escape_bib(paper["title"])
    arxiv_id = paper.get("externalIds", {}).get("ArXiv")
    key = bib_key(paper)
    author = format_authors(paper.get("authors", []))
    year = paper.get("year") or ""
    month = month_name(paper.get("publicationDate"))
    abstract = escape_bib(paper.get("abstract") or "")

    fields = [
        ("abbr", "Arxiv" if arxiv_id else "Paper"),
    ]
    if abstract:
        fields.append(("abstract", abstract))
    if arxiv_id:
        fields.append(("arxiv", arxiv_id))
    fields.append(("author", author))
    fields.append(("booktitle", title))
    if month:
        fields.append(("month", month))
    if arxiv_id:
        fields.append(("pdf", f"https://arxiv.org/pdf/{arxiv_id}"))
    fields.append(("publisher", "Arxiv" if arxiv_id else (paper.get("venue") or "")))
    for name, value in preserved_fields.get(key, {}).items():
        fields.append((name, value))
    fields.append(("title", title))
    fields.append(("year", str(year)))
    fields.sort(key=lambda kv: kv[0])

    lines = [f"@InProceedings{{{key},"]
    for name, value in fields:
        if value == "":
            continue
        lines.append(f"  {name}={{{value}}},")
    lines.append("}")
    return "\n".join(lines)


def main():
    papers = fetch_papers()
    if not papers:
        print("No papers returned from Semantic Scholar API; aborting without changes.", file=sys.stderr)
        return 1

    papers.sort(key=lambda p: (p.get("year") or 0, p.get("publicationDate") or ""), reverse=True)

    text = BIB_PATH.read_text()
    preserved_fields = parse_preserved_fields(text)
    entries = "\n\n".join(build_entry(p, preserved_fields) for p in papers)
    block = f"{BEGIN_MARKER}\n\n{entries}\n\n{END_MARKER}"

    if BEGIN_MARKER in text and END_MARKER in text:
        pattern = re.compile(
            re.escape(BEGIN_MARKER) + r".*?" + re.escape(END_MARKER), re.DOTALL
        )
        new_text = pattern.sub(block, text)
    else:
        new_text = text.rstrip("\n") + "\n\n" + block + "\n"

    BIB_PATH.write_text(new_text)
    print(f"Synced {len(papers)} papers from Semantic Scholar into {BIB_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
