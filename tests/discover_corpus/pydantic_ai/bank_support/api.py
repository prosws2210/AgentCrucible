from fastapi import Depends, FastAPI, Header
from pydantic import BaseModel

from .agent import SupportOutput, support_agent
from .deps import DatabaseConn, SupportDeps

app = FastAPI()
db = DatabaseConn()


class Question(BaseModel):
    text: str


def current_customer(x_customer_id: int = Header(...)) -> int:
    return x_customer_id


@app.post("/support", response_model=SupportOutput)
async def support(q: Question, customer_id: int = Depends(current_customer)):
    result = await support_agent.run(q.text, deps=SupportDeps(customer_id=customer_id, db=db))
    return result.output
