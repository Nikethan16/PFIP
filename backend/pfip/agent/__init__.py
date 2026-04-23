"""Agent layer (plan Section 12.1 + 5.5 + Stage 3).

Public surface:

- :mod:`pfip.agent.graph` — LangGraph-style chat agent with SSE streaming.
- :mod:`pfip.agent.morning_brief` — Section 12.1 daily brief.
- :mod:`pfip.agent.post_mortem` — close-time post-mortem drafter.
- :mod:`pfip.agent.weekly_review` — weekly "system / you / change" review.
- :mod:`pfip.agent.arxiv_digest` — weekly arXiv q-fin digest.
- :mod:`pfip.agent.sanitizer` — prompt-injection defenses.
- :mod:`pfip.agent.llm_client` — Ollama/Groq router.
"""
