FROM python:3.12-slim

# Install git and Docker CLI (for docker compose)
RUN apt-get update && \
    apt-get install -y --no-install-recommends git curl && \
    curl -fsSL https://get.docker.com | sh && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /updater

COPY server.py update.sh ./
RUN chmod +x update.sh

EXPOSE 9999

CMD ["python", "server.py"]
