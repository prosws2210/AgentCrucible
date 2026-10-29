import requests
from google.adk.agents import Agent, LlmAgent

from .tools.flights import book_flight, search_flights
from .tools.hotels import cancel_hotel_booking, search_hotels

MODEL = "gemini-2.5-flash"


def get_weather(city: str) -> dict:
    """Get the current weather for a city."""
    geo = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search", params={"name": city, "count": 1}, timeout=10
    ).json()
    if not geo.get("results"):
        return {"status": "error", "error_message": f"unknown city {city}"}
    loc = geo["results"][0]
    wx = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={"latitude": loc["latitude"], "longitude": loc["longitude"], "current": "temperature_2m,weather_code"},
        timeout=10,
    ).json()
    return {"status": "success", "current": wx["current"]}


flight_agent = LlmAgent(
    name="flight_agent",
    model=MODEL,
    description="Searches and books flights.",
    instruction="Search flights, present the 3 cheapest options, and book only after the user picks one.",
    tools=[search_flights, book_flight],
)

hotel_agent = LlmAgent(
    name="hotel_agent",
    model=MODEL,
    description="Finds hotels and manages hotel bookings.",
    instruction="Help the user find hotels. Confirm before cancelling any booking.",
    tools=[search_hotels, cancel_hotel_booking],
)

root_agent = Agent(
    name="travel_coordinator",
    model=MODEL,
    description="Plans trips end to end.",
    instruction=(
        "You coordinate trip planning. Delegate flights to flight_agent and hotels to hotel_agent. "
        "Use get_weather to advise on packing."
    ),
    tools=[get_weather],
    sub_agents=[flight_agent, hotel_agent],
)
