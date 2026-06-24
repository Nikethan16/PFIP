"""Knowledge-base ingestion pipeline.

Reads a book (PDF, EPUB, or plain text/markdown), chunks it semantically,
embeds each chunk via ``nomic-embed-text`` on Ollama, and stores the chunks
in the Qdrant ``kb`` collection. Idempotent — we hash the source path +
file bytes and skip if the hash is already recorded in ``kb_ingestions``.

Usage
-----
Programmatic::

    from pathlib import Path
    from pfip.kb.ingest import ingest_book
    await ingest_book(Path("/data/kb_sources/kahneman_tfas.pdf"),
                      title="Thinking, Fast and Slow",
                      author="Daniel Kahneman",
                      category="behavioral")

CLI (iterates a folder)::

    python -m pfip.kb.ingest /data/kb_sources/

For a folder we auto-derive ``title`` from the filename stem and mark
``author=unknown``, ``category=unsorted``. Users should re-run with
explicit kwargs on a book-by-book basis for proper metadata.

Dependencies
------------
- ``pypdf`` for PDFs.
- ``ebooklib`` + ``beautifulsoup4`` for EPUBs.
- ``langchain-text-splitters`` for the recursive splitter.

These are optional — the ingest function lazily imports each one and
emits a helpful error if missing.
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger
from qdrant_client.http import models as qmodels
from sqlalchemy import select

from pfip.agent.llm_client import LLMUnavailable
from pfip.db.session import get_sessionmaker
from pfip.kb.search import KB_COLLECTION, get_qdrant

# Chunking defaults per task spec.
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
# Separators tuned for prose — paragraphs, then sentences, then words.
SEPARATORS: list[str] = ["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ", ""]

SUPPORTED_SUFFIXES = {".pdf", ".epub", ".txt", ".md", ".markdown"}


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Summary of an ingestion run."""

    path: Path
    title: str
    chunks_written: int
    skipped: bool
    reason: str | None = None


# ---------------------------------------------------------------------------
# Loaders — one per supported format. Each returns list[(text, metadata)].
# ---------------------------------------------------------------------------


def _load_pdf(path: Path) -> list[tuple[str, dict[str, Any]]]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover — dependency absent
        raise RuntimeError("pypdf is required for PDF ingest. `pip install pypdf`.") from exc
    reader = PdfReader(str(path))
    out: list[tuple[str, dict[str, Any]]] = []
    for i, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if not text:
            continue
        out.append((text, {"page_range": f"p.{i}"}))
    return out


def _load_epub(path: Path) -> list[tuple[str, dict[str, Any]]]:
    try:
        import ebooklib
        from ebooklib import epub
        from bs4 import BeautifulSoup
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("ebooklib + beautifulsoup4 required for EPUB ingest.") from exc
    book = epub.read_epub(str(path))
    out: list[tuple[str, dict[str, Any]]] = []
    for idx, item in enumerate(book.get_items_of_type(ebooklib.ITEM_DOCUMENT), start=1):
        html = item.get_content().decode("utf-8", errors="ignore")
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text("\n").strip()
        if not text:
            continue
        chap_title = None
        if soup.find(["h1", "h2", "h3"]):
            chap_title = soup.find(["h1", "h2", "h3"]).get_text(strip=True)
        out.append((text, {"chapter": chap_title or f"section_{idx}"}))
    return out


def _load_text(path: Path) -> list[tuple[str, dict[str, Any]]]:
    return [(path.read_text(encoding="utf-8", errors="ignore"), {})]


def _load_by_suffix(path: Path) -> list[tuple[str, dict[str, Any]]]:
    suf = path.suffix.lower()
    if suf == ".pdf":
        return _load_pdf(path)
    if suf == ".epub":
        return _load_epub(path)
    if suf in {".txt", ".md", ".markdown"}:
        return _load_text(path)
    raise ValueError(f"Unsupported KB file type: {path.suffix}")


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def _get_splitter():
    """Lazy import of langchain splitter so test envs without it still boot."""
    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
    except ImportError:
        try:
            from langchain.text_splitter import RecursiveCharacterTextSplitter  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "langchain-text-splitters is required. " "`pip install langchain-text-splitters`."
            ) from exc
    return RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=SEPARATORS,
        length_function=len,
    )


