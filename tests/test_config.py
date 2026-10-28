import pytest

from agentcrucible.config import Scenario, load_config, load_scenarios


def test_example_project_loads():
    cfg = load_config(__import__("pathlib").Path(__file__).parent.parent / "examples" / "support-agent")
    pairs = load_scenarios(cfg)
    assert len(pairs) >= 10
    assert {"shop", "docs"} <= set(cfg.mcp_servers)


def test_check_syntax_is_validated():
    with pytest.raises(ValueError):
        Scenario.model_validate({"id": "x", "task": "t", "checks": [{"nodot": 1}]})
    with pytest.raises(ValueError):
        Scenario.model_validate({"id": "bad id!", "task": "t", "checks": []})
