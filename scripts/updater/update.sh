#!/bin/bash
# Self-update script — runs inside the updater sidecar container.
# Pulls latest code, rebuilds Docker images, and restarts all containers.
#
# KEY INSIGHT: This script runs inside a container with a Docker socket mount.
# Docker compose commands talk to the HOST Docker daemon, but relative bind
# mount paths (./monitoring/...) resolve to /project/... which doesn't exist
# on the host. We avoid this by:
#   1. Using -f docker-compose.yml + docker-compose.override.yml (the override
#      contains AppArmor workaround + frontend build args for the host)
#   2. Only recreating app services (backend, celery, frontend) which have NO
#      relative bind mounts in the base compose file
#   3. Skipping monitoring services (prometheus, alertmanager, grafana) which
#      use external images and don't need updating during code deploys

set -e

PROJECT_DIR="${COMPOSE_PROJECT_DIR:-/project}"
STATUS_FILE="/tmp/update_status.json"

# Compose command: include override for AppArmor workaround + frontend build args.
# The override is git-ignored and host-specific (contains security_opt + NEXT_PUBLIC_API_URL).
COMPOSE="docker compose -f ${PROJECT_DIR}/docker-compose.yml"
if [ -f "${PROJECT_DIR}/docker-compose.override.yml" ]; then
    COMPOSE="${COMPOSE} -f ${PROJECT_DIR}/docker-compose.override.yml"
fi

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

# Step 2: Docker build
# Backend + celery use standard docker compose build.
# Frontend needs buildx --allow security.insecure to bypass Proxmox AppArmor
# blocking Node.js child_process.spawn during `npm run build`.
printf "=== Step 2/4: Building backend image ===\n"
write_status "building" "docker compose build (backend)"
if ! $COMPOSE build --no-cache backend celery-worker celery-beat; then
    write_status "error" "docker compose build" "\"backend build failed — check Dockerfile.backend\""
    exit 1
fi

# Ensure buildx builder with security.insecure entitlement exists
BUILDER_NAME="insecure-builder"
if ! docker buildx inspect "$BUILDER_NAME" >/dev/null 2>&1; then
    printf "Creating buildx builder '%s' with insecure entitlement...\n" "$BUILDER_NAME"
    docker buildx create --name "$BUILDER_NAME" --buildkitd-flags '--allow-insecure-entitlement security.insecure' --use
else
    docker buildx use "$BUILDER_NAME"
fi

# Read NEXT_PUBLIC_API_URL from override file if present
NEXT_PUBLIC_API_URL=""
if [ -f "${PROJECT_DIR}/docker-compose.override.yml" ]; then
    NEXT_PUBLIC_API_URL=$(grep -A1 'NEXT_PUBLIC_API_URL' "${PROJECT_DIR}/docker-compose.override.yml" | tail -1 | sed 's/.*: *//' | tr -d ' "'"'" || true)
fi

printf "=== Step 3/4: Building frontend image (buildx) ===\n"
write_status "building" "docker buildx build (frontend)"
if ! docker buildx build \
    --builder "$BUILDER_NAME" \
    --allow security.insecure \
    ${NEXT_PUBLIC_API_URL:+--build-arg "NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}"} \
    --load \
    -t boz-weather-trader-frontend \
    -f "${PROJECT_DIR}/frontend/Dockerfile" \
    "${PROJECT_DIR}/frontend"; then
    write_status "error" "docker buildx build" "\"frontend build failed — check frontend/Dockerfile\""
    exit 1
fi

# Step 4: Restart app containers with new images
printf "=== Step 4/4: Restarting app containers ===\n"
write_status "restarting" "docker compose restart"
printf "Recreating services: %s\n" "$APP_SERVICES"
if ! $COMPOSE up -d --force-recreate $APP_SERVICES; then
    write_status "error" "docker compose up" "\"docker compose restart failed — check container logs\""
    exit 1
fi

printf "=== Update complete ===\n"
write_status "done" "complete"
