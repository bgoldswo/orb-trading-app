"""Helper to set up Telegram alerts.

Steps:
  1. In Telegram, message @BotFather -> /newbot -> copy the bot token.
  2. Put it in .env as TELEGRAM_BOT_TOKEN=...
  3. Send any message to your new bot (so it has a chat to reply to).
  4. Run:  python scripts/telegram_setup.py
     -> prints the chat id(s) that have messaged the bot. Put it in .env as
        TELEGRAM_CHAT_ID=...
  5. Run again -> sends a test message to confirm end-to-end.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

from orb.data import _load_dotenv
from orb.notify import send_telegram


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    _load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Set TELEGRAM_BOT_TOKEN in .env first (message @BotFather -> /newbot).")
        return 2

    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if chat_id:
        ok = send_telegram("✅ ORB alerts are wired up. You'll get signals here.")
        print("Test message sent." if ok else "Test send failed — check token/chat id.")
        return 0 if ok else 1

    # No chat id yet: discover it from recent updates.
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    with urllib.request.urlopen(url, timeout=15) as resp:  # noqa: S310
        data = json.loads(resp.read().decode("utf-8"))
    chats = {}
    for upd in data.get("result", []):
        msg = upd.get("message") or upd.get("channel_post") or {}
        chat = msg.get("chat") or {}
        if "id" in chat:
            chats[chat["id"]] = chat.get("username") or chat.get("title") or chat.get("first_name", "")
    if not chats:
        print("No chats found yet. Send a message to your bot in Telegram, then re-run.")
        return 1
    print("Found chat id(s) — add one to .env as TELEGRAM_CHAT_ID:")
    for cid, name in chats.items():
        print(f"  {cid}  ({name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
