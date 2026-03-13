import json
import logging
import os
from datetime import datetime, timedelta, timezone

from config import DATA_DIR
from models import FlightResult

logger = logging.getLogger(__name__)


class DedupTracker:
    """Per-chat dedup: tracks which flights have been sent to which chat."""

    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self._filepath = os.path.join(DATA_DIR, "notified_flights.json")
        # {chat_id: {dedup_key: timestamp}}
        self._notified: dict[str, dict[str, str]] = {}
        self._load()

    def _load(self):
        if not os.path.exists(self._filepath):
            logger.info("No existing dedup file found at %s, starting fresh", self._filepath)
            return
        try:
            with open(self._filepath, "r") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                logger.warning("Dedup file did not contain a dict, starting fresh")
                return
            # Detect old global format: {dedup_key: timestamp_string}
            # vs new per-chat format: {chat_id: {dedup_key: timestamp}}
            first_val = next(iter(data.values()), None) if data else None
            if isinstance(first_val, str):
                # Old global format — migrate: we can't know which chats saw
                # these, so just drop them. New chats will get current flights.
                logger.info("Migrating old global dedup format, resetting")
                self._notified = {}
            else:
                self._notified = data
                total = sum(len(v) for v in self._notified.values())
                logger.info(
                    "Loaded dedup entries for %d chat(s) (%d total) from %s",
                    len(self._notified), total, self._filepath,
                )
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load dedup file %s: %s, starting fresh", self._filepath, e)

    def _save(self):
        try:
            with open(self._filepath, "w") as f:
                json.dump(self._notified, f, indent=2)
        except OSError as e:
            logger.error("Failed to save dedup file %s: %s", self._filepath, e)

    def is_new(self, flight: FlightResult, chat_id: str) -> bool:
        return flight.dedup_key not in self._notified.get(chat_id, {})

    def mark_notified(self, flight: FlightResult, chat_id: str):
        if chat_id not in self._notified:
            self._notified[chat_id] = {}
        self._notified[chat_id][flight.dedup_key] = datetime.now(timezone.utc).isoformat()

    def save(self):
        self._save()

    def cleanup_old(self):
        cutoff = datetime.now(timezone.utc) - timedelta(days=8)
        total_removed = 0
        for chat_id in list(self._notified):
            before = len(self._notified[chat_id])
            self._notified[chat_id] = {
                key: ts
                for key, ts in self._notified[chat_id].items()
                if datetime.fromisoformat(ts) >= cutoff
            }
            total_removed += before - len(self._notified[chat_id])
            if not self._notified[chat_id]:
                del self._notified[chat_id]
        if total_removed:
            logger.info("Cleaned up %d old dedup entries", total_removed)
        self._save()
