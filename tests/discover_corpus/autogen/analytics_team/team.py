import os

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.conditions import MaxMessageTermination, TextMentionTermination
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_ext.models.openai import OpenAIChatCompletionClient

from .tools import run_sql_query, save_chart, send_email


def build_team() -> RoundRobinGroupChat:
    model_client = OpenAIChatCompletionClient(model="gpt-4o", api_key=os.environ["OPENAI_API_KEY"])

    analyst = AssistantAgent(
        name="data_analyst",
        model_client=model_client,
        tools=[run_sql_query, save_chart],
        system_message=(
            "You answer business questions with SQL against the warehouse (tables: orders, customers, "
            "products). Produce one chart for the key finding."
        ),
        reflect_on_tool_use=True,
    )

    reporter = AssistantAgent(
        name="reporter",
        model_client=model_client,
        tools=[send_email],
        system_message="Write a 5-line executive summary of the analyst's findings and email it. Then say TERMINATE.",
    )

    termination = TextMentionTermination("TERMINATE") | MaxMessageTermination(20)
    return RoundRobinGroupChat([analyst, reporter], termination_condition=termination)