def chunk_text(text: str) -> list[str]:
    """Split ``text`` into prose-friendly chunks."""
    splitter = _get_splitter()
    return [c for c in splitter.split_text(text) if c.strip()]


# ---------------------------------------------------------------------------
# Hashing / idempotency
# ---------------------------------------------------------------------------


def _path_hash(path: Path) -> str:
    h = hashlib.sha256()
    h.update(str(path.resolve()).encode("utf-8"))
    try:
        with path.open("rb") as f:
            while True:
                buf = f.read(1 << 16)
                if not buf:
                    break
                h.update(buf)
    except OSError:
        pass
    return h.hexdigest()


async def _already_ingested(path_hash: str) -> bool:
    from sqlalchemy import text as sql_text

    factory = get_sessionmaker()
    async with factory() as session:
        try:
            stmt = sql_text("SELECT 1 FROM kb_ingestions WHERE path_hash = :h LIMIT 1")
            result = await session.execute(stmt, {"h": path_hash})
            return result.scalar() is not None
        except Exception as exc:  # noqa: BLE001 — migrations may not yet be applied
            logger.warning(f"kb_ingestions lookup failed; treating as new: {exc}")
            return False


async def _record_ingestion(
    *, title: str, author: str, category: str, path_hash: str, chunks_count: int
) -> None:
    from sqlalchemy import text as sql_text

    factory = get_sessionmaker()
    async with factory() as session:
        stmt = sql_text(
            """
            INSERT INTO kb_ingestions (title, author, category, path_hash, chunks_count)
            VALUES (:title, :author, :category, :path_hash, :chunks_count)
            ON CONFLICT (path_hash) DO UPDATE SET chunks_count = EXCLUDED.chunks_count,
                                                  embedded_at = now()
            """
        )
        await session.execute(
            stmt,
            {
                "title": title,
                "author": author,
                "category": category,
                "path_hash": path_hash,
                "chunks_count": chunks_count,
            },
        )
        await session.commit()


# ---------------------------------------------------------------------------
# Qdrant collection bootstrap
# ---------------------------------------------------------------------------


async def _ensure_collection(dim: int) -> None:
    client = get_qdrant()
    try:
        await client.get_collection(KB_COLLECTION)
        return
    except Exception:  # noqa: BLE001 — "not found" raises a typed error we can't import cheaply
        pass
    logger.info(f"Creating Qdrant collection '{KB_COLLECTION}' dim={dim}")
    await client.create_collection(
        collection_name=KB_COLLECTION,
        vectors_config=qmodels.VectorParams(size=dim, distance=qmodels.Distance.COSINE),
    )


# ---------------------------------------------------------------------------
# Main ingest entrypoint
# ---------------------------------------------------------------------------


