import json
import logging
import os
import time

import requests

from config import DATA_DIR, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from models import FlightResult

logger = logging.getLogger(__name__)

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
CHAT_IDS_FILE = os.path.join(DATA_DIR, "chat_ids.json")


def _load_chat_ids() -> set[str]:
    """Load known chat IDs from disk, seeded with TELEGRAM_CHAT_ID if set."""
    chat_ids: set[str] = set()
    if TELEGRAM_CHAT_ID:
        chat_ids.add(str(TELEGRAM_CHAT_ID))
    try:
        with open(CHAT_IDS_FILE) as f:
            data = json.load(f)
        if isinstance(data, list):
            chat_ids.update(str(cid) for cid in data)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return chat_ids


def _save_chat_ids(chat_ids: set[str]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CHAT_IDS_FILE, "w") as f:
        json.dump(sorted(chat_ids), f)


def _poll_new_chats() -> None:
    """Poll getUpdates to discover new chats that messaged the bot."""
    chat_ids = _load_chat_ids()
    before = len(chat_ids)

    try:
        resp = requests.get(f"{TELEGRAM_API}/getUpdates", timeout=10)
        resp.raise_for_status()
        updates = resp.json().get("result", [])
    except Exception:
        logger.exception("Failed to poll Telegram getUpdates")
        return

    max_update_id = None
    for update in updates:
        uid = update.get("update_id")
        if uid is not None:
            max_update_id = uid if max_update_id is None else max(max_update_id, uid)
        msg = update.get("message") or update.get("my_chat_member", {}).get("chat")
        if msg:
            chat = msg.get("chat", msg) if "chat" in msg else msg
            chat_id = chat.get("id")
            if chat_id:
                chat_ids.add(str(chat_id))

    # Acknowledge processed updates so they don't pile up
    if max_update_id is not None:
        try:
            requests.get(
                f"{TELEGRAM_API}/getUpdates",
                params={"offset": max_update_id + 1},
                timeout=10,
            )
        except Exception:
            pass

    if len(chat_ids) > before:
        logger.info(
            "Discovered %d new chat(s), total: %d",
            len(chat_ids) - before, len(chat_ids),
        )

    _save_chat_ids(chat_ids)


def _escape_markdown_v2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2 format."""
    special_chars = [
        "_", "*", "[", "]", "(", ")", "~", "`", ">",
        "#", "+", "-", "=", "|", "{", "}", ".", "!",
    ]
    escaped = str(text)
    for char in special_chars:
        escaped = escaped.replace(char, f"\\{char}")
    return escaped


def _send_to_chat(chat_id: str, text: str) -> None:
    """Send a message to a single chat. Handles rate limiting."""
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "MarkdownV2",
    }

    try:
        response = requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=30)

        if response.status_code == 429:
            retry_after = response.json().get("parameters", {}).get("retry_after", 5)
            logger.warning("Rate limited by Telegram API. Retrying after %s seconds.", retry_after)
            time.sleep(retry_after)
            response = requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=30)

        if response.status_code == 403:
            logger.warning("Bot blocked by chat %s, skipping", chat_id)
        elif response.status_code != 200:
            logger.error(
                "Failed to send to chat %s. Status: %s, Response: %s",
                chat_id, response.status_code, response.text,
            )

    except requests.RequestException as exc:
        logger.error("Error sending to chat %s: %s", chat_id, exc)


def send_message(text: str) -> None:
    """Send a message to all registered chats."""
    _poll_new_chats()
    chat_ids = _load_chat_ids()

    if not chat_ids:
        logger.warning("No chat IDs registered. No messages sent.")
        return

    logger.info("Sending message to %d chat(s)", len(chat_ids))
    for chat_id in chat_ids:
        _send_to_chat(chat_id, text)


def _format_flights_message(flights: list) -> str:
    """Format a list of FlightResult objects into a Telegram message."""
    blocks = []
    for flight in flights:
        airline = _escape_markdown_v2(flight.airline)
        date = _escape_markdown_v2(flight.date)

        lines = [f"*{airline}*"]
        if flight.flight_number:
            lines[0] = f"*{airline} \\- {_escape_markdown_v2(flight.flight_number)}*"
        lines.append(f"Date: {date}")
        if flight.departure_time:
            lines.append(f"Time: {_escape_markdown_v2(flight.departure_time)}")
        if flight.price:
            lines.append(f"Price: {_escape_markdown_v2(flight.price)}")
        if flight.seats_left:
            lines.append(f"Seats left: {_escape_markdown_v2(flight.seats_left)}")
        if flight.url:
            lines.append(f"Link: {_escape_markdown_v2(flight.url)}")

        blocks.append("\n".join(lines))

    header = _escape_markdown_v2("New flights found!")
    return f"*{header}*\n\n" + "\n\n".join(blocks)


def get_chat_ids() -> set[str]:
    """Poll for new chats and return all registered chat IDs."""
    _poll_new_chats()
    return _load_chat_ids()


def notify_flights_to_chat(flights: list, chat_id: str) -> None:
    """Send flight notifications to a specific chat."""
    if not flights:
        return
    message = _format_flights_message(flights)
    _send_to_chat(chat_id, message)


def notify_flights(flights: list) -> None:
    """Format a list of FlightResult objects into a Telegram message and send to all chats."""
    if not flights:
        logger.info("No flights to notify about.")
        return
    message = _format_flights_message(flights)
    send_message(message)


def send_startup_message() -> None:
    """Send a startup notification indicating the bot is running."""
    text = _escape_markdown_v2("JustInFlight bot started! Monitoring TLV->LCA flights.")
    send_message(text)
