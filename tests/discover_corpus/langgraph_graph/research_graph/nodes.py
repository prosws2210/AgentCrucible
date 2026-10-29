from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import create_react_agent

from .state import ResearchState
from .tools import researcher_tools, writer_tools

llm = ChatAnthropic(model="claude-sonnet-4-5", temperature=0)

researcher = create_react_agent(
    llm,
    tools=researcher_tools,
    name="researcher",
    prompt="Find the 5 most relevant recent papers on the topic and summarise each in 3 bullets.",
)

writer_llm = llm.bind_tools(writer_tools)

WRITER_SYSTEM = (
    "You turn research notes into a literature review. Check citation counts to rank papers, "
    "then save the review with save_report."
)


def research(state: ResearchState) -> dict:
    result = researcher.invoke({"messages": state["messages"]})
    return {"messages": result["messages"][-1:]}


def writer(state: ResearchState) -> dict:
    reply = writer_llm.invoke([("system", WRITER_SYSTEM), *state["messages"]])
    return {"messages": [reply]}
