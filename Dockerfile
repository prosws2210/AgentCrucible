# AgentCrucible backend / runner image.
#   docker compose: runs `crucible serve` (API) against Postgres and the Ollama service
#   standalone:     docker run agentcrucible:0.1.0 run --suite core
# Companies extend it with their own agent + scenarios:
#   FROM agentcrucible:0.1.0
#   COPY . /workspace/project
#   WORKDIR /workspace/project
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 UV_SYSTEM_PYTHON=1
# git: workspace fixtures (fresh repo copy + baseline commit per episode) and state.git_diff
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir uv==0.11.23

WORKDIR /opt/agentcrucible
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN uv pip install --system ".[examples]"

# Bundled example project (support agent + 2 MCP servers + 10 scenarios)
COPY examples /workspace/examples
RUN useradd --create-home --uid 10001 runner \
 && for d in /workspace/examples/*/; do mkdir -p "$d.crucible"; done \
 && chown -R runner /workspace
USER 10001
WORKDIR /workspace/examples/support-agent

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)" || exit 1

ENTRYPOINT ["crucible"]
CMD ["--help"]
