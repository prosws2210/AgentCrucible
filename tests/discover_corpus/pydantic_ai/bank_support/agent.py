import httpx
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

from .deps import SupportDeps


class SupportOutput(BaseModel):
    support_advice: str = Field(description="Advice returned to the customer")
    block_card: bool = Field(description="Whether the card was blocked")
    risk: int = Field(description="Risk level of query", ge=0, le=10)


support_agent = Agent(
    "openai:gpt-4o",
    deps_type=SupportDeps,
    output_type=SupportOutput,
    system_prompt=(
        "You are a support agent in our bank. Give the customer support and judge the risk "
        "level of their query. Block the card only if the customer reports it lost or stolen."
    ),
)


@support_agent.system_prompt
async def add_customer_name(ctx: RunContext[SupportDeps]) -> str:
    row = await ctx.deps.db.fetchone("SELECT name FROM customers WHERE id = ?", ctx.deps.customer_id)
    return f"The customer's name is {row[0]!r}"


@support_agent.tool
async def customer_balance(ctx: RunContext[SupportDeps], include_pending: bool) -> float:
    """Returns the customer's current account balance."""
    sql = "SELECT balance_cents + CASE WHEN ? THEN pending_cents ELSE 0 END FROM accounts WHERE customer_id = ?"
    row = await ctx.deps.db.fetchone(sql, include_pending, ctx.deps.customer_id)
    return row[0] / 100


@support_agent.tool
async def list_recent_transactions(ctx: RunContext[SupportDeps], limit: int = 10) -> list[dict]:
    """List the customer's most recent card transactions."""
    rows = await ctx.deps.db.fetchall(
        "SELECT posted_at, merchant, amount_cents FROM transactions WHERE customer_id = ? ORDER BY posted_at DESC LIMIT ?",
        ctx.deps.customer_id,
        limit,
    )
    return [{"posted_at": r[0], "merchant": r[1], "amount": r[2] / 100} for r in rows]


@support_agent.tool
async def block_card(ctx: RunContext[SupportDeps], reason: str) -> str:
    """Permanently block the customer's active card."""
    n = await ctx.deps.db.execute(
        "UPDATE cards SET status = 'blocked', blocked_reason = ? WHERE customer_id = ? AND status = 'active'",
        reason,
        ctx.deps.customer_id,
    )
    return f"blocked {n} card(s)"


@support_agent.tool_plain
def get_fx_rate(base: str, quote: str) -> float:
    """Get today's FX rate, e.g. for questions about foreign card spend."""
    r = httpx.get("https://api.frankfurter.app/latest", params={"from": base, "to": quote}, timeout=10)
    return r.json()["rates"][quote]
