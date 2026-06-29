"""Curated investment-theme catalogue (Phase 4).

Each theme is a label + keyword set. The engine matches these keywords against
the entity-linked news to find which TRACKED companies have news exposure to the
theme — a research aid, not a recommendation. Extend freely; keep keywords
lowercase and reasonably specific to avoid spurious matches.
"""

from __future__ import annotations

THEMES: dict[str, dict] = {
    "ai": {
        "label": "AI buildout",
        "keywords": [
            "artificial intelligence",
            "generative ai",
            "genai",
            "chatgpt",
            "large language model",
            " llm",
            "machine learning",
            "ai chip",
            "ai data center",
            "ai data centre",
            "copilot",
            "openai",
        ],
    },
    "semiconductors": {
        "label": "Semiconductors",
        "keywords": [
            "semiconductor",
            "chipmaker",
            " chip ",
            "foundry",
            "wafer",
            "fab ",
            "lithography",
            "nm node",
            "tsmc",
        ],
    },
    "ev": {
        "label": "Electric vehicles",
        "keywords": [
            "electric vehicle",
            " ev ",
            "ev sales",
            "battery",
            "lithium",
            "charging network",
            "gigafactory",
        ],
    },
    "defense": {
        "label": "Defense & aerospace",
        "keywords": [
            "defence",
            "defense",
            "missile",
            "aerospace",
            "fighter jet",
            "warship",
            "arms deal",
            "military order",
        ],
    },
    "clean_energy": {
        "label": "Clean energy",
        "keywords": [
            "solar",
            "wind power",
            "renewable",
            "green hydrogen",
            "clean energy",
            "energy transition",
        ],
    },
    "india_infra": {
        "label": "India infrastructure & PLI",
        "keywords": [
            "infrastructure",
            "pli scheme",
            "production linked incentive",
            "capex",
            "highway",
            "railway",
            "metro",
            "make in india",
            "order win",
            "tender",
        ],
    },
    "financials": {
        "label": "Banks & financials",
        "keywords": [
            "bank",
            "lender",
            "nbfc",
            "credit growth",
            "loan book",
            "deposit",
            "interest rate",
            "rbi ",
        ],
    },
    "crypto": {
        "label": "Crypto & blockchain",
        "keywords": [
            "bitcoin",
            "ethereum",
            "crypto",
            "blockchain",
            "spot etf",
            "halving",
            "stablecoin",
        ],
    },
    "healthcare": {
        "label": "Healthcare & pharma",
        "keywords": [
            "pharma",
            "drug ",
            "fda",
            "clinical trial",
            "vaccine",
            "biotech",
            "usfda",
        ],
    },
    "energy": {
        "label": "Oil & gas",
        "keywords": ["crude", "oil price", "opec", "natural gas", "refinery", "per barrel"],
    },
}


def list_themes() -> list[dict]:
    """Theme slugs + labels for the explorer."""
    return [{"slug": k, "label": v["label"], "keywords": v["keywords"]} for k, v in THEMES.items()]
