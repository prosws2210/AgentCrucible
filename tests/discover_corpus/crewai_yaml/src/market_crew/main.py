#!/usr/bin/env python
from market_crew.crew import MarketCrew


def run():
    inputs = {
        "product": "Acme Analytics",
        "competitors": "https://www.mixpanel.com/pricing, https://amplitude.com/pricing",
    }
    MarketCrew().crew().kickoff(inputs=inputs)


if __name__ == "__main__":
    run()
