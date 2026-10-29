from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from .nodes import research, writer
from .state import ResearchState
from .tools import writer_tools

workflow = StateGraph(ResearchState)
workflow.add_node("research", research)
workflow.add_node("writer", writer)
workflow.add_node("tools", ToolNode(writer_tools))

workflow.add_edge(START, "research")
workflow.add_edge("research", "writer")
workflow.add_conditional_edges("writer", tools_condition, {"tools": "tools", END: END})
workflow.add_edge("tools", "writer")

graph = workflow.compile()
