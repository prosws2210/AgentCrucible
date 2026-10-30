"""AgentCrucible's own model calls cope with picky models, and code under test can't phone home."""

import asyncio
import json

import httpx

from agentcrucible.gateway import child_env, post_chat


def test_tracing_and_telemetry_are_off_unless_a_spec_turns_them_on():
    env = child_env()
    assert env["LANGCHAIN_TRACING_V2"] == "false" and env["LANGSMITH_TRACING"] == "false" and env["SENTRY_DSN"] == ""
    assert child_env({"LANGSMITH_TRACING": "true"})["LANGSMITH_TRACING"] == "true"


def test_a_parameter_the_model_rejects_is_dropped_and_remembered():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        if "temperature" in body:
            return httpx.Response(400, json={"error": {"message": "`temperature` is deprecated for this model."}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})

    async def go() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            body = {"model": "picky-test-model", "temperature": 0.7, "messages": []}
            r = await post_chat(http, "http://llm/v1", "k", dict(body))
            assert r.json()["choices"][0]["message"]["content"] == "hi"
            await post_chat(http, "http://llm/v1", "k", dict(body))  # the second call leaves it out from the start

    asyncio.run(go())
    assert ["temperature" in b for b in seen] == [True, False, False]


def test_a_tool_that_reports_its_own_failure_counts_as_an_error():
    from agentcrucible.checks import REPORTED_FAILURE

    assert REPORTED_FAILURE.search('{"success": false, "error": "Invalid document type"}')
    assert REPORTED_FAILURE.search("{'ok': False, 'ids': []}")
    assert REPORTED_FAILURE.search('{"status": "error"}')
    assert not REPORTED_FAILURE.search('{"success": true, "error": null, "id": 3}')
    assert not REPORTED_FAILURE.search('{"success": true, "error": ""}')
    assert not REPORTED_FAILURE.search("The error rate is low")
