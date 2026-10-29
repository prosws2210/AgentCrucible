from agents import Agent
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX

from .specialists import billing_agent, tech_agent

triage_agent = Agent(
    name="Triage",
    instructions=(
        f"{RECOMMENDED_PROMPT_PREFIX}\n"
        "Figure out whether the customer needs billing or technical help and hand off. "
        "Do not try to solve the problem yourself."
    ),
    model="gpt-4.1-mini",
    handoffs=[billing_agent, tech_agent],
)
