from dataclasses import dataclass
from typing import Optional


@dataclass
class FlightResult:
    airline: str
    origin: str
    destination: str
    date: str
    departure_time: Optional[str] = None
    price: Optional[str] = None
    flight_number: Optional[str] = None
    seats_left: Optional[str] = None
    url: Optional[str] = None

    @property
    def dedup_key(self) -> str:
        if self.flight_number:
            return f"{self.airline}|{self.flight_number}|{self.date}"
        return f"{self.airline}|{self.date}|{self.departure_time}"
