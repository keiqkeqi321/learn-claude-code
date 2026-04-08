# =============================================================
#  OpenAgent — Dockerfile
#  用法:
#    docker build -t openagent .
#    docker run -it openagent
#    docker run -it openagent chat "hello"
#
#  一行启动（直接从 GitHub 构建）:
#    docker run -it $(docker build -q https://github.com/your-org/openagent.git#main:OpenAgent)
# =============================================================
FROM python:3.12-slim

LABEL org.opencontainers.image.title="OpenAgent"
LABEL org.opencontainers.image.description="A modular AI agent CLI"
LABEL org.opencontainers.image.source="https://github.com/your-org/openagent"

# Install system deps
RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

# Copy and install
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .

# Default entrypoint
ENTRYPOINT ["python", "-m", "openagent"]
CMD []
