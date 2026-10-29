from analyst.agent import analyze_company
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()


class Query(BaseModel):
    question: str


@app.post("/research")
async def research(q: Query):
    return {"answer": analyze_company(q.question)}
