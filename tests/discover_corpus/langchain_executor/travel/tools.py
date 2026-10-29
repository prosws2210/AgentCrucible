import os

import requests
from langchain_core.tools import tool

BRAVE_KEY = os.environ["BRAVE_SEARCH_API_KEY"]
AVIATIONSTACK_KEY = os.environ["AVIATIONSTACK_KEY"]
BOOKING_API = os.getenv("BOOKING_API", "https://partners.staybook.example/v2")
BOOKING_TOKEN = os.environ["STAYBOOK_TOKEN"]


@tool
def web_search(query: str) -> str:
    """Search the web for travel information (visa rules, attractions, opening hours)."""
    resp = requests.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": 6},
        headers={"Accept": "application/json", "X-Subscription-Token": BRAVE_KEY},
        timeout=10,
    )
    resp.raise_for_status()
    hits = resp.json()["web"]["results"]
    return "\n".join(f"- {h['title']} ({h['url']}): {h.get('description', '')}" for h in hits)


@tool
def get_flight_status(flight_number: str, date: str) -> dict:
    """Get live status for a flight number (IATA, e.g. BA117) on a YYYY-MM-DD date."""
    resp = requests.get(
        "http://api.aviationstack.com/v1/flights",
        params={"access_key": AVIATIONSTACK_KEY, "flight_iata": flight_number, "flight_date": date},
        timeout=10,
    )
    data = resp.json().get("data", [])
    if not data:
        return {"status": "unknown"}
    f = data[0]
    return {"status": f["flight_status"], "departure": f["departure"], "arrival": f["arrival"]}


@tool
def book_hotel(hotel_id: str, check_in: str, check_out: str, guest_name: str, card_token: str) -> dict:
    """Book and pay for a hotel room using the traveller's saved card token."""
    resp = requests.post(
        f"{BOOKING_API}/reservations",
        json={
            "hotel_id": hotel_id,
            "check_in": check_in,
            "check_out": check_out,
            "guest": {"name": guest_name},
            "payment": {"card_token": card_token, "capture": True},
        },
        headers={"Authorization": f"Bearer {BOOKING_TOKEN}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


@tool("currency_convert")
def convert(amount: float, from_ccy: str, to_ccy: str) -> float:
    """Convert an amount between two currencies at today's rate."""
    resp = requests.get(
        "https://api.frankfurter.app/latest",
        params={"amount": amount, "from": from_ccy, "to": to_ccy},
        timeout=10,
    )
    return resp.json()["rates"][to_ccy]
