"""Signal delivery: Fidelity order tickets + Telegram alerts (Phase 4 add-on).

Turns a PaperSignal into (a) a clean, copy-paste **bracket order ticket** you can
key into Fidelity by hand, and (b) an optional **Telegram** push to your phone.

Still NO orders are placed anywhere — this only formats text and sends a message.
Fidelity has no public trading API, so execution stays manual by design.

Telegram is configured via env (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID). If those
aren't set, alerting is simply skipped — the scanner still logs signals.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

from .data import _load_dotenv
from .signals import PaperSignal
from .strategy import LONG

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def format_order_ticket(sig: PaperSignal) -> str:
    """A copy-paste Fidelity bracket order (One-Triggers-an-OCO).

    Long  -> BUY entry, protective SELL stop, SELL limit target.
    Short -> SELL SHORT entry, protective BUY-to-cover stop, BUY limit target.
    """
    is_long = sig.direction == LONG
    open_side = "BUY" if is_long else "SELL SHORT"
    close_side = "SELL" if is_long else "BUY TO COVER"
    detected = sig.emitted_at.replace("T", " ")[:16] + " UTC"

    return (
        f"ORB PAPER SIGNAL — {sig.asof_date}\n"
        f"{sig.symbol}  {sig.direction.upper()}   (app places NO order)\n"
        f"\n"
        f"Fidelity bracket (One-Triggers-an-OCO):\n"
        f"  1) {open_side} {sig.suggested_shares} {sig.symbol} — limit {sig.reference_entry:.2f}\n"
        f"  2) {close_side} stop-loss @ {sig.stop_level:.2f}\n"
        f"  3) {close_side} limit (target) @ {sig.target_level:.2f}\n"
        f"\n"
        f"Risk/share ${sig.risk_per_share:.2f}  •  OR {sig.or_low:.2f}–{sig.or_high:.2f}\n"
        f"Detected {detected}\n"
        f"⚠ Paper/education only — verify the price is still valid before placing."
    )


def telegram_configured() -> bool:
    _load_dotenv()
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def send_telegram(text: str, *, token: str | None = None, chat_id: str | None = None,
                  timeout: int = 15) -> bool:
    """Send one Telegram message. Returns True on success, False if unconfigured
    or the API rejects it. Never raises on a delivery failure."""
    _load_dotenv()
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False

    url = _TELEGRAM_API.format(token=token)
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted host)
            payload = json.loads(resp.read().decode("utf-8"))
            return bool(payload.get("ok"))
    except Exception:
        return False


def notify_signals(signals: list[PaperSignal]) -> int:
    """Send a Telegram ticket for each signal (if configured). Returns count sent."""
    if not signals or not telegram_configured():
        return 0
    sent = 0
    for sig in signals:
        if send_telegram(format_order_ticket(sig)):
            sent += 1
    return sent
