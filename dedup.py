import json
import logging
import os
from datetime import datetime, timedelta, timezone

from config import DATA_DIR
from models import FlightResult

logger = logging.getLogger(__name__)


class DedupTracker:
    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self._filepath = os.path.join(DATA_DIR, "notified_flights.json")
        self._notified: dict[str, str] = {}
        self._load()

    def _load(self):
        if not os.path.exists(self._filepath):
            logger.info("No existing dedup file found at %s, starting fresh", self._filepath)
            return
        try:
            with open(self._filepath, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._notified = data
                logger.info("Loaded %d dedup entries from %s", len(self._notified), self._filepath)
            else:
                logger.warning("Dedup file %s did not contain a dict, starting fresh", self._filepath)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load dedup file %s: %s, starting fresh", self._filepath, e)

    def _save(self):
        try:
            with open(self._filepath, "w") as f:
                json.dump(self._notified, f, indent=2)
        except OSError as e:
            logger.error("Failed to save dedup file %s: %s", self._filepath, e)

    def is_new(self, flight: FlightResult) -> bool:
        return flight.dedup_key not in self._notified

    def mark_notified(self, flight: FlightResult):
        self._notified[flight.dedup_key] = datetime.now(timezone.utc).isoformat()
        self._save()

    def cleanup_old(self):
        cutoff = datetime.now(timezone.utc) - timedelta(days=8)
        before_count = len(self._notified)
        self._notified = {
            key: ts
            for key, ts in self._notified.items()
            if datetime.fromisoformat(ts) >= cutoff
        }
        removed = before_count - len(self._notified)
        if removed:
            logger.info("Cleaned up %d old dedup entries", removed)
        self._save()
