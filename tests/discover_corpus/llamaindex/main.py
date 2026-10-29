import asyncio
import sys

from docs_agent.agent import docs_agent


async def main() -> None:
    question = " ".join(sys.argv[1:]) or "How do I rotate an API key?"
    response = await docs_agent.run(user_msg=question)
    print(str(response))


if __name__ == "__main__":
    asyncio.run(main())
