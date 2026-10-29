import json
from pathlib import Path

from openai import OpenAI

from .tools import DISPATCH, TOOLS

client = OpenAI()
INSTRUCTIONS = (Path(__file__).parent.parent / "prompts" / "analyst.txt").read_text()


def analyze_company(question: str, model: str = "gpt-4.1") -> str:
    response = client.responses.create(
        model=model,
        instructions=INSTRUCTIONS,
        input=question,
        tools=TOOLS,
    )

    for _ in range(10):
        calls = [item for item in response.output if item.type == "function_call"]
        if not calls:
            break
        outputs = []
        for call in calls:
            handler = DISPATCH[call.name]
            result = handler(**json.loads(call.arguments))
            outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(result) if not isinstance(result, str) else result,
                }
            )
        response = client.responses.create(
            model=model,
            instructions=INSTRUCTIONS,
            previous_response_id=response.id,
            input=outputs,
            tools=TOOLS,
        )

    return response.output_text
