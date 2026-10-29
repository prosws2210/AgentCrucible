from typing import List

from crewai import Agent, Crew, Process, Task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.project import CrewBase, agent, crew, task
from market_crew.tools.custom_tools import fetch_competitor_page, sales_lookup, save_report


@CrewBase
class MarketCrew:
    """Competitive positioning crew."""

    agents: List[BaseAgent]
    tasks: List[Task]

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def researcher(self) -> Agent:
        return Agent(
            config=self.agents_config["researcher"],
            tools=[fetch_competitor_page, sales_lookup],
            verbose=True,
        )

    @agent
    def analyst(self) -> Agent:
        return Agent(
            config=self.agents_config["analyst"],
            tools=[sales_lookup, save_report],
            allow_delegation=False,
        )

    @task
    def competitor_scan(self) -> Task:
        return Task(config=self.tasks_config["competitor_scan"])

    @task
    def positioning_brief(self) -> Task:
        return Task(config=self.tasks_config["positioning_brief"])

    @crew
    def crew(self) -> Crew:
        return Crew(agents=self.agents, tasks=self.tasks, process=Process.sequential, verbose=True)
