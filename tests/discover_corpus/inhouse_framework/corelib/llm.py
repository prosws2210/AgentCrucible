import os

import openai


class OpenAILLM:
    """Thin wrapper so the runner does not depend on a specific SDK surface."""

    def __init__(self, model: str = "gpt-4o-mini", temperature: float = 0.0):
        self.model = model
        self.temperature = temperature
        self._client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

    def complete(self, messages: list[dict], tools: list[dict] | None = None):
        return self._client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            messages=messages,
            tools=tools or openai.NOT_GIVEN,
        ).choices[0].message
