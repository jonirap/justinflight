DESTINATIONS = {
    "LCA": {"name": "Larnaca", "country": "Cyprus"},
    "PFO": {"name": "Paphos", "country": "Cyprus"},
    "ATH": {"name": "Athens", "country": "Greece"},
    "RHO": {"name": "Rhodes", "country": "Greece"},
    "SKG": {"name": "Thessaloniki", "country": "Greece"},
    "HER": {"name": "Heraklion", "country": "Greece"},
    "CFU": {"name": "Corfu", "country": "Greece"},
    "MJT": {"name": "Mytilene", "country": "Greece"},
    "ADB": {"name": "Izmir", "country": "Turkey"},
    "AYT": {"name": "Antalya", "country": "Turkey"},
    "DLM": {"name": "Dalaman", "country": "Turkey"},
    "PRG": {"name": "Prague", "country": "Czech Republic"},
    "BUD": {"name": "Budapest", "country": "Hungary"},
    "SOF": {"name": "Sofia", "country": "Bulgaria"},
    "VAR": {"name": "Varna", "country": "Bulgaria"},
    "BOJ": {"name": "Burgas", "country": "Bulgaria"},
    "OTP": {"name": "Bucharest", "country": "Romania"},
    "TBS": {"name": "Tbilisi", "country": "Georgia"},
    "BUS": {"name": "Batumi", "country": "Georgia"},
    "EVN": {"name": "Yerevan", "country": "Armenia"},
    "MRS": {"name": "Marseille", "country": "France"},
    "BCN": {"name": "Barcelona", "country": "Spain"},
    "FCO": {"name": "Rome", "country": "Italy"},
    "MXP": {"name": "Milan", "country": "Italy"},
    "VCE": {"name": "Venice", "country": "Italy"},
}


def find_destination(query: str) -> str | None:
    """Fuzzy-match user input (city name, country, or IATA code) to an IATA code."""
    q = query.strip().lower()
    if not q:
        return None

    # Exact IATA match
    upper = q.upper()
    if upper in DESTINATIONS:
        return upper

    # Exact city or country match
    for code, info in DESTINATIONS.items():
        if q == info["name"].lower() or q == info["country"].lower():
            return code

    # Substring match on city name
    for code, info in DESTINATIONS.items():
        if q in info["name"].lower():
            return code

    # Substring match on country
    for code, info in DESTINATIONS.items():
        if q in info["country"].lower():
            return code

    return None


def destination_display(code: str) -> str:
    """Return 'City (CODE)' display string for a destination."""
    info = DESTINATIONS.get(code)
    if info:
        return f"{info['name']} ({code})"
    return code
