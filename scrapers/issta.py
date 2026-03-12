import logging
import re
from datetime import datetime
from html.parser import HTMLParser
from typing import List

import requests

from models import FlightResult
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

RESULTS_URL = (
    "https://www.issta.co.il/flights/results.aspx"
    "?route=1&padt=1&pchd=0&pinf=0&pyou=0"
    "&dport=tlv&aport=lca&dtime=-1&class=y&flighttype=0"
)

CALENDAR_URL = (
    "https://external.issta.co.il/products/api/flights/calendardates"
    "?destinationCode=LCA&from=null"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
}

WANTED_AIRLINES = {"israir", "arkia", "el al"}


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.texts: list[str] = []

    def handle_data(self, data: str):
        d = data.strip()
        if d:
            self.texts.append(d)


class IsstaScraper(BaseScraper):
    """Scrape Issta.co.il search results for one-way TLV->LCA flights.

    The Issta results page is server-side rendered and returns full flight
    data in the HTML without requiring JavaScript execution. We use the
    calendar API to find dates with availability, then load the results
    page for each date and parse the HTML.
    """

    airline_name = "Issta"

    async def search_flights(self, dates: List[str]) -> List[FlightResult]:
        results: List[FlightResult] = []

        # First, check which of our target dates have flights available
        available_dates = self._get_available_dates()
        target_dates = set(dates)
        dates_to_search = sorted(target_dates & available_dates)

        if not dates_to_search:
            logger.info(
                "No flights available on Issta for any of the %d target dates",
                len(dates),
            )
            return results

        logger.info(
            "Issta calendar shows flights on %d of %d target dates: %s",
            len(dates_to_search), len(dates), ", ".join(dates_to_search),
        )

        for date in dates_to_search:
            try:
                flights = self._search_date(date)
                results.extend(flights)
            except Exception:
                logger.exception("Error searching Issta for %s", date)

        # Deduplicate
        seen = set()
        unique = []
        for f in results:
            if f.dedup_key not in seen:
                seen.add(f.dedup_key)
                unique.append(f)

        logger.info("Issta scraper finished. Total: %d unique flights", len(unique))
        return unique

    def _get_available_dates(self) -> set[str]:
        """Query Issta calendar API to find dates with flight availability."""
        try:
            resp = requests.get(CALENDAR_URL, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.exception("Failed to fetch Issta calendar")
            return set()

        dates = set()
        for entry in data.get("Dates", []):
            # Date format: "2026-03-20T00:00:00"
            raw = entry.get("Date", "")
            if raw:
                dates.add(raw[:10])  # YYYY-MM-DD
        return dates

    def _search_date(self, date_iso: str) -> List[FlightResult]:
        """Load Issta results page for a specific date and parse flights."""
        # Convert YYYY-MM-DD to DD/MM/YYYY for URL
        dt = datetime.strptime(date_iso, "%Y-%m-%d")
        fdate = dt.strftime("%d/%m/%Y")

        url = f"{RESULTS_URL}&fdate={fdate}"
        logger.info("Fetching Issta results for %s", date_iso)

        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        html = resp.text

        return self._parse_results_html(html, date_iso, url)

    def _parse_results_html(
        self, html: str, date_iso: str, url: str,
    ) -> List[FlightResult]:
        """Parse the Issta results HTML to extract flight information."""
        results: List[FlightResult] = []

        # Split HTML by flight result items (literal string split)
        blocks = html.split('class="list-item result')

        for block in blocks[1:]:  # skip first (before any result)
            parser = _TextExtractor()
            try:
                parser.feed(block[:8000])
            except Exception:
                continue

            texts = parser.texts
            if len(texts) < 3:
                continue

            airline = None
            dep_time = None
            price = None

            for i, t in enumerate(texts):
                # Find airline name (first occurrence only)
                if airline is None and any(
                    a in t.lower()
                    for a in ["israir", "arkia", "el al", "elal"]
                ):
                    airline = t

                # Find departure time (HH:MM pattern, first occurrence)
                # Handle "(+1)" marker before time for overnight flights
                if dep_time is None and re.match(r"^\d{1,2}:\d{2}$", t):
                    dep_time = t

                # Find price: look for "סה"כ לתשלום:" followed by "$NNN"
                if price is None and re.match(r"^\$\d+", t):
                    price = t

            # Also try: "$" as separate token followed by number
            if price is None:
                for i, t in enumerate(texts):
                    if t == "$" and i + 1 < len(texts) and texts[i + 1].isdigit():
                        price = f"${texts[i + 1]}"
                        break

            if not airline:
                continue

            # Filter: only wanted airlines
            airline_lower = airline.lower()
            if not any(wanted in airline_lower for wanted in WANTED_AIRLINES):
                continue

            # Normalize airline name
            if "israir" in airline_lower:
                airline = "Israir"
            elif "arkia" in airline_lower:
                airline = "Arkia"
            elif "el al" in airline_lower or "elal" in airline_lower:
                airline = "El Al"

            flight = FlightResult(
                airline=airline,
                origin="TLV",
                destination="LCA",
                date=date_iso,
                departure_time=dep_time,
                price=price,
                flight_number=None,
                url=url,
            )
            results.append(flight)
            logger.info(
                "Found %s flight: %s dep %s price %s",
                airline, date_iso, dep_time, price,
            )

        return results
