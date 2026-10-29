# Acme support (demo codebase for `crucible discover`)

A small but realistic agent service: a hand-written OpenAI tool loop (`acme/agent.py`), tools on a SQLite database and
a payments API (`acme/tools.py`), a FastAPI endpoint (`acme/api.py`), a prompt file, an eval set and an MCP server.
It contains nothing AgentCrucible-specific. Try:

```bash
crucible discover examples/import-demo            # review what it finds
crucible discover examples/import-demo --apply    # write agent-tests/ and smoke-run it
```
