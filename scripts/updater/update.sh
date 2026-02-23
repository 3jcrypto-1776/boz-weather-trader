#!/bin/bash
# Self-update script — runs inside the updater sidecar container.
# Pulls latest code, rebuilds Docker images, and restarts all containers.
#
# KEY INSIGHT: This script runs inside a container with a Docker socket mount.
# Docker compose commands talk to the HOST Docker daemon, but relative bind
# mount paths (./monitoring/...) resolve to /project/... which doesn't exist
# on the host. We avoid this by:
#   1. Using -f docker-compose.yml explicitly (skips docker-compose.override.yml
#      which has the dev bind mount for hot reload)
#   2. Only recreating app services (backend, celery, frontend) which have NO
#      relative bind mounts in the base compose file
#   3. Skipping monitoring services (prometheus, alertmanager, grafana) which
#      use external images and don't need updating during code deploys

set -e

PROJECT_DIR="${COMPOSE_PROJECT_DIR:-/project}"
STATUS_FILE="/tmp/update_status.json"

# Compose command: explicit -f to skip docker-compose.override.yml
COMPOSE="docker compose -f ${PROJECT_DIR}/docker-compose.yml"

# Only recreate services that use our built images and have NO relative bind mounts.
# Monitoring services (prometheus, alertmanager, grafana) use external images and
# have config file bind mounts that can't resolve from inside this container.
# The updater itself is excluded because it can't safely recreate itself.
APP_SERVICES="backend celery-worker celery-beat frontend"

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
printf "=== Step 1/3: Pulling latest code ===\n"
write_status "pulling" "git pull"
if ! git pull origin master; then
    write_status "error" "git pull" "\"git pull failed — check remote connectivity and branch status\""
    exit 1
fi

# Step 2: Docker build (only services with build configs)
printf "=== Step 2/3: Building Docker images ===\n"
write_status "building" "docker compose build"
if ! $COMPOSE build --no-cache; then
    write_status "error" "docker compose build" "\"docker compose build failed — check Dockerfiles and build context\""
    exit 1
fi

# Step 3: Restart app containers with new images
printf "=== Step 3/3: Restarting app containers ===\n"
write_status "restarting" "docker compose restart"
printf "Recreating services: %s\n" "$APP_SERVICES"
if ! $COMPOSE up -d --force-recreate $APP_SERVICES; then
    write_status "error" "docker compose up" "\"docker compose restart failed — check container logs\""
    exit 1
fi

printf "=== Update complete ===\n"
write_status "done" "complete"
