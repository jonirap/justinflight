import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import DAYS_AHEAD, TELEGRAM_BOT_TOKEN, TZ, generate_rolling_dates
from dedup import DedupTracker
from destinations import DESTINATIONS, destination_display, find_destination
from notifier import escape_markdown_v2, format_flights_message
from preferences import UserPreferences
from scrapers import IsstaScraper

logger = logging.getLogger(__name__)


def _scrape_sync(dest: str, dates: list[str]):
    """Run scraper synchronously (for use with asyncio.to_thread)."""
    import asyncio as _asyncio
    scraper = IsstaScraper(dest)
    return _asyncio.run(scraper.search_flights(dates))


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prefs: UserPreferences = context.bot_data["preferences"]
    chat_id = str(update.effective_chat.id)
    await prefs.ensure_user(chat_id)
    await update.message.reply_text(
        "Welcome to JustInFlight!\n\n"
        "I monitor flight availability from TLV (Tel Aviv) "
        "for Israeli airlines (Israir, Arkia, El Al).\n\n"
        "You're subscribed to: Larnaca (LCA) by default.\n\n"
        "Commands:\n"
        "/destinations - list available destinations\n"
        "/subscribe <city> - add a destination\n"
        "/unsubscribe <city> - remove a destination\n"
        "/dates - show your date settings\n"
        "/dates rolling - monitor next N days\n"
        "/dates 20/03 25/03 - set specific dates\n"
        "/mysettings - show all preferences\n"
        "/status - check flights now\n"
        "/stop - stop all notifications\n"
        "/help - show this message"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "JustInFlight - TLV Flight Monitor\n\n"
        "/start - register & get started\n"
        "/destinations - list available destinations\n"
        "/subscribe <city> - add a destination\n"
        "/unsubscribe <city> - remove a destination\n"
        "/dates - show your date settings\n"
        "/dates rolling - switch to rolling mode\n"
        "/dates 20/03 25/03 - set specific dates\n"
        "/mysettings - show all preferences\n"
        "/status - check flights now\n"
        "/stop - stop all notifications\n"
        "/help - show this message"
    )


