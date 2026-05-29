"""Fidelity order tickets + Telegram sender (mocked — no network, no orders)."""

from __future__ import annotations

import orb.notify as notify
from orb.signals import PaperSignal


def _signal(direction="long", shares=518):
    return PaperSignal(
        emitted_at="2026-05-29T19:14:00+00:00",
        asof_date="2026-05-29",
        symbol="SPY",
        direction=direction,
        or_high=757.00,
        or_low=755.57,
        confirmation_ts="2026-05-29T09:45:00-04:00",
        entry_ts="2026-05-29T09:46:00-04:00",
        reference_entry=757.50,
        stop_level=755.57,
        target_level=761.36,
        risk_per_share=1.93,
        suggested_shares=shares,
    )


def test_ticket_is_a_long_bracket_with_levels():
    t = notify.format_order_ticket(_signal())
    assert "SPY  LONG" in t
    assert "BUY 518 SPY" in t
    assert "757.50" in t and "755.57" in t and "761.36" in t  # entry/stop/target
    assert "stop-loss" in t and "target" in t
    assert "NO order" in t and "Paper" in t  # safety wording present


def test_ticket_flips_sides_for_short():
    t = notify.format_order_ticket(_signal(direction="short"))
    assert "SELL SHORT" in t
    assert "BUY TO COVER" in t  # protective + target legs cover the short


def test_send_telegram_builds_correct_request(monkeypatch):
    captured = {}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"ok": true}'

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["data"] = req.data.decode("utf-8")
        return _Resp()

    monkeypatch.setattr(notify.urllib.request, "urlopen", fake_urlopen)
    ok = notify.send_telegram("hello", token="T0K", chat_id="999")
    assert ok is True
    assert "/botT0K/sendMessage" in captured["url"]
    assert "chat_id=999" in captured["data"]
    assert "hello" in captured["data"]


def test_send_telegram_unconfigured_returns_false(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setattr(notify, "_load_dotenv", lambda *a, **k: None)  # don't read .env
    assert notify.send_telegram("x") is False
    assert notify.notify_signals([_signal()]) == 0


def test_send_telegram_swallows_network_errors(monkeypatch):
    def boom(req, timeout=0):
        raise OSError("network down")
    monkeypatch.setattr(notify.urllib.request, "urlopen", boom)
    # Delivery failure must never raise — just report False.
    assert notify.send_telegram("x", token="T", chat_id="1") is False
