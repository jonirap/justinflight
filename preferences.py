import asyncio
import json
import logging
import os
from datetime import datetime, timezone

from config import DATA_DIR, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

PREFS_FILE = os.path.join(DATA_DIR, "user_preferences.json")
CHAT_IDS_FILE = os.path.join(DATA_DIR, "chat_ids.json")


class UserPreferences:
    """JSON-file-backed per-user preference store."""

    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self._lock = asyncio.Lock()
        # {chat_id_str: {destinations: [...], dates: [...], date_mode: str, created_at: str}}
        self._prefs: dict[str, dict] = {}
        self._load()

    def _default_user(self) -> dict:
        return {
            "destinations": ["LCA"],
            "date_mode": "rolling",
            "dates": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def _load(self):
        # Try loading existing preferences
        if os.path.exists(PREFS_FILE):
            try:
                with open(PREFS_FILE) as f:
                    self._prefs = json.load(f)
                logger.info(
                    "Loaded preferences for %d user(s)", len(self._prefs)
                )
                return
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load preferences: %s", e)

        # Migrate from old chat_ids.json if it exists
        self._migrate_from_chat_ids()

    def _migrate_from_chat_ids(self):
        chat_ids: set[str] = set()
        if TELEGRAM_CHAT_ID:
            chat_ids.add(str(TELEGRAM_CHAT_ID))
        if os.path.exists(CHAT_IDS_FILE):
            try:
                with open(CHAT_IDS_FILE) as f:
                    data = json.load(f)
                if isinstance(data, list):
                    chat_ids.update(str(cid) for cid in data)
            except (json.JSONDecodeError, OSError):
                pass

        if chat_ids:
            logger.info("Migrating %d chat(s) from chat_ids.json", len(chat_ids))
            for cid in chat_ids:
                self._prefs[cid] = self._default_user()
            self._save()

    def _save(self):
        try:
            with open(PREFS_FILE, "w") as f:
                json.dump(self._prefs, f, indent=2)
        except OSError as e:
            logger.error("Failed to save preferences: %s", e)

    async def ensure_user(self, chat_id: str) -> dict:
        async with self._lock:
            chat_id = str(chat_id)
            if chat_id not in self._prefs:
                self._prefs[chat_id] = self._default_user()
                self._save()
            return self._prefs[chat_id]

    async def add_destination(self, chat_id: str, code: str) -> bool:
        """Add a destination. Returns True if added, False if already present."""
        async with self._lock:
            chat_id = str(chat_id)
            if chat_id not in self._prefs:
                self._prefs[chat_id] = self._default_user()
            dests = self._prefs[chat_id]["destinations"]
            if code in dests:
                return False
            dests.append(code)
            self._save()
            return True

    async def remove_destination(self, chat_id: str, code: str) -> bool:
        """Remove a destination. Returns True if removed, False if not found."""
        async with self._lock:
            chat_id = str(chat_id)
            if chat_id not in self._prefs:
                return False
            dests = self._prefs[chat_id]["destinations"]
            if code not in dests:
                return False
            dests.remove(code)
            self._save()
            return True

    async def set_dates(self, chat_id: str, dates: list[str]):
        async with self._lock:
            chat_id = str(chat_id)
            if chat_id not in self._prefs:
                self._prefs[chat_id] = self._default_user()
            self._prefs[chat_id]["dates"] = dates
            self._prefs[chat_id]["date_mode"] = "specific"
            self._save()

    async def set_rolling_mode(self, chat_id: str):
        async with self._lock:
            chat_id = str(chat_id)
            if chat_id not in self._prefs:
                self._prefs[chat_id] = self._default_user()
            self._prefs[chat_id]["date_mode"] = "rolling"
            self._prefs[chat_id]["dates"] = []
            self._save()

    def get_user_prefs(self, chat_id: str) -> dict | None:
        return self._prefs.get(str(chat_id))

    def get_dates_for_user(self, chat_id: str, rolling_dates: list[str]) -> list[str]:
        """Return the dates a user wants to monitor."""
        prefs = self._prefs.get(str(chat_id))
        if not prefs:
            return rolling_dates
        if prefs["date_mode"] == "rolling":
            return rolling_dates
        return prefs.get("dates", [])

    def get_all_wanted_destinations(self) -> set[str]:
        """Union of all users' subscribed destinations."""
        result = set()
        for prefs in self._prefs.values():
            result.update(prefs.get("destinations", []))
        return result

    def get_users_for_destination(self, code: str) -> list[str]:
        """Return chat_ids subscribed to a destination."""
        return [
            cid for cid, prefs in self._prefs.items()
            if code in prefs.get("destinations", [])
        ]

    def get_all_chat_ids(self) -> list[str]:
        return list(self._prefs.keys())

    async def clear_destinations(self, chat_id: str):
        async with self._lock:
            chat_id = str(chat_id)
            if chat_id in self._prefs:
                self._prefs[chat_id]["destinations"] = []
                self._save()
