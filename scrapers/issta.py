import asyncio
import logging
import re
from datetime import datetime
from html.parser import HTMLParser
from typing import Dict, List, Optional

import requests
from curl_cffi import requests as cffi_requests
from playwright.async_api import async_playwright

from models import FlightResult
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

WANTED_AIRLINES = {"israir", "arkia", "el al", "airhaifa"}

ORIGINS = ["tlv", "hfa"]

STEALTH_JS = """
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
    if (parameter === 37445) return 'Intel Inc.';
    if (parameter === 37446) return 'Intel Iris OpenGL Engine';
    return getParameter.call(this, parameter);
};
Object.defineProperty(navigator, 'webdriver', { get: () => false });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', {
    get: () => ['he-IL', 'he', 'en-US', 'en'],
});
window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){} };
"""

CALENDAR_URL = (
    "https://external.issta.co.il/products/api/flights/calendardates"
)

CALENDAR_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
}


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.texts: list[str] = []

    def handle_data(self, data: str):
        d = data.strip()
        if d:
            self.texts.append(d)


async def _obtain_radware_cookies() -> Dict[str, str]:
    """Use headless Firefox to solve the Radware bot challenge and return cookies."""
    logger.info("Obtaining Radware cookies via headless Firefox...")
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:134.0) "
                "Gecko/20100101 Firefox/134.0"
            ),
            viewport={"width": 1920, "height": 1080},
            locale="he-IL",
            timezone_id="Asia/Jerusalem",
        )
        await context.add_init_script(STEALTH_JS)
        page = await context.new_page()

        # Load any Issta results page to trigger the challenge
        await page.goto(
            "https://www.issta.co.il/flights/results.aspx"
            "?route=1&padt=1&pchd=0&pinf=0&pyou=0"
            "&dport=tlv&aport=lca&dtime=-1&class=y&flighttype=0"
            "&fdate=01/01/2027",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        # Wait for the challenge JS to execute and set cookies
        await page.wait_for_timeout(15000)

        cookies = await context.cookies()
        result = {
            c["name"]: c["value"]
            for c in cookies
            if "issta" in c.get("domain", "")
        }
        logger.info("Obtained %d Radware cookies", len(result))

        await browser.close()
    return result


class IsstaScraper(BaseScraper):
    """Scrape Issta.co.il search results for one-way TLV/HFA flights.

    Issta's results page is behind Radware Bot Manager. We use headless
    Firefox (once per scrape session) to solve the JS challenge and obtain
    auth cookies, then use curl_cffi with Chrome TLS impersonation to
    fetch results pages quickly via plain HTTP.
    """

    airline_name = "Issta"

    def __init__(self, destination: str = "LCA"):
        super().__init__(destination)
        dest_lower = self.destination.lower()
        self._results_url_template = (
            "https://www.issta.co.il/flights/results.aspx"
            "?route=1&padt=1&pchd=0&pinf=0&pyou=0"
            "&dport={origin}&aport=" + dest_lower
            + "&dtime=-1&class=y&flighttype=0"
        )
        self._calendar_url = (
            f"{CALENDAR_URL}?destinationCode={self.destination}&from=null"
        )
        self._cookies: Optional[Dict[str, str]] = None

    async def search_flights(self, dates: List[str]) -> List[FlightResult]:
        results: List[FlightResult] = []

        # Check which target dates have flights available (no auth needed)
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

        # Obtain Radware cookies if we don't have them yet
        if not self._cookies:
            try:
                self._cookies = await _obtain_radware_cookies()
            except Exception:
                logger.exception("Failed to obtain Radware cookies")
                return results

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

        logger.info(
            "Issta scraper finished. Total: %d unique flights", len(unique),
        )
        return unique

    def _get_available_dates(self) -> set[str]:
        """Query Issta calendar API to find dates with flight availability."""
        try:
            resp = requests.get(
                self._calendar_url, headers=CALENDAR_HEADERS, timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.exception("Failed to fetch Issta calendar")
            return set()

        dates = set()
        for entry in data.get("Dates", []):
            raw = entry.get("Date", "")
            if raw:
                dates.add(raw[:10])  # YYYY-MM-DD
        return dates

    def _search_date(self, date_iso: str) -> List[FlightResult]:
        """Fetch Issta results page for a date across all origins."""
        dt = datetime.strptime(date_iso, "%Y-%m-%d")
        fdate = dt.strftime("%d/%m/%Y")

        session = cffi_requests.Session(impersonate="chrome120")
        for name, value in (self._cookies or {}).items():
            session.cookies.set(name, value, domain="www.issta.co.il")

        all_results: List[FlightResult] = []
        for origin in ORIGINS:
            url = (
                f"{self._results_url_template.format(origin=origin)}"
                f"&fdate={fdate}"
            )
            logger.info(
                "Fetching Issta results for %s from %s", date_iso,
                origin.upper(),
            )

            try:
                resp = session.get(url, timeout=30)
                if resp.status_code == 247:
                    logger.warning(
                        "Radware challenge on %s (cookies may have expired)",
                        origin.upper(),
                    )
                    self._cookies = None  # Force re-auth next time
                    continue
                resp.raise_for_status()
            except Exception:
                logger.exception(
                    "Error fetching Issta for %s from %s",
                    date_iso, origin.upper(),
                )
                continue

            flights = self._parse_results_html(
                resp.text, date_iso, url, origin.upper(),
            )
            all_results.extend(flights)

        return all_results

    def _parse_results_html(
        self, html: str, date_iso: str, url: str, origin: str = "TLV",
    ) -> List[FlightResult]:
        """Parse the Issta Angular results page HTML."""
        results: List[FlightResult] = []

        # The Angular page uses <div class="list-item "> (trailing space)
        # for each flight. Split on that marker to isolate per-flight blocks.
        blocks = html.split('class="list-item ')

        for block in blocks[1:]:
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
            seats_left = None

            for t in texts:
                # Airline name: first text token matching a known airline
                if airline is None:
                    tl = t.lower()
                    if any(a in tl for a in [
                        "israir", "arkia", "el al", "elal",
                        "airhaifa", "air haifa",
                    ]):
                        airline = t

                # Departure time (HH:MM)
                if dep_time is None and re.match(r"^\d{1,2}:\d{2}$", t):
                    dep_time = t

                # Total price: "סה"כ לתשלום: $NNN" → the $NNN token
                if price is None and re.match(r"^\$\d+", t):
                    price = t

                # Seats remaining: "N מקומות אחרונים" or "מקום אחרון"
                if seats_left is None:
                    seats_match = re.match(r"^(\d+)\s+מקומו?ת", t)
                    if seats_match:
                        seats_left = seats_match.group(1)
                    elif "מקום אחרון" in t:
                        seats_left = "1"

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
            elif "airhaifa" in airline_lower or "air haifa" in airline_lower:
                airline = "airHaifa"

            flight = FlightResult(
                airline=airline,
                origin=origin,
                destination=self.destination,
                date=date_iso,
                departure_time=dep_time,
                price=price,
                flight_number=None,
                seats_left=seats_left,
                url=url,
            )
            results.append(flight)
            logger.info(
                "Found %s flight: %s dep %s price %s seats %s",
                airline, date_iso, dep_time, price, seats_left,
            )

        return results
