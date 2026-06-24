"""Fetch the public-domain KB books into ``data/kb_sources/``.

Downloads only the **public-domain** titles from ``docs/KB_SOURCES.md`` Tier 1
(Project Gutenberg plain-text). In-copyright titles are never fetched — those
must be supplied by the user (see the doc). Idempotent: skips files already
present. Plain stdlib (urllib), no extra deps.

Run from the repo root or ``backend/``::

    python -m scripts.fetch_kb_public_domain
    python -m scripts.fetch_kb_public_domain --dest /custom/dir

Then ingest (once Qdrant + an embedding provider are configured)::

    python -m pfip.kb.ingest data/kb_sources/
"""

from __future__ import annotations

import argparse
import urllib.request
from pathlib import Path

# (Gutenberg ID, output filename, title, author) — all confirmed public domain.
BOOKS: list[tuple[int, str, str, str]] = [
    (
        60979,
        "lefevre_reminiscences_of_a_stock_operator.txt",
        "Reminiscences of a Stock Operator",
        "Edwin Lefevre",
    ),
    (
        24518,
        "mackay_extraordinary_popular_delusions.txt",
        "Extraordinary Popular Delusions and the Madness of Crowds",
        "Charles Mackay",
    ),
    (445, "lebon_the_crowd.txt", "The Crowd: A Study of the Popular Mind", "Gustave Le Bon"),
    (3300, "smith_wealth_of_nations.txt", "The Wealth of Nations", "Adam Smith"),
]

# Stable plain-text endpoint for a Gutenberg ebook id.
_URL = "https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt"


def _default_dest() -> Path:
    here = Path(__file__).resolve()
    # backend/scripts/this.py → repo root is two levels up.
    return here.parents[2] / "data" / "kb_sources"


def fetch_all(dest: Path) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    fetched = 0
    for book_id, filename, title, author in BOOKS:
        out = dest / filename
        if out.exists() and out.stat().st_size > 0:
            print(f"skip (exists): {filename}")
            continue
        url = _URL.format(id=book_id)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "pfip-kb-fetch/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - trusted host
                data = resp.read()
            out.write_bytes(data)
            print(f"fetched: {title} — {author}  ({len(data) // 1024} KB) -> {filename}")
            fetched += 1
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED {title} ({url}): {type(exc).__name__}: {exc}")
    return fetched


def main() -> None:
    p = argparse.ArgumentParser(description="Fetch public-domain KB books (Gutenberg).")
    p.add_argument(
        "--dest", type=Path, default=None, help="Target dir (default: data/kb_sources/)."
    )
    args = p.parse_args()
    dest = args.dest or _default_dest()
    n = fetch_all(dest)
    print(f"\nDone. {n} new file(s) in {dest}.")


if __name__ == "__main__":
    main()
