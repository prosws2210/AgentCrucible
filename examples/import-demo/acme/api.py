"""HTTP API used by the website's chat widget."""

from fastapi import FastAPI
from pydantic import BaseModel

from acme.agent import run_agent

app = FastAPI(title="Acme support")


class ChatRequest(BaseModel):
    messages: list[dict]


@app.post("/chat")
def chat(req: ChatRequest) -> dict:
    return {"reply": run_agent(req.messages)}