async def cmd_destinations(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["Available destinations from TLV:\n"]
    by_country: dict[str, list[str]] = {}
    for code, info in DESTINATIONS.items():
        country = info["country"]
        by_country.setdefault(country, []).append(f"  {info['name']} ({code})")
    for country in sorted(by_country):
        lines.append(f"{country}:")
        lines.extend(sorted(by_country[country]))
    lines.append("\nUse /subscribe <city> to add one.")
    await update.message.reply_text("\n".join(lines))


async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prefs: UserPreferences = context.bot_data["preferences"]
    chat_id = str(update.effective_chat.id)
    await prefs.ensure_user(chat_id)

    if not context.args:
        await update.message.reply_text("Usage: /subscribe <city or IATA code>\nExample: /subscribe Larnaca")
        return

    query = " ".join(context.args)
    code = find_destination(query)
    if not code:
        await update.message.reply_text(f"Unknown destination: {query}\nUse /destinations to see the list.")
        return

    added = await prefs.add_destination(chat_id, code)
    if added:
        await update.message.reply_text(f"Subscribed to {destination_display(code)}!")
    else:
        await update.message.reply_text(f"Already subscribed to {destination_display(code)}.")


async def cmd_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prefs: UserPreferences = context.bot_data["preferences"]
    chat_id = str(update.effective_chat.id)

    if not context.args:
        await update.message.reply_text("Usage: /unsubscribe <city or IATA code>")
        return

    query = " ".join(context.args)
    code = find_destination(query)
    if not code:
        await update.message.reply_text(f"Unknown destination: {query}\nUse /destinations to see the list.")
        return

    removed = await prefs.remove_destination(chat_id, code)
    if removed:
        await update.message.reply_text(f"Unsubscribed from {destination_display(code)}.")
    else:
        await update.message.reply_text(f"You weren't subscribed to {destination_display(code)}.")


async def cmd_dates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prefs: UserPreferences = context.bot_data["preferences"]
    chat_id = str(update.effective_chat.id)
    await prefs.ensure_user(chat_id)

    if not context.args:
        # Show current settings
        user_prefs = prefs.get_user_prefs(chat_id)
        mode = user_prefs["date_mode"]
        if mode == "rolling":
            await update.message.reply_text(
                f"Date mode: rolling (next {DAYS_AHEAD} days)\n\n"
                "Use /dates rolling to keep this\n"
                "Use /dates 20/03 25/03 to set specific dates"
            )
        else:
            dates = user_prefs.get("dates", [])
            dates_str = ", ".join(dates) if dates else "none"
            await update.message.reply_text(
                f"Date mode: specific\nDates: {dates_str}\n\n"
                "Use /dates rolling to switch to rolling\n"
                "Use /dates 20/03 25/03 to update dates"
            )
        return

    if context.args[0].lower() == "rolling":
        await prefs.set_rolling_mode(chat_id)
        await update.message.reply_text(f"Switched to rolling mode (next {DAYS_AHEAD} days).")
        return

    # Parse specific dates (DD/MM format, auto-detect year)
    today = datetime.now(TZ).date()
    parsed_dates = []
    for arg in context.args:
        try:
            parts = arg.split("/")
            if len(parts) == 2:
                day, month = int(parts[0]), int(parts[1])
                # Use current year, bump to next year if date is in the past
                year = today.year
                candidate = datetime(year, month, day).date()
                if candidate < today:
                    candidate = datetime(year + 1, month, day).date()
                parsed_dates.append(candidate.isoformat())
            elif len(parts) == 3:
                day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
                if year < 100:
                    year += 2000
                parsed_dates.append(datetime(year, month, day).date().isoformat())
            else:
                await update.message.reply_text(f"Invalid date format: {arg}. Use DD/MM or DD/MM/YYYY.")
                return
        except ValueError:
            await update.message.reply_text(f"Invalid date: {arg}. Use DD/MM or DD/MM/YYYY.")
            return

    await prefs.set_dates(chat_id, sorted(parsed_dates))
    dates_str = ", ".join(sorted(parsed_dates))
    await update.message.reply_text(f"Monitoring specific dates: {dates_str}")


async def cmd_mysettings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prefs: UserPreferences = context.bot_data["preferences"]
    chat_id = str(update.effective_chat.id)
    await prefs.ensure_user(chat_id)

    user_prefs = prefs.get_user_prefs(chat_id)
    dests = user_prefs.get("destinations", [])
    dests_str = ", ".join(destination_display(d) for d in dests) if dests else "none"

    mode = user_prefs["date_mode"]
    if mode == "rolling":
        dates_str = f"Rolling (next {DAYS_AHEAD} days)"
    else:
        dates = user_prefs.get("dates", [])
        dates_str = ", ".join(dates) if dates else "none set"

    await update.message.reply_text(
        f"Your settings:\n\n"
        f"Destinations: {dests_str}\n"
        f"Dates: {dates_str}"
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prefs: UserPreferences = context.bot_data["preferences"]
    chat_id = str(update.effective_chat.id)
    await prefs.ensure_user(chat_id)

    user_prefs = prefs.get_user_prefs(chat_id)
    dests = user_prefs.get("destinations", [])
    if not dests:
        await update.message.reply_text("You have no destinations. Use /subscribe <city> first.")
        return

    rolling = generate_rolling_dates()
    dates = prefs.get_dates_for_user(chat_id, rolling)
    if not dates:
        await update.message.reply_text("No dates to check. Use /dates to configure.")
        return

    dests_str = ", ".join(destination_display(d) for d in dests)
    await update.message.reply_text(f"Checking flights to {dests_str}...")

    all_flights = []
    for dest in dests:
        try:
            flights = await asyncio.to_thread(_scrape_sync, dest, dates)
            all_flights.extend(flights)
        except Exception:
            logger.exception("Status check failed for %s", dest)

    if not all_flights:
        await update.message.reply_text("No flights found for your destinations and dates.")
        return

    message = format_flights_message(all_flights)
    await update.message.reply_text(message, parse_mode="MarkdownV2")


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prefs: UserPreferences = context.bot_data["preferences"]
    chat_id = str(update.effective_chat.id)
    await prefs.clear_destinations(chat_id)
    await update.message.reply_text(
        "All destinations cleared. You won't receive notifications.\n"
        "Use /subscribe <city> to start again."
    )


def create_bot_app(preferences: UserPreferences, dedup: DedupTracker) -> Application:
    """Create and configure the Telegram bot application."""
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.bot_data["preferences"] = preferences
    app.bot_data["dedup"] = dedup

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("destinations", cmd_destinations))
    app.add_handler(CommandHandler("subscribe", cmd_subscribe))
    app.add_handler(CommandHandler("unsubscribe", cmd_unsubscribe))
    app.add_handler(CommandHandler("dates", cmd_dates))
    app.add_handler(CommandHandler("mysettings", cmd_mysettings))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("stop", cmd_stop))

    return app
