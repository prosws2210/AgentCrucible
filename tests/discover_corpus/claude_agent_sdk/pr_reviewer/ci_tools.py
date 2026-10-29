import os

import httpx
from claude_agent_sdk import create_sdk_mcp_server, tool

BUILDKITE_ORG = os.getenv("BUILDKITE_ORG", "acme")
BUILDKITE_PIPELINE = os.getenv("BUILDKITE_PIPELINE", "monorepo")
BK_HEADERS = {"Authorization": f"Bearer {os.environ['BUILDKITE_TOKEN']}"}
BK_BASE = f"https://api.buildkite.com/v2/organizations/{BUILDKITE_ORG}/pipelines/{BUILDKITE_PIPELINE}"


@tool("get_build_log", "Fetch the raw log of the first failed job in a CI build", {"build_number": int})
async def get_build_log(args):
    async with httpx.AsyncClient(headers=BK_HEADERS, timeout=30) as client:
        build = (await client.get(f"{BK_BASE}/builds/{args['build_number']}")).json()
        failed = next((j for j in build["jobs"] if j.get("state") == "failed"), None)
        if failed is None:
            return {"content": [{"type": "text", "text": "No failed jobs."}]}
        log = (await client.get(failed["raw_log_url"])).text
    return {"content": [{"type": "text", "text": log[-30000:]}]}


@tool("retry_build", "Rebuild a CI build (re-runs all jobs)", {"build_number": int})
async def retry_build(args):
    async with httpx.AsyncClient(headers=BK_HEADERS, timeout=30) as client:
        r = await client.put(f"{BK_BASE}/builds/{args['build_number']}/rebuild")
    return {"content": [{"type": "text", "text": f"rebuild started: {r.json().get('web_url')}"}]}


ci_server = create_sdk_mcp_server(name="ci-tools", version="1.0.0", tools=[get_build_log, retry_build])
