import asyncio
import sys

from agents import Runner
from helpdesk.triage import triage_agent


async def main(message: str) -> None:
    result = await Runner.run(triage_agent, input=message, max_turns=12)
    print(f"[{result.last_agent.name}] {result.final_output}")


if __name__ == "__main__":
    asyncio.run(main(" ".join(sys.argv[1:]) or "I was charged twice for invoice INV-1042"))
