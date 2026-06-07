"""Tests for pfip.kb.book_to_rules — heuristic + LLM-fallback paths."""

from __future__ import annotations

import json
from typing import Any

import pytest

from pfip.kb.book_to_rules import (
    ExtractedRule,
    extract_rules_heuristic,
    extract_rules_llm,
    rules_to_jsonl,
)


# ---------------------------------------------------------------------------
# Heuristic
# ---------------------------------------------------------------------------


def test_heuristic_extracts_if_then():
    text = "If the volume exceeds the 20-day average then enter the position."
    rules = extract_rules_heuristic(text, source="Wyckoff ch.4")
    assert len(rules) == 1
    assert "volume" in rules[0].rule_text
    assert rules[0].source == "Wyckoff ch.4"
    assert rules[0].confidence > 0.5
    assert rules[0].method == "heuristic"


def test_heuristic_extracts_never():
    text = "Never average down on a losing trade."
    rules = extract_rules_heuristic(text)
    assert len(rules) == 1
    assert rules[0].rule_text.lower().startswith("never")


def test_heuristic_extracts_cut_losses():
    text = "Cut losses when the price closes below the 50-day moving average."
    rules = extract_rules_heuristic(text)
    assert len(rules) == 1
    assert "cut losses" in rules[0].rule_text.lower()


def test_heuristic_no_rules_in_descriptive_text():
    text = "The market opened higher today. Many traders bought at the open."
    assert extract_rules_heuristic(text) == []


def test_heuristic_multiple_sentences():
    text = (
        "Always size positions based on conviction. "
        "Never risk more than two percent of capital on one trade. "
        "The market is fickle and traders should be patient."
    )
    rules = extract_rules_heuristic(text)
    # First two sentences match; the third doesn't.
    assert len(rules) == 2


# ---------------------------------------------------------------------------
# LLM path with mock
# ---------------------------------------------------------------------------


class _FakeLLM:
    """Minimal duck-typed LLM with .generate(prompt) → str."""

    def __init__(self, response: str) -> None:
        self._response = response
        self.calls: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self._response


@pytest.mark.asyncio
async def test_llm_parses_valid_json():
    payload = json.dumps(
        [
            {
                "rule_text": "Never anchor to your entry price.",
                "preconditions": [],
                "confidence": 0.9,
            }
        ]
    )
    llm = _FakeLLM(payload)
    rules = await extract_rules_llm("...", llm, source="Tharp")
    assert len(rules) == 1
    assert rules[0].method == "llm"
    assert rules[0].source == "Tharp"


@pytest.mark.asyncio
async def test_llm_strips_code_fences():
    payload = '```json\n[{"rule_text": "Wait for confirmation.", "confidence": 0.7}]\n```'
    llm = _FakeLLM(payload)
    rules = await extract_rules_llm("...", llm)
    assert len(rules) == 1
    assert rules[0].rule_text == "Wait for confirmation."


@pytest.mark.asyncio
async def test_llm_falls_back_on_bad_json():
    llm = _FakeLLM("this is not json")
    rules = await extract_rules_llm("Never chase a stock that has gapped up.", llm, source="ch1")
    # Heuristic must have caught the 'Never' sentence.
    assert len(rules) == 1
    assert rules[0].method == "heuristic"


@pytest.mark.asyncio
async def test_llm_falls_back_on_empty_text():
    llm = _FakeLLM("[]")
    rules = await extract_rules_llm("", llm)
    assert rules == []


@pytest.mark.asyncio
async def test_llm_falls_back_on_generate_exception():
    class _Boom:
        async def generate(self, _prompt: str) -> str:
            raise RuntimeError("nope")

    rules = await extract_rules_llm("Always honour your stop loss.", _Boom())
    # Heuristic recovered.
    assert any("always" in r.rule_text.lower() for r in rules)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def test_rules_to_jsonl_round_trips():
    rules = [
        ExtractedRule(
            rule_text="Never trade on tilt.",
            preconditions=[],
            source="Lefevre",
            confidence=0.9,
            method="heuristic",
        )
    ]
    jsonl = rules_to_jsonl(rules)
    parsed = [json.loads(line) for line in jsonl.strip().splitlines()]
    assert parsed[0]["rule_text"] == "Never trade on tilt."
    assert parsed[0]["source"] == "Lefevre"


def test_rules_to_jsonl_empty_is_empty():
    assert rules_to_jsonl([]) == ""
