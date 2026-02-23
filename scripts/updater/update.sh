#!/bin/bash
# Self-update script — runs inside the updater sidecar container.
# Pulls latest code, rebuilds Docker images, and restarts all containers.

set -e

PROJECT_DIR="${COMPOSE_PROJECT_DIR:-/project}"
STATUS_FILE="/tmp/update_status.json"

write_status() {
    local status="$1"
    local step="$2"
    local error="${3:-null}"
    local started_at
    started_at=$(cat /tmp/update_started_at 2>/dev/null || echo "null")
    cat > "$STATUS_FILE" <<STATUSEOF
{"status": "$status", "step": "$step", "error": $error, "started_at": $started_at}
STATUSEOF
}

# Record start time
date -u +"\"%Y-%m-%dT%H:%M:%SZ\"" > /tmp/update_started_at

cd "$PROJECT_DIR"

# Step 1: Git pull
echo "=== Step 1/3: Pulling latest code ==="
write_status "pulling" "git pull"
if ! git pull origin master; then
    write_status "error" "git pull" "\"git pull failed — check remote connectivity and branch status\""
    exit 1
fi

# Step 2: Docker build
echo "=== Step 2/3: Building Docker images ==="
write_status "building" "docker compose build"
if ! docker compose build --no-cache; then
    write_status "error" "docker compose build" "\"docker compose build failed — check Dockerfiles and build context\""
    exit 1
fi

# Step 3: Restart containers (all EXCEPT the updater itself)
echo "=== Step 3/3: Restarting containers ==="
write_status "restarting" "docker compose restart"
# Collect all services except the updater sidecar — we can't recreate ourselves
SERVICES=$(docker compose config --services | grep -v '^updater$' | tr '\n' ' ')
echo "Recreating services: $SERVICES"
if ! docker compose up -d --force-recreate $SERVICES; then
    write_status "error" "docker compose up" "\"docker compose restart failed — check container logs\""
    exit 1
fi

echo "=== Update complete ==="
write_status "done" "complete"
