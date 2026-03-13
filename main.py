import asyncio
import logging
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config import CHECK_INTERVAL_MINUTES, DAYS_AHEAD, LOG_LEVEL
from dedup import DedupTracker
from models import FlightResult
from notifier import (
    _escape_markdown_v2,
    get_chat_ids,
    notify_flights_to_chat,
    send_message,
    send_startup_message,
)
from scrapers import IsstaScraper

TZ = ZoneInfo("Asia/Jerusalem")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("justinflight")


def generate_dates() -> list[str]:
    """Return the next DAYS_AHEAD dates in YYYY-MM-DD format (Jerusalem timezone)."""
    today = datetime.now(TZ).date()
    return [(today + timedelta(days=d)).isoformat() for d in range(DAYS_AHEAD)]


async def run_check(dedup: DedupTracker, failure_counts: dict[str, int]) -> None:
    """Run a single check cycle across all scrapers."""
    dates = generate_dates()
    logger.info("Checking dates: %s", ", ".join(dates))

    scrapers = [
        IsstaScraper(),
    ]

    all_flights: list[FlightResult] = []

    for scraper in scrapers:
        name = scraper.airline_name
        try:
            logger.info("Running %s scraper...", name)
            flights = await scraper.search_flights(dates)
            logger.info("%s scraper returned %d flight(s)", name, len(flights))
            failure_counts[name] = 0
            all_flights.extend(flights)

        except Exception:
            logger.exception("%s scraper failed", name)
            failure_counts[name] = failure_counts.get(name, 0) + 1

            if failure_counts[name] == 5:
                logger.warning(
                    "%s scraper has failed %d consecutive times — sending alert",
                    name, failure_counts[name],
                )
                msg = _escape_markdown_v2(
                    f"Warning: {name} scraper has failed 5 consecutive times. "
                    "Check logs for details."
                )
                send_message(msg)

    if not all_flights:
        logger.info("No flights found this cycle")
        dedup.cleanup_old()
        return

    # Per-chat dedup: each chat gets flights it hasn't seen yet
    chat_ids = get_chat_ids()
    if not chat_ids:
        logger.warning("No chat IDs registered, skipping notifications")
        dedup.cleanup_old()
        return

    for chat_id in chat_ids:
        new_for_chat = [f for f in all_flights if dedup.is_new(f, chat_id)]
        if new_for_chat:
            logger.info(
                "Notifying chat %s about %d new flight(s)", chat_id, len(new_for_chat),
            )
            notify_flights_to_chat(new_for_chat, chat_id)
            for flight in new_for_chat:
                dedup.mark_notified(flight, chat_id)

    dedup.save()
    dedup.cleanup_old()


async def main() -> None:
    logger.info("JustInFlight bot starting up")
    send_startup_message()

    dedup = DedupTracker()
    failure_counts: dict[str, int] = {}

    while True:
        try:
            await run_check(dedup, failure_counts)
        except Exception:
            logger.exception("Unexpected error in check cycle")

        logger.info("Sleeping for %d minutes", CHECK_INTERVAL_MINUTES)
        await asyncio.sleep(CHECK_INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    asyncio.run(main())
