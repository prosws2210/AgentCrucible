# Throwaway container for benchmarks/import_bench.py: third-party agent code runs here, not on your machine.
#   docker build -f benchmarks/Dockerfile -t agentcrucible-bench .
#   docker run --rm --network agentcrucible_default -v "$PWD/.bench:/work" agentcrucible-bench
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git build-essential ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

WORKDIR /src
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY benchmarks ./benchmarks
RUN uv pip install --system --no-cache .

ENV CRUCIBLE_SRC=/src CRUCIBLE_LLM_URL=http://models:11434/v1 CRUCIBLE_MODEL=qwen2.5:7b \
    CREWAI_DISABLE_TELEMETRY=true OTEL_SDK_DISABLED=true ANONYMIZED_TELEMETRY=false
ENTRYPOINT ["python", "/src/benchmarks/import_bench.py", "--work", "/work"]
