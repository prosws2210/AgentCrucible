# AgentCrucible runner image. Companies extend it with their own agent + scenarios:
#   FROM ghcr.io/<you>/agentcrucible:0.1.0
#   COPY . /workspace/project
#   WORKDIR /workspace/project
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 UV_SYSTEM_PYTHON=1
RUN pip install --no-cache-dir uv==0.11.23

WORKDIR /opt/agentcrucible
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN uv pip install --system ".[examples]"

# Bundled example project (support agent + 2 MCP servers + 10 scenarios)
COPY examples /workspace/examples
RUN useradd --create-home --uid 10001 runner && chown -R runner /workspace
USER 10001
WORKDIR /workspace/examples/support-agent

ENTRYPOINT ["crucible"]
CMD ["--help"]
