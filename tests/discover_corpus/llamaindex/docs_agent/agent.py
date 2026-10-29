from llama_index.core.agent.workflow import FunctionAgent
from llama_index.core.tools import FunctionTool
from llama_index.llms.openai import OpenAI

from . import tools as t

search_tool = FunctionTool.from_defaults(fn=t.search_docs)
ticket_tool = FunctionTool.from_defaults(
    fn=t.create_jira_ticket,
    name="open_ticket",
    description="Open a DOCS Jira ticket describing a documentation gap.",
)
release_notes_tool = FunctionTool.from_defaults(fn=t.fetch_release_notes)

docs_agent = FunctionAgent(
    name="DocsAgent",
    description="Answers product questions from the docs and release notes.",
    tools=[search_tool, ticket_tool, release_notes_tool],
    llm=OpenAI(model="gpt-4o-mini", temperature=0),
    system_prompt=(
        "Answer using search_docs first. If the docs do not cover the question, check the "
        "release notes, and if still missing open a ticket."
    ),
)