async def ingest_book(path: Path, *, title: str, author: str, category: str) -> IngestResult:
    """Ingest one book. Returns a summary; idempotent."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Unsupported suffix: {path.suffix}")

    h = _path_hash(path)
    if await _already_ingested(h):
        logger.info(f"Skipping already-ingested: {path.name}")
        return IngestResult(
            path=path, title=title, chunks_written=0, skipped=True, reason="already ingested"
        )

    # 1. Load source -> list of (text, metadata).
    sections = _load_by_suffix(path)
    if not sections:
        return IngestResult(
            path=path, title=title, chunks_written=0, skipped=True, reason="empty source"
        )

    # 2. Chunk each section.
    chunks: list[tuple[str, dict[str, Any]]] = []
    for section_text, section_meta in sections:
        for chunk_idx, chunk in enumerate(chunk_text(section_text)):
            chunks.append((chunk, {**section_meta, "chunk_idx": chunk_idx}))
    if not chunks:
        return IngestResult(
            path=path, title=title, chunks_written=0, skipped=True, reason="no chunks produced"
        )

    # 3. Embed — batched (one request per BATCH chunks, not one per chunk), via
    # the embedder facade so it uses the configured provider (NVIDIA NIM / Ollama).
    from pfip.agent.embedder import get_embedder

    embedder = get_embedder()
    texts = [c for c, _ in chunks]
    _BATCH = 50
    vectors: list[list[float]] = []
    try:
        for start in range(0, len(texts), _BATCH):
            vectors.extend(await embedder.embed(texts[start : start + _BATCH]))
    except LLMUnavailable as exc:
        raise RuntimeError(
            f"Cannot embed — {exc}. Set NVIDIA_NIM_API_KEY or run a local Ollama "
            "with nomic-embed-text."
        ) from exc
    if not vectors:
        return IngestResult(
            path=path, title=title, chunks_written=0, skipped=True, reason="no vectors produced"
        )
    dim = len(vectors[0])
    await _ensure_collection(dim)

    # 4. Upsert into Qdrant with rich metadata.
    client = get_qdrant()
    points = []
    for i, ((chunk, meta), vec) in enumerate(zip(chunks, vectors, strict=True)):
        point_id = int(hashlib.sha1(f"{h}:{i}".encode()).hexdigest()[:15], 16)
        payload: dict[str, Any] = {
            "text": chunk,
            "title": title,
            "author": author,
            "category": category,
            "chunk_id": f"{h[:8]}:{i}",
            "source_type": "book",
            **meta,
        }
        points.append(qmodels.PointStruct(id=point_id, vector=vec, payload=payload))
    # Upsert in batches — a whole large book in one request exceeds Qdrant's
    # 32 MB payload limit (a ~3k-chunk book is ~84 MB of vectors + text).
    _UPSERT_BATCH = 256
    for start in range(0, len(points), _UPSERT_BATCH):
        await client.upsert(
            collection_name=KB_COLLECTION, points=points[start : start + _UPSERT_BATCH]
        )

    # 5. Ledger row.
    await _record_ingestion(
        title=title, author=author, category=category, path_hash=h, chunks_count=len(chunks)
    )
    logger.info(f"Ingested {len(chunks)} chunks from {title}")
    return IngestResult(path=path, title=title, chunks_written=len(chunks), skipped=False)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


async def _iter_folder(folder: Path) -> list[IngestResult]:
    results: list[IngestResult] = []
    for p in sorted(folder.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        title = p.stem.replace("_", " ").title()
        try:
            res = await ingest_book(p, title=title, author="unknown", category="unsorted")
        except Exception as exc:  # noqa: BLE001 — keep chugging on per-file errors
            logger.error(f"Failed to ingest {p}: {exc}")
            results.append(
                IngestResult(path=p, title=title, chunks_written=0, skipped=True, reason=str(exc))
            )
            continue
        results.append(res)
    return results


def _cli_main() -> None:
    if len(sys.argv) < 2:
        print("usage: python -m pfip.kb.ingest <folder>", file=sys.stderr)
        sys.exit(2)
    folder = Path(sys.argv[1])
    if not folder.is_dir():
        print(f"not a directory: {folder}", file=sys.stderr)
        sys.exit(2)
    results = asyncio.run(_iter_folder(folder))
    total_chunks = sum(r.chunks_written for r in results)
    skipped = sum(1 for r in results if r.skipped)
    print(
        f"Done. {len(results)} files processed, {total_chunks} chunks written, "
        f"{skipped} skipped."
    )


if __name__ == "__main__":  # pragma: no cover
    _cli_main()


__all__ = [
    "CHUNK_OVERLAP",
    "CHUNK_SIZE",
    "IngestResult",
    "SEPARATORS",
    "SUPPORTED_SUFFIXES",
    "chunk_text",
    "ingest_book",
]
