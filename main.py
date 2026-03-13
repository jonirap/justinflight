import asyncio
import logging
import sys

from config import CHECK_INTERVAL_MINUTES, LOG_LEVEL, generate_rolling_dates
from dedup import DedupTracker
from models import FlightResult
from notifier import escape_markdown_v2, notify_flights_to_chat, send_to_chat
from preferences import UserPreferences
from scrapers import IsstaScraper

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("justinflight")


def _scrape_destination(dest: str, dates: list[str]) -> list[FlightResult]:
    """Run scraper synchronously (called via asyncio.to_thread)."""
    scraper = IsstaScraper(dest)
    # search_flights is declared async but uses sync requests internally,
    # so we run it in a thread. Call the underlying sync logic directly.
    import asyncio
    return asyncio.run(scraper.search_flights(dates))


async def run_check(
    preferences: UserPreferences,
    dedup: DedupTracker,
    failure_counts: dict[str, int],
) -> None:
    """Run a single check cycle across all user-subscribed destinations."""
    rolling_dates = generate_rolling_dates()
    wanted_dests = preferences.get_all_wanted_destinations()

    if not wanted_dests:
        logger.info("No destinations subscribed by any user, skipping check")
        return

    logger.info("Checking %d destination(s): %s", len(wanted_dests), ", ".join(sorted(wanted_dests)))

    # Scrape each destination (in a thread to avoid blocking the event loop)
    dest_flights: dict[str, list[FlightResult]] = {}
    for dest in sorted(wanted_dests):
        scraper_key = f"Issta-{dest}"
        try:
            # Compute union of dates across all users wanting this destination
            users = preferences.get_users_for_destination(dest)
            all_dates: set[str] = set()
            for uid in users:
                all_dates.update(preferences.get_dates_for_user(uid, rolling_dates))
            dates = sorted(all_dates)

            if not dates:
                continue

            logger.info("Running scraper for %s with %d date(s)", dest, len(dates))
            flights = await asyncio.to_thread(_scrape_destination, dest, dates)
            logger.info("%s returned %d flight(s)", scraper_key, len(flights))
            dest_flights[dest] = flights
            failure_counts[scraper_key] = 0

        except Exception:
            logger.exception("Scraper failed for %s", dest)
            failure_counts[scraper_key] = failure_counts.get(scraper_key, 0) + 1

            if failure_counts[scraper_key] == 5:
                logger.warning(
                    "%s scraper has failed 5 consecutive times", scraper_key,
                )
                # Notify all users subscribed to this destination
                users = preferences.get_users_for_destination(dest)
                msg = escape_markdown_v2(
                    f"Warning: scraper for {dest} has failed 5 consecutive times. "
                    "Check logs for details."
                )
                for uid in users:
                    await asyncio.to_thread(send_to_chat, uid, msg)

    # Per-user notification with dedup
    all_chat_ids = preferences.get_all_chat_ids()
    for chat_id in all_chat_ids:
        user_prefs = preferences.get_user_prefs(chat_id)
        if not user_prefs:
            continue
        user_dests = user_prefs.get("destinations", [])
        user_dates = set(preferences.get_dates_for_user(chat_id, rolling_dates))

        # Collect flights matching this user's destinations and dates
        user_flights = []
        for dest in user_dests:
            for flight in dest_flights.get(dest, []):
                if flight.date in user_dates:
                    user_flights.append(flight)

        # Filter through dedup
        new_flights = [f for f in user_flights if dedup.is_new(f, chat_id)]
        if new_flights:
            logger.info(
                "Notifying chat %s about %d new flight(s)", chat_id, len(new_flights),
            )
            await asyncio.to_thread(notify_flights_to_chat, new_flights, chat_id)
            for flight in new_flights:
                dedup.mark_notified(flight, chat_id)

    dedup.save()
    dedup.cleanup_old()


async def main() -> None:
    logger.info("JustInFlight bot starting up")

    preferences = UserPreferences()
    dedup = DedupTracker()
    failure_counts: dict[str, int] = {}

    # Import here to avoid circular imports at module level
    from bot import create_bot_app

    bot_app = create_bot_app(preferences, dedup)
    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling()

    logger.info("Bot polling started, entering scraper loop")

    try:
        while True:
            try:
                await run_check(preferences, dedup, failure_counts)
            except Exception:
                logger.exception("Unexpected error in check cycle")

            logger.info("Sleeping for %d minutes", CHECK_INTERVAL_MINUTES)
            await asyncio.sleep(CHECK_INTERVAL_MINUTES * 60)
    finally:
        logger.info("Shutting down bot...")
        await bot_app.updater.stop()
        await bot_app.stop()
        await bot_app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
