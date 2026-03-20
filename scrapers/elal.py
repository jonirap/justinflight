import logging
from datetime import datetime
from typing import Dict, List, Optional

import requests

from config import TZ
from models import FlightResult
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

API_URL = "https://www.elal.com/api/SeatAvailability/lang/eng/flights"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://www.elal.com/eng/seat-availability",
}

# Cache the API response so we only call once per scrape cycle
# (the endpoint returns all destinations in a single response).
_cache: Dict[str, object] = {"data": None, "fetched_at": None}


def _fetch_flights() -> Optional[dict]:
    """Fetch seat availability data from El Al, with per-cycle caching."""
    now = datetime.now(TZ)

    # Reuse cached response if fetched in the same minute
    if (
        _cache["data"] is not None
        and _cache["fetched_at"] is not None
        and (now - _cache["fetched_at"]).total_seconds() < 120
    ):
        return _cache["data"]

    try:
        resp = requests.get(API_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        logger.exception("Failed to fetch El Al seat availability API")
        return None

    if not isinstance(data, dict) or data.get("responseCode") != 0:
        logger.warning("El Al API returned unexpected response: %s", str(data)[:200])
        return None

    _cache["data"] = data
    _cache["fetched_at"] = now
    logger.info("Fetched El Al seat availability (%d destinations from Israel)",
                len(data.get("flightsFromIsrael", [])))
    return data


def _build_date_map(date_range: dict) -> Dict[str, str]:
    """Map DD.MM date strings from the API to YYYY-MM-DD ISO format.

    The API returns dates like '19.03' without the year. We resolve the
    year using the current date in Jerusalem timezone.
    """
    now = datetime.now(TZ)
    current_year = now.year
    result = {}
    for dd_mm in date_range.get("dates", []):
        try:
            # Try current year first
            dt = datetime.strptime(f"{dd_mm}.{current_year}", "%d.%m.%Y")
            # If the date is more than 30 days in the past, it's next year
            if (now.date() - dt.date()).days > 30:
                dt = dt.replace(year=current_year + 1)
            result[dd_mm] = dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return result


class ElAlScraper(BaseScraper):
    """Scrape El Al seat availability via their public JSON API.

    El Al publishes a seat availability page at elal.com/eng/seat-availability
    backed by a public API that returns all flights from/to Israel with seat
    counts for the next ~8 days. No authentication is needed.
    """

    airline_name = "El Al"

    async def search_flights(self, dates: List[str]) -> List[FlightResult]:
        results: List[FlightResult] = []

        data = _fetch_flights()
        if not data:
            return results

        date_map = _build_date_map(data.get("dateRange", {}))
        target_dates = set(dates)

        for group in data.get("flightsFromIsrael", []):
            dest_code = group.get("origin", "").upper()
            if dest_code != self.destination:
                continue

            for flight in group.get("flights", []):
                flight_number = flight.get("flightNumber")
                dep_time = flight.get("segmentDepTime")
                origin = flight.get("routeFrom", "TLV").upper()

                for fd in flight.get("flightsDates", []):
                    seat_count = fd.get("seatCount", 0)
                    if not seat_count or seat_count <= 0:
                        continue

                    dd_mm = fd.get("flightsDate", "")
                    date_iso = date_map.get(dd_mm)
                    if not date_iso or date_iso not in target_dates:
                        continue

                    result = FlightResult(
                        airline="El Al",
                        origin=origin,
                        destination=self.destination,
                        date=date_iso,
                        departure_time=dep_time,
                        flight_number=flight_number,
                        seats_left=str(seat_count),
                        url="https://www.elal.com/eng/seat-availability",
                    )
                    results.append(result)
                    logger.info(
                        "Found El Al flight: %s %s->%s %s dep %s seats %s",
                        flight_number, origin, self.destination,
                        date_iso, dep_time, seat_count,
                    )

        logger.info("El Al scraper finished for %s. Found %d flights",
                     self.destination, len(results))
        return results
