from pathlib import Path

from claude_agent_sdk import (
    AgentDefinition,
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

from .ci_tools import ci_server

PROMPTS = Path(__file__).parent.parent / "prompts"


async def review_pull_request(repo_path: str, pr_number: int, build_number: int) -> str:
    options = ClaudeAgentOptions(
        system_prompt=(PROMPTS / "lead.md").read_text(),
        cwd=repo_path,
        allowed_tools=[
            "Read",
            "Grep",
            "Glob",
            "Bash",
            "mcp__ci__get_build_log",
            "mcp__ci__retry_build",
        ],
        mcp_servers={"ci": ci_server},
        agents={
            "reviewer": AgentDefinition(
                description="Reviews a diff for correctness bugs and missing tests. Use for every changed file group.",
                prompt=(PROMPTS / "reviewer.md").read_text(),
                tools=["Read", "Grep", "Glob"],
                model="sonnet",
            ),
        },
        max_turns=40,
    )

    report: list[str] = []
    async for message in query(
        prompt=f"Review PR #{pr_number}. If CI build {build_number} failed, find out why and retry it if flaky.",
        options=options,
    ):
        if isinstance(message, AssistantMessage):
            report.extend(b.text for b in message.content if isinstance(b, TextBlock))
        elif isinstance(message, ResultMessage):
            break
    return "\n".join(report)
