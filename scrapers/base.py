from abc import ABC, abstractmethod
from typing import List

from models import FlightResult


class BaseScraper(ABC):
    """Abstract base class for airline flight scrapers."""

    airline_name: str = ""

    @abstractmethod
    async def search_flights(self, dates: List[str]) -> List[FlightResult]:
        """Search for available flights on the given dates.

        Args:
            dates: List of date strings in YYYY-MM-DD format.

        Returns:
            List of FlightResult objects for available flights.
        """
        ...

    async def close(self):
        """Clean up resources. Override if needed."""
        pass
