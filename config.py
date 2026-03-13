import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Required settings
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")

# Optional — used only for migrating existing users on first run
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Optional settings with defaults
CHECK_INTERVAL_MINUTES = int(os.environ.get("CHECK_INTERVAL_MINUTES", 5))
DAYS_AHEAD = int(os.environ.get("DAYS_AHEAD", 7))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
DATA_DIR = os.environ.get("DATA_DIR", "/app/data")

TZ = ZoneInfo("Asia/Jerusalem")


def generate_rolling_dates() -> list[str]:
    """Return the next DAYS_AHEAD dates in YYYY-MM-DD format (Jerusalem timezone)."""
    today = datetime.now(TZ).date()
    return [(today + timedelta(days=d)).isoformat() for d in range(DAYS_AHEAD)]
