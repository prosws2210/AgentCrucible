from app.agent import run_support_agent
from fastapi import FastAPI
from pydantic import BaseModel

api = FastAPI(title="northwind-support")


class ChatIn(BaseModel):
    message: str
    history: list[dict] = []


@api.post("/support/chat")
def chat(body: ChatIn) -> dict:
    return {"reply": run_support_agent(body.message, body.history)}
