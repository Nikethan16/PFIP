"""Unit tests for Telegram channel configuration (env-driven)."""

from __future__ import annotations

from pfip.ingest.news import telegram_telethon as T


def test_configured_channels_defaults(monkeypatch):
    monkeypatch.delenv("TELEGRAM_CHANNELS", raising=False)
    assert T._configured_channels() == T.DEFAULT_CHANNELS


def test_configured_channels_from_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHANNELS", "@foo, bar , @baz")
    assert T._configured_channels() == ("foo", "bar", "baz")


def test_configured_channels_blank_falls_back(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHANNELS", "   ")
    assert T._configured_channels() == T.DEFAULT_CHANNELS
