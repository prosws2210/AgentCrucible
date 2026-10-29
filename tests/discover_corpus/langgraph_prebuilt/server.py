from billing_agent.agent import agent
from fastapi import FastAPI
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

app = FastAPI(title="billing-assistant")


class ChatRequest(BaseModel):
    thread_id: str
    message: str


@app.post("/chat")
async def chat(req: ChatRequest):
    result = await agent.ainvoke(
        {"messages": [HumanMessage(req.message)]},
        config={"configurable": {"thread_id": req.thread_id}},
    )
    return {"reply": result["messages"][-1].content}
