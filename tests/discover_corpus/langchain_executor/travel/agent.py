from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI

from .tools import book_hotel, convert, get_flight_status, web_search

TOOLS = [web_search, get_flight_status, book_hotel, convert]

prompt = ChatPromptTemplate.from_messages(
    [
        ("system", "You are a travel concierge. Confirm price and dates with the traveller before booking anything."),
        MessagesPlaceholder("chat_history", optional=True),
        ("human", "{input}"),
        MessagesPlaceholder("agent_scratchpad"),
    ]
)

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
tool_agent = create_tool_calling_agent(llm, TOOLS, prompt)

travel_executor = AgentExecutor(
    agent=tool_agent,
    tools=TOOLS,
    max_iterations=6,
    handle_parsing_errors=True,
    verbose=True,
)
