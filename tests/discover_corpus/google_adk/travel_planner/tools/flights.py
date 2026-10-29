import os

import requests

DUFFEL = "https://api.duffel.com/air"
HEADERS = {
    "Authorization": f"Bearer {os.environ['DUFFEL_ACCESS_TOKEN']}",
    "Duffel-Version": "v2",
    "Content-Type": "application/json",
}


def search_flights(origin: str, destination: str, departure_date: str, adults: int = 1) -> dict:
    """Search for flight offers between two IATA airport codes on a date (YYYY-MM-DD)."""
    body = {
        "data": {
            "slices": [{"origin": origin, "destination": destination, "departure_date": departure_date}],
            "passengers": [{"type": "adult"}] * adults,
            "cabin_class": "economy",
        }
    }
    r = requests.post(f"{DUFFEL}/offer_requests?return_offers=true", json=body, headers=HEADERS, timeout=30)
    r.raise_for_status()
    offers = r.json()["data"]["offers"][:5]
    return {
        "status": "success",
        "offers": [{"id": o["id"], "total": o["total_amount"], "currency": o["total_currency"]} for o in offers],
    }


def book_flight(offer_id: str, passenger_name: str, passenger_email: str, amount: str, currency: str) -> dict:
    """Book and pay for a flight offer using the agency balance."""
    given, _, family = passenger_name.partition(" ")
    body = {
        "data": {
            "selected_offers": [offer_id],
            "payments": [{"type": "balance", "amount": amount, "currency": currency}],
            "passengers": [{"given_name": given, "family_name": family, "email": passenger_email}],
        }
    }
    r = requests.post(f"{DUFFEL}/orders", json=body, headers=HEADERS, timeout=60)
    r.raise_for_status()
    return {"status": "success", "booking_reference": r.json()["data"]["booking_reference"]}
