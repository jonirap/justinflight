"""Full integration test — runs the Issta scraper and prints results."""
import asyncio
import logging
import sys
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("DATA_DIR", "/tmp/justinflight_test")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ.setdefault("TELEGRAM_CHAT_ID", "test")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)

from scrapers import IsstaScraper

TZ = ZoneInfo("Asia/Jerusalem")


async def main():
    today = datetime.now(TZ).date()
    dates = [(today + timedelta(days=d)).isoformat() for d in range(7)]
    print(f"Dates: {dates}\n")

    print("=" * 60)
    print("ISSTA SCRAPER (One-way TLV->LCA, Israeli airlines only)")
    print("=" * 60)
    try:
        scraper = IsstaScraper()
        flights = await scraper.search_flights(dates)
        print(f"\nResults: {len(flights)} flights")
        for f in flights:
            print(f"  {f.airline:20s} | {f.date} | dep {f.departure_time or '-':>5s} | {f.price or '-'}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"ERROR: {e}")

    print()
    print("=" * 60)
    print(f"TOTAL: {len(flights)} flights found")
    print("=" * 60)
    for f in flights:
        print(f"  [{f.airline}] {f.date} dep={f.departure_time} price={f.price} key={f.dedup_key}")


asyncio.run(main())
