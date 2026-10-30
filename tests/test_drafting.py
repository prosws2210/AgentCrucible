"""Draft tests fit the agent they're for: the repo's own examples go where they belong, RAG checks only to agents
that retrieve, and tasks read like a request, not a function signature."""

from agentcrucible.discover.plan import _task_for, draft_scenarios, eval_cases_for
from agentcrucible.discover.schema import Agent, Discovery, Evidence, Fact, RepoInfo, Tool, VectorStore


def disc(agents, cases, tools=(), vector=False):
    facts = {f"f{i}": Fact(id=f"f{i}", kind="agent", name=a.id, evidence=[Evidence(file=path, line=1)])
             for i, (a, path) in enumerate(agents)}
    for i, (a, _) in enumerate(agents):
        a.evidence = [f"f{i}"]
    return Discovery(repo=RepoInfo(root="/r", name="r"), agents=[a for a, _ in agents], facts=facts, tools=list(tools),
                     test_cases=[{"input": q, "expected": e, "file": f, "evidence": []} for q, e, f in cases],
                     vector_stores=[VectorStore(id="qdrant", kind="qdrant")] if vector else [])


def test_a_single_agent_gets_the_repos_examples():
    d = disc([(Agent(id="a", name="A"), "src/agent.py")], [("Where is my order?", "in transit", "evals/golden.jsonl")])
    assert len(eval_cases_for(d, d.agents[0], retriever=False)) == 1


def test_examples_go_only_to_the_agents_they_were_written_for():
    split = Agent(id="split", name="Splitter")
    rag = Agent(id="rag", name="Answerer")
    excel = Agent(id="excel", name="Excel mapper")
    d = disc([(split, "services/api/src/extraction/splitter.py"), (rag, "services/api/src/rag/answer.py"),
              (excel, "services/api/src/extraction/excel/mapping.py")],
             [("How is a lease measured?", None, "services/api/src/rag/evaluation/retrieval_questions.jsonl"),
              ("Split this file", "2 documents", "services/api/src/extraction/evals/split_cases.jsonl")])
    assert [c["file"] for c in eval_cases_for(d, split, retriever=False)] == ["services/api/src/extraction/evals/split_cases.jsonl"]
    assert [c["file"] for c in eval_cases_for(d, rag, retriever=True)] == ["services/api/src/rag/evaluation/retrieval_questions.jsonl"]
    assert eval_cases_for(d, rag, retriever=False) == [c for c in d.test_cases if "/rag/" in c["file"]]


def test_no_rag_scenarios_without_a_retriever_and_evals_always_check_something():
    a = Agent(id="a", name="A")
    d = disc([(a, "src/agent.py"), (Agent(id="b", name="B"), "src/other/b.py")],
             [("What is IFRS 16?", None, "src/evals/q.jsonl")], vector=True)
    ids = [s.id for s in draft_scenarios(d, a, set())]
    assert not any("unknown-answer" in i or "grounded" in i for i in ids)
    one = disc([(Agent(id="solo", name="Solo"), "src/agent.py")], [("What is IFRS 16?", None, "src/evals/q.jsonl")])
    sc = next(s for s in draft_scenarios(one, one.agents[0], set()) if "eval" in s.id)
    assert "judge.rubric" in sc.yaml and "customer" not in sc.yaml


def test_tasks_leave_out_internal_parameters():
    t = Tool(name="create_invoice", description="Create an invoice from extracted data",
             params={"document_id": "int", "user_id": "str", "db_session": "Session", "invoice_data": "dict"})
    task = _task_for(t)
    assert "document_id" in task and "db_session" not in task and "invoice_data" not in task


def test_postgres_apps_get_postgres_fixtures(tmp_path):
    from types import SimpleNamespace

    import pytest

    from agentcrucible.config import Environment, Fixture, Scenario
    from agentcrucible.discover.schema import Datastore
    from agentcrucible.runner import Runner

    a = Agent(id="a", name="A", datastores=["app"], tools=["create_invoice"])
    d = disc([(a, "src/agent.py")], [], tools=[Tool(name="create_invoice", params={"invoice_id": "int"})])
    d.datastores = [Datastore(id="app", kind="postgres", tables={"invoices": {"id": "int"}})]
    sc = next(s for s in draft_scenarios(d, a, set()) if s.id.endswith("-uses"))
    assert "kind: postgres" in sc.yaml

    seed = tmp_path / "app.sql"
    seed.write_text("DO $$ BEGIN CREATE TYPE s AS ENUM ('a'); END $$;\nCREATE TABLE t (id SERIAL);\n")
    fake = SimpleNamespace(cfg=SimpleNamespace(postgres=SimpleNamespace(admin_url=None)), _resolve=lambda sc, rel: seed)
    scen = Scenario(id="x", task="hi", checks=[{"output.regex": ".+"}],
                    environment=Environment(fixtures={"app": Fixture(seed=str(seed))}))
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        Runner._build_fixtures(fake, scen, tmp_path, [])


def test_tables_only_the_models_define_are_created_in_the_fixture(tmp_path):
    from agentcrucible.discover.plan import project_files
    from agentcrucible.discover.schema import Datastore

    (tmp_path / "schema.sql").write_text("CREATE TABLE IF NOT EXISTS public.invoices (id INTEGER, total NUMERIC);\n")
    d = disc([(Agent(id="a", name="A"), "src/agent.py")], [])
    d.datastores = [Datastore(id="app", kind="postgres", schema_files=["schema.sql"],
                              tables={"invoices": {"id": "INTEGER"}, "llm_usage": {"id": "TEXT", "tokens": "INTEGER"}})]
    sql = project_files(d, tmp_path)["fixtures/app.sql"]
    assert "CREATE TABLE IF NOT EXISTS llm_usage" in sql  # the model's table, missing from schema.sql
    assert sql.count("CREATE TABLE IF NOT EXISTS public.invoices") == 1 and "CREATE TABLE IF NOT EXISTS invoices" not in sql


def test_leaving_an_agent_out_closes_its_other_questions():
    from agentcrucible.discover.schema import Question
    from agentcrucible.server_discover import answer_questions

    d = disc([(Agent(id="init", name="Init", confidence="low"), "src/a.py")], [])
    d.questions = [Question(id="q1", text="Is Init an agent you want to test?", about="agent:init", evidence=[]),
                   Question(id="q2", text="How can AgentCrucible start Init?", about="agent:init", evidence=[])]
    answer_questions(d, {"q1": "no"})
    assert d.agents[0].include is False and d.questions[1].answer == "(left out)"
