import logging
import time

import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from models import FlightResult

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"


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


def send_message(text: str) -> None:
    """Send a single message via the Telegram Bot API.

    Handles HTTP 429 (rate limit) responses by sleeping for the
    retry_after duration indicated in the response and retrying once.
    """
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "MarkdownV2",
    }

    try:
        response = requests.post(TELEGRAM_API_URL, json=payload, timeout=30)

        if response.status_code == 429:
            retry_after = response.json().get("parameters", {}).get("retry_after", 5)
            logger.warning("Rate limited by Telegram API. Retrying after %s seconds.", retry_after)
            time.sleep(retry_after)
            response = requests.post(TELEGRAM_API_URL, json=payload, timeout=30)

        if response.status_code != 200:
            logger.error(
                "Failed to send Telegram message. Status: %s, Response: %s",
                response.status_code,
                response.text,
            )
        else:
            logger.info("Telegram message sent successfully.")

    except requests.RequestException as exc:
        logger.error("Error sending Telegram message: %s", exc)


def notify_flights(flights: list) -> None:
    """Format a list of FlightResult objects into a batched Telegram message and send it.

    Each flight is displayed as a clearly separated block with airline,
    flight number, date, time, price, and URL.
    """
    if not flights:
        logger.info("No flights to notify about.")
        return

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
    message = f"*{header}*\n\n" + "\n\n".join(blocks)

    send_message(message)


def send_startup_message() -> None:
    """Send a startup notification indicating the bot is running."""
    text = _escape_markdown_v2("JustInFlight bot started! Monitoring TLV->LCA flights.")
    send_message(text)
