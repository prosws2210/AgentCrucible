import asyncio
import sys

from analytics_team.team import build_team
from autogen_agentchat.ui import Console


async def main(task: str) -> None:
    team = build_team()
    await Console(team.run_stream(task=task))


if __name__ == "__main__":
    asyncio.run(main(" ".join(sys.argv[1:]) or "Which product category grew fastest last quarter? Email cfo@acme.example."))
