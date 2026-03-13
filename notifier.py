import logging
import time

import requests

from config import TELEGRAM_BOT_TOKEN
from destinations import destination_display
from models import FlightResult

logger = logging.getLogger(__name__)

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def escape_markdown_v2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2 format."""
    special_chars = [
        "_", "*", "[", "]", "(", ")", "~", "`", ">",
        "#", "+", "-", "=", "|", "{", "}", ".", "!",
    ]
    escaped = str(text)
    for char in special_chars:
        escaped = escaped.replace(char, f"\\{char}")
    return escaped


def send_to_chat(chat_id: str, text: str) -> None:
    """Send a MarkdownV2 message to a single chat. Handles rate limiting."""
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


def format_flights_message(flights: list[FlightResult], header: str | None = None) -> str:
    """Format a list of FlightResult objects into a Telegram MarkdownV2 message."""
    blocks = []
    for flight in flights:
        airline = escape_markdown_v2(flight.airline)
        date = escape_markdown_v2(flight.date)

        lines = [f"*{airline}*"]
        if flight.flight_number:
            lines[0] = f"*{airline} \\- {escape_markdown_v2(flight.flight_number)}*"
        dest_name = destination_display(flight.destination)
        lines.append(f"Route: TLV → {escape_markdown_v2(dest_name)}")
        lines.append(f"Date: {date}")
        if flight.departure_time:
            lines.append(f"Time: {escape_markdown_v2(flight.departure_time)}")
        if flight.price:
            lines.append(f"Price: {escape_markdown_v2(flight.price)}")
        if flight.seats_left:
            lines.append(f"Seats left: {escape_markdown_v2(flight.seats_left)}")
        if flight.url:
            lines.append(f"Link: {escape_markdown_v2(flight.url)}")

        blocks.append("\n".join(lines))

    if header is None:
        header = "New flights found\\!"
    else:
        header = escape_markdown_v2(header)
    return f"*{header}*\n\n" + "\n\n".join(blocks)


def notify_flights_to_chat(flights: list[FlightResult], chat_id: str) -> None:
    """Send flight notifications to a specific chat."""
    if not flights:
        return
    message = format_flights_message(flights)
    send_to_chat(chat_id, message)
