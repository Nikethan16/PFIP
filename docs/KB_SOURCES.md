# Knowledge-Base Sources — Curated Reading List

_Date: 2026-06-23. The chat agent cites these once ingested into Qdrant via
`python -m pfip.kb.ingest data/kb_sources/`. **Ingestion is currently blocked on Qdrant** (the
vector DB), which is parked pending the VPS decision — so this doc curates and sources the corpus
so that ingestion is a single command the moment Qdrant is available._

## Legal policy (non-negotiable)

- **Public-domain** works (generally pre-1929 US publications) may be downloaded freely from
  Project Gutenberg / Internet Archive and dropped into `data/kb_sources/`.
- **In-copyright** works must be **purchased and added by the user** — we do not download or
  redistribute copyrighted PDFs. Links below for those go to the publisher/retailer, not a file.

## Tier 1 — Public domain (legitimately free; safe to auto-fetch)

| # | Work | Author (year) | Why it's in the KB | Source |
| - | --- | --- | --- | --- |
| 1 | Reminiscences of a Stock Operator | Lefèvre (1923) | The canonical trading-psychology / speculation narrative; eval_qa already references it. | [Gutenberg #60979](https://www.gutenberg.org/ebooks/60979), [Archive](https://archive.org/details/reminiscencesofs0000edwi) |
| 2 | Studies in Tape Reading | Wyckoff (1910) | Price/volume reading; `book_to_rules.py` names Wyckoff. | Internet Archive |
| 3 | The ABC of Stock Speculation | Nelson (1903) | Original codification of Dow Theory. | Internet Archive |
| 4 | The Psychology of the Stock Market | Selden (1912) | Early behavioral finance. | Internet Archive |
| 5 | Extraordinary Popular Delusions & the Madness of Crowds | Mackay (1841) | Bubbles/manias case studies. | [Gutenberg #24518](https://www.gutenberg.org/ebooks/24518) |
| 6 | The Crowd: A Study of the Popular Mind | Le Bon (1895) | Crowd psychology underpinning sentiment. | [Gutenberg #445](https://www.gutenberg.org/ebooks/445) |
| 7 | The Wealth of Nations | Smith (1776) | Economic first principles. | [Gutenberg #3300](https://www.gutenberg.org/ebooks/3300) |

## Tier 2 — Open-access academic papers (free, with attribution)

| # | Paper | Author (year) | Why |
| - | --- | --- | --- |
| 8 | Portfolio Selection | Markowitz (1952) | MPT foundation (drives allocation/HHI logic). |
| 9 | The Cross-Section of Expected Stock Returns | Fama & French (1992) | Factor model basis. |
| 10 | Common Risk Factors in Stocks and Bonds | Fama & French (1993) | 3-factor model. |
| 11 | Returns to Buying Winners and Selling Losers | Jegadeesh & Titman (1993) | Momentum evidence (relevant to the trend specialist). |

_Source these from the authors' university pages / NBER / SSRN — verify the posted copy is the
author's open version before adding._

## Tier 3 — In-copyright essentials (USER must buy + add legally)

These are the modern core of the reading list; the repo's `eval_qa.json` already expects some of
them. Purchase and drop the PDF/EPUB into `data/kb_sources/`:

| # | Work | Author | Note |
| - | --- | --- | --- |
| 12 | The Intelligent Investor (rev. ed.) | Graham | Referenced in eval_qa ("Mr. Market"). |
| 13 | Security Analysis | Graham & Dodd | Value-investing bible. |
| 14 | Market Wizards (series) | Schwager | Referenced in eval_qa (risk management). |
| 15 | Common Stocks and Uncommon Profits | Fisher | Growth investing. |
| 16 | Thinking, Fast and Slow | Kahneman | Referenced in `ingest.py` example (`kahneman_tfas.pdf`). |
| 17 | Fooled by Randomness | Taleb | Referenced in `book_to_rules.py`. |
| 18 | The Black Swan | Taleb | Tail risk. |
| 19 | A Random Walk Down Wall Street | Malkiel | EMH counterpoint. |
| 20 | The Little Book of Common Sense Investing | Bogle | Index/SIP discipline (ties to the SIP/Goals pages). |

## Infrastructure (serverless — no VPS)

- **Vector store:** Qdrant Cloud (free 1 GB). Set `QDRANT_URL` + `QDRANT_API_KEY`.
- **Embeddings:** NVIDIA NIM `baai/bge-m3` (1024-dim, symmetric). Set `NVIDIA_NIM_API_KEY`.
  Falls back to local Ollama `nomic-embed-text` if NIM isn't configured.

## How to ingest

1. Fetch the public-domain titles: `python -m scripts.fetch_kb_public_domain`
   (drops Tier-1 books into `data/kb_sources/`). Add Tier-3 (purchased) files manually.
2. Ingest: `python -m pfip.kb.ingest data/kb_sources/`
   (embeds in batches of 50, upserts to Qdrant in batches of 256).
3. Optional: `book_to_rules.py` extracts machine-readable rules into `data/kb_rules/<book>.jsonl`.
4. Validate retrieval against `backend/pfip/kb/eval_qa.json` (RAGAS via `ragas_eval.py`).

## Status (2026-06-24)

- **Tier 1 — ingested ✅.** 4 public-domain books in the `kb` Qdrant collection, **8,796 chunks**:
  Reminiscences of a Stock Operator (1,087), The Crowd (650), Extraordinary Popular Delusions
  (2,893), The Wealth of Nations (4,166). RAG search verified — returns relevant, cited passages.
- **Tier 2** (papers) and **Tier 3** (in-copyright): pending — drop files into `data/kb_sources/`
  and re-run the ingest command (idempotent).
- The chat agent can now cite the Tier-1 corpus.
