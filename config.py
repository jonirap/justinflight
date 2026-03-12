import os

# Required settings
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")

TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
if not TELEGRAM_CHAT_ID:
    raise ValueError("TELEGRAM_CHAT_ID environment variable is required")

# Optional settings with defaults
CHECK_INTERVAL_MINUTES = int(os.environ.get("CHECK_INTERVAL_MINUTES", 5))
DAYS_AHEAD = int(os.environ.get("DAYS_AHEAD", 7))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
