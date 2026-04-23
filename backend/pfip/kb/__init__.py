"""Knowledge base RAG (plan Section 10).

Public surface:

- :mod:`pfip.kb.ingest` — PDF/EPUB/text → Qdrant ``kb`` collection.
- :mod:`pfip.kb.search` — semantic search with citation formatting.
- :mod:`pfip.kb.news_embed` — news → Qdrant ``news`` collection (Prefect flow).
"""

# Intentionally do not re-export the submodule names here; submodule
# imports must use ``from pfip.kb.search import search`` explicitly so that
# ``pfip.kb.search`` always resolves to the submodule, not a function.
