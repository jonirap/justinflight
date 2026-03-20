#!/usr/bin/env python3
"""System test for the El Al seat availability scraper."""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Stub TELEGRAM_BOT_TOKEN so config.py doesn't raise
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")

from scrapers.elal import ElAlScraper, _fetch_flights, _build_date_map


def test_api_fetch():
    """Test that the El Al API returns valid data."""
    print("=== Testing El Al API fetch ===")
    data = _fetch_flights()
    assert data is not None, "API returned None"
    assert data["responseCode"] == 0, f"Bad responseCode: {data['responseCode']}"

    date_range = data["dateRange"]
    print(f"Date range: {date_range['dates']}")
    print(f"Flights from Israel: {len(data['flightsFromIsrael'])} destination groups")
    print(f"Flights to Israel: {len(data['flightsToIsrael'])} origin groups")

    # List all destinations from Israel
    dests = [g["origin"] for g in data["flightsFromIsrael"]]
    print(f"Destinations from Israel: {', '.join(sorted(dests))}")
    print()
    return data


def test_date_mapping(data):
    """Test date string mapping."""
    print("=== Testing date mapping ===")
    date_map = _build_date_map(data["dateRange"])
    for dd_mm, iso in sorted(date_map.items(), key=lambda x: x[1]):
        print(f"  {dd_mm} -> {iso}")
    print()
    return date_map


def test_scraper_lca(date_map):
    """Test scraper for LCA destination."""
    print("=== Testing ElAlScraper for LCA ===")
    scraper = ElAlScraper("LCA")
    dates = list(date_map.values())
    flights = asyncio.run(scraper.search_flights(dates))
    print(f"Found {len(flights)} flight(s) to LCA:")
    for f in flights:
        print(f"  {f.flight_number} {f.origin}->{f.destination} "
              f"{f.date} dep {f.departure_time} seats={f.seats_left}")
    print()
    return flights


def test_scraper_all_dests(data, date_map):
    """Test scraper across all available destinations."""
    print("=== Testing ElAlScraper for all destinations ===")
    dates = list(date_map.values())
    total = 0
    for group in data["flightsFromIsrael"]:
        dest = group["origin"]
        scraper = ElAlScraper(dest)
        flights = asyncio.run(scraper.search_flights(dates))
        if flights:
            total += len(flights)
            print(f"  {dest}: {len(flights)} flight(s) with availability")
            for f in flights:
                print(f"    {f.flight_number} {f.date} dep {f.departure_time} "
                      f"seats={f.seats_left}")
    print(f"\nTotal flights with availability: {total}")
    print()


if __name__ == "__main__":
    data = test_api_fetch()
    date_map = test_date_mapping(data)
    test_scraper_lca(date_map)
    test_scraper_all_dests(data, date_map)
    print("All tests passed!")
