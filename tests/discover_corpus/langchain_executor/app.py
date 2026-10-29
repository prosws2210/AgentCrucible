from fastapi import FastAPI
from pydantic import BaseModel
from travel.agent import travel_executor

app = FastAPI()


class Ask(BaseModel):
    input: str
    chat_history: list = []


@app.post("/concierge")
async def concierge(body: Ask):
    out = await travel_executor.ainvoke({"input": body.input, "chat_history": body.chat_history})
    return {"output": out["output"]}
