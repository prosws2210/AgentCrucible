import os

import requests

HOTELS_API = os.getenv("HOTELS_API", "https://api.hotelbeds.example/hotel-api/1.0")
HEADERS = {"Api-key": os.environ["HOTELS_API_KEY"], "Accept": "application/json"}


def search_hotels(city_code: str, check_in: str, check_out: str) -> dict:
    """Find available hotels in a city for the given dates."""
    r = requests.get(
        f"{HOTELS_API}/hotels",
        params={"destination": city_code, "checkIn": check_in, "checkOut": check_out},
        headers=HEADERS,
        timeout=20,
    )
    r.raise_for_status()
    return {"status": "success", "hotels": r.json()["hotels"][:8]}


def cancel_hotel_booking(booking_reference: str) -> dict:
    """Cancel an existing hotel booking. Cancellation fees may apply."""
    r = requests.delete(
        f"{HOTELS_API}/bookings/{booking_reference}",
        params={"cancellationFlag": "CANCELLATION"},
        headers=HEADERS,
        timeout=20,
    )
    r.raise_for_status()
    return {"status": "success", "cancellation": r.json()["booking"]["status"]}
