"""Functions are driven with a chat message only when they can take one; pipeline steps are left out."""

import pytest

from agentcrucible.adapters.function import turn_for
from agentcrucible.discover.plan import chat_input

H = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}, {"role": "user", "content": "refund?"}]


def test_keyword_only_and_named_message_parameters():
    def call(*, query, model="m"):
        return f"q={query}"

    def ask(model="m", message=""):
        return f"m={message}"

    def chat(messages):
        return len(messages)

    def loop(message, history):
        return f"{message}|{len(history)}"

    assert turn_for(call)(H) == "q=refund?"
    assert turn_for(ask)(H) == "m=refund?"  # positional, but not the first one: by keyword
    assert turn_for(chat)(H) == 3
    assert turn_for(loop)(H) == "refund?|2"


def test_functions_that_cant_take_a_message_say_so():
    def detect_boundaries(pdf_bytes: bytes, page_count: int):
        return []

    def call():
        return "x"

    for fn in (detect_boundaries, call):
        with pytest.raises(TypeError, match="can't take a chat message"):
            turn_for(fn)


def p(name, kind="pos", required=True, type_=""):
    return {"name": name, "kind": kind, "required": required, "type": type_}


def test_static_check_matches_the_adapter():
    assert chat_input([p("query", "kw")]) == ("query", "ok")
    assert chat_input([p("text", type_="str")]) == ("text", "ok")
    assert chat_input([p("user_text", type_="str")])[0] == "user_text"
    assert chat_input([p("pdf_bytes", type_="bytes"), p("page_count", type_="int")])[0] is None
    assert chat_input([p("payload", type_="Dict[str, Any]")])[0] is None
    assert chat_input([])[0] is None
    assert chat_input([p("message"), p("db")])[1].startswith("also needs")
    assert chat_input(None)[0] == ""  # no signature recorded: leave the agent alone


def test_agents_with_an_unfinished_adapter_are_skipped_not_failed(tmp_path):
    import asyncio

    from agentcrucible.config import load_config, load_scenarios
    from agentcrucible.runner import Runner, RunOptions, scaffold_pending

    (tmp_path / "adapters").mkdir()
    (tmp_path / "adapters" / "bot.py").write_text(
        'def turn(history):\n    raise NotImplementedError("call Bot here with `message` and return the reply")\n')
    (tmp_path / "scenarios").mkdir()
    (tmp_path / "scenarios" / "hi.yaml").write_text("id: hi\nagent: bot\ntask: hello\nchecks:\n  - output.regex: .+\n")
    (tmp_path / "crucible.yaml").write_text(
        "project: p\nagents:\n  bot:\n    transport: stdio\n    command: python adapters/bot.py\n"
        "suites:\n  bot:\n    path: scenarios\n    agent: bot\n")
    cfg = load_config(tmp_path / "crucible.yaml")
    assert scaffold_pending(cfg, "bot")
    run = asyncio.run(Runner(cfg, RunOptions(label="t")).run(load_scenarios(cfg)))
    assert run["episodes"] == [] and run["skipped"][0]["scenario_id"] == "hi"


def test_a_lone_document_parameter_isnt_a_message():
    assert chat_input([p("pdf_b64", type_="str")])[0] is None
    assert chat_input([p("file_path", type_="str")])[0] is None

    def detect(pdf_b64: str, client=None):
        return []

    with pytest.raises(TypeError, match="can't take a chat message"):
        turn_for(detect)


def test_class_agents_on_a_repo_base_class_get_an_adapter_from_their_input_keys(tmp_path):
    from agentcrucible.discover import build_plan, discover

    pkg = tmp_path / "app"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "base.py").write_text(
        "from openai import OpenAI\n\nclass BaseAgent:\n    def __init__(self, name, tools, llm=None):\n"
        "        self.tools, self.llm = tools, llm or OpenAI()\n\n    def invoke(self, input):\n        return self._execute_task(input)\n")
    (pkg / "invoice.py").write_text(
        "from app.base import BaseAgent\n\nclass InvoiceAgent(BaseAgent):\n    def __init__(self, llm=None, **kw):\n"
        "        super().__init__(name='invoice', tools=[], llm=llm)\n\n    def _execute_task(self, input):\n"
        "        text = input.get('user_message')\n        kind = input['task_type']\n        return {'output': text}\n")
    d = discover(tmp_path)
    build_plan(d, tmp_path)
    ag = next(a for a in d.agents if a.name.lower().startswith("invoice"))
    plan = next(p for p in d.plans if p.agent == ag.id)
    assert plan.strategy == "code" and '{"user_message": message}' in plan.adapter_code
    compile(plan.adapter_code, "adapter.py", "exec")
    assert "env_map=" in plan.adapter_code and "tools=" in plan.adapter_code  # fixtures, mocks and tracing apply too
    assert "InvoiceAgent(llm=chat_model())" in plan.adapter_code  # a model on the gateway, not "no LLM configured"
    smoke = next(s for s in d.scenarios if s.agent == ag.id and s.id.endswith("-smoke"))
    assert "budget.min_llm_calls" in smoke.yaml
    (pkg / "invoice.py").write_text(  # passes **kwargs to a base class that takes the model
        "from app.base import BaseAgent\n\nclass InvoiceAgent(BaseAgent):\n    def __init__(self, **kw):\n"
        "        super().__init__(name='invoice', tools=[], **kw)\n\n    def _execute_task(self, input):\n"
        "        return {'output': input.get('user_message')}\n")
    d2 = discover(tmp_path)
    build_plan(d2, tmp_path)
    ag2 = next(a for a in d2.agents if a.name.lower().startswith("invoice"))
    assert "InvoiceAgent(llm=chat_model())" in next(p for p in d2.plans if p.agent == ag2.id).adapter_code


def test_the_import_check_gives_settings_mapped_to_fixtures_a_placeholder(tmp_path):
    from agentcrucible.adapters import apply_env_map
    from agentcrucible.discover.apply import PLACEHOLDER

    assert PLACEHOLDER["db"].startswith("postgresql://") and PLACEHOLDER["http"].startswith("http://")
    import os
    os.environ.pop("CRUCIBLE_DB_APP_URL", None)
    apply_env_map({"SOME_UNSET_DATABASE_URL": "db:app"})  # no fixture in this process: the setting is left alone
    assert "SOME_UNSET_DATABASE_URL" not in os.environ
