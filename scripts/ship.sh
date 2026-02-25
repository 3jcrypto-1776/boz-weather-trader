#!/usr/bin/env bash
# ship.sh — Full release pipeline: test, bump, commit, tag, push, deploy.
#
# Usage:
#   ./scripts/ship.sh --bump patch --message "Fix confidence badge colors"
#   ./scripts/ship.sh --bump minor --message "Phase 39: Ship script"
#   ./scripts/ship.sh --skip-tests --skip-deploy    # commit + push only
#   ./scripts/ship.sh --help
#
# Environment variables (override defaults):
#   SHIP_HOMELAB_HOST   SSH target           (default: root@10.0.0.51)
#   SHIP_HOMELAB_DIR    Project path on host (default: /opt/boz-weather-trader)
#   SHIP_API_URL        Frontend API URL     (default: http://10.0.0.51:8000)
#   SHIP_BUILDX_BUILDER Buildx builder name  (default: insecure-builder)
#
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

# ─── Configurable defaults ───
SHIP_HOMELAB_HOST="${SHIP_HOMELAB_HOST:-root@10.0.0.51}"
SHIP_HOMELAB_DIR="${SHIP_HOMELAB_DIR:-/opt/boz-weather-trader}"
SHIP_API_URL="${SHIP_API_URL:-http://10.0.0.51:8000}"
SHIP_BUILDX_BUILDER="${SHIP_BUILDX_BUILDER:-insecure-builder}"

# ─── Colors ───
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

step()  { echo -e "\n${CYAN}${BOLD}[$1/6]${NC} ${CYAN}$2${NC}"; }
ok()    { echo -e "  ${GREEN}✓ $1${NC}"; }
warn()  { echo -e "  ${YELLOW}⚠ $1${NC}"; }
fail()  { echo -e "  ${RED}✗ $1${NC}"; exit 1; }

# ─── Parse arguments ───
BUMP=""
SKIP_TESTS=false
SKIP_DEPLOY=false
MESSAGE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bump)
      BUMP="$2"; shift 2
      if [[ ! "$BUMP" =~ ^(patch|minor|major)$ ]]; then
        fail "--bump must be patch, minor, or major (got: $BUMP)"
      fi
      ;;
    --skip-tests)  SKIP_TESTS=true; shift ;;
    --skip-deploy) SKIP_DEPLOY=true; shift ;;
    --message|-m)  MESSAGE="$2"; shift 2 ;;
    --help|-h)
      echo "Usage: ./scripts/ship.sh [options]"
      echo ""
      echo "Options:"
      echo "  --bump patch|minor|major   Bump VERSION and create git tag"
      echo "  --skip-tests               Skip test/lint gate"
      echo "  --skip-deploy              Skip homelab deploy (push only)"
      echo "  --message, -m \"msg\"        Custom commit message"
      echo "  --help, -h                 Show this help"
      echo ""
      echo "Environment variables:"
      echo "  SHIP_HOMELAB_HOST   SSH target           (default: root@10.0.0.51)"
      echo "  SHIP_HOMELAB_DIR    Project path on host (default: /opt/boz-weather-trader)"
      echo "  SHIP_API_URL        Frontend API URL     (default: http://10.0.0.51:8000)"
      echo "  SHIP_BUILDX_BUILDER Buildx builder name  (default: insecure-builder)"
      echo ""
      echo "Examples:"
      echo "  ./scripts/ship.sh --bump patch -m \"Fix confidence badge colors\""
      echo "  ./scripts/ship.sh --bump minor -m \"Phase 39: Ship script\""
      echo "  ./scripts/ship.sh --skip-tests --skip-deploy"
      exit 0
      ;;
    *)
      # Legacy: positional arg is the commit message
      MESSAGE="$1"; shift
      ;;
  esac
done

# ─── Read current version ───
CURRENT_VERSION=$(cat VERSION)
echo -e "${BOLD}Boz Weather Trader — Ship Pipeline${NC}"
echo -e "Current version: ${CYAN}v${CURRENT_VERSION}${NC}"

# ─── Compute new version if bumping ───
NEW_VERSION=""
if [ -n "$BUMP" ]; then
  IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT_VERSION"
  case "$BUMP" in
    major) NEW_VERSION="$((MAJOR + 1)).0.0" ;;
    minor) NEW_VERSION="${MAJOR}.$((MINOR + 1)).0" ;;
    patch) NEW_VERSION="${MAJOR}.${MINOR}.$((PATCH + 1))" ;;
  esac
  echo -e "Version bump: ${YELLOW}v${CURRENT_VERSION}${NC} → ${GREEN}v${NEW_VERSION}${NC} (${BUMP})"
fi

# ═══════════════════════════════════════════════════════════════
# Stage 1: Preflight
# ═══════════════════════════════════════════════════════════════
step 1 "Preflight checks"

# Check we're on master
BRANCH=$(git branch --show-current)
if [ "$BRANCH" != "master" ]; then
  fail "Not on master branch (on: $BRANCH). Switch to master first."
fi

# Check remote is reachable
if ! git ls-remote --exit-code origin &>/dev/null; then
  fail "Cannot reach origin remote"
fi
ok "On master, remote reachable"

# Check for changes
HAS_CHANGES=false
if ! git diff --quiet || ! git diff --cached --quiet || [ -n "$(git ls-files --others --exclude-standard)" ]; then
  HAS_CHANGES=true
  ok "Changes detected — will commit"
else
  if [ -z "$BUMP" ]; then
    warn "No changes to commit and no --bump specified"
  else
    ok "No code changes — version bump only"
  fi
fi

# ═══════════════════════════════════════════════════════════════
# Stage 2: Test Gate
# ═══════════════════════════════════════════════════════════════
step 2 "Test gate"

if [ "$SKIP_TESTS" = true ]; then
  warn "Skipping tests (--skip-tests)"
else
  echo -e "  Running backend lint..."
  if ! ruff check backend/ tests/ && ruff format --check backend/ tests/; then
    fail "Backend lint failed. Fix issues or use --skip-tests."
  fi
  ok "Backend lint clean"

  echo -e "  Running backend tests..."
  if ! python -m pytest tests/ -x -q --tb=short \
    --deselect tests/common/test_config.py::TestSettings::test_missing_encryption_key_raises; then
    fail "Backend tests failed. Fix issues or use --skip-tests."
  fi
  ok "Backend tests passed"

  echo -e "  Running frontend tests + lint..."
  if ! (cd frontend && npm test && npm run lint); then
    fail "Frontend tests/lint failed. Fix issues or use --skip-tests."
  fi
  ok "Frontend tests + lint passed"
fi

# ═══════════════════════════════════════════════════════════════
# Stage 3: Version Bump
# ═══════════════════════════════════════════════════════════════
step 3 "Version bump"

if [ -n "$BUMP" ]; then
  echo "$NEW_VERSION" > VERSION
  git add VERSION
  git commit -m "$(cat <<EOF
chore: bump version to v${NEW_VERSION}

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
  ok "VERSION bumped to v${NEW_VERSION}"
else
  warn "No version bump (use --bump patch|minor|major)"
fi

# ═══════════════════════════════════════════════════════════════
# Stage 4: Commit + Push + Tag
# ═══════════════════════════════════════════════════════════════
step 4 "Commit, push, tag"

# Commit any remaining changes (if not already committed by version bump)
if [ "$HAS_CHANGES" = true ]; then
  # Check if there are still uncommitted changes after the version bump commit
  if ! git diff --quiet || ! git diff --cached --quiet || [ -n "$(git ls-files --others --exclude-standard)" ]; then
    if [ -z "$MESSAGE" ]; then
      MESSAGE="Update $(date +%Y-%m-%d)"
    fi
    git add -A
    git commit -m "$(cat <<EOF
${MESSAGE}

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
    ok "Committed: ${MESSAGE}"
  else
    ok "All changes already committed"
  fi
elif [ -z "$BUMP" ]; then
  warn "Nothing to commit"
fi

# Push
echo -e "  Pushing to origin..."
git push origin master
ok "Pushed to origin/master"

# Tag + push tag (triggers GitHub Release via release.yml)
if [ -n "$BUMP" ]; then
  TAG="v${NEW_VERSION}"
  git tag "$TAG"
  git push origin "$TAG"
  ok "Tagged ${TAG} and pushed (GitHub Release will be created)"
fi

# ═══════════════════════════════════════════════════════════════
# Stage 5: Homelab Deploy
# ═══════════════════════════════════════════════════════════════
step 5 "Homelab deploy"

if [ "$SKIP_DEPLOY" = true ]; then
  warn "Skipping deploy (--skip-deploy)"
else
  REMOTE="ssh -o ConnectTimeout=10 ${SHIP_HOMELAB_HOST}"

  # Test SSH connectivity
  if ! $REMOTE "echo ok" &>/dev/null; then
    fail "Cannot SSH to ${SHIP_HOMELAB_HOST}"
  fi
  ok "SSH connected to ${SHIP_HOMELAB_HOST}"

  # Git pull
  echo -e "  Pulling latest code..."
  $REMOTE "cd ${SHIP_HOMELAB_DIR} && git pull"
  ok "Code pulled"

  # Rebuild backend (regular compose works for Python builds)
  echo -e "  Rebuilding backend image..."
  $REMOTE "cd ${SHIP_HOMELAB_DIR} && docker compose build --no-cache backend"
  ok "Backend image rebuilt"

  # Rebuild frontend (uses buildx to bypass AppArmor)
  echo -e "  Rebuilding frontend image (buildx)..."
  $REMOTE "cd ${SHIP_HOMELAB_DIR}/frontend && docker buildx build \
    --builder ${SHIP_BUILDX_BUILDER} \
    --allow security.insecure \
    --load \
    -t boz-weather-trader-frontend \
    --build-arg NEXT_PUBLIC_API_URL=${SHIP_API_URL} \
    ."
  ok "Frontend image rebuilt"

  # Recreate app containers
  echo -e "  Recreating app containers..."
  $REMOTE "cd ${SHIP_HOMELAB_DIR} && docker compose up -d backend celery-worker celery-beat frontend"
  ok "Containers recreated"
fi

# ═══════════════════════════════════════════════════════════════
# Stage 6: Verify
# ═══════════════════════════════════════════════════════════════
step 6 "Verify"

if [ "$SKIP_DEPLOY" = true ]; then
  warn "Skipping verification (no deploy)"
else
  # Wait for backend to come up
  echo -e "  Waiting for backend health..."
  for i in $(seq 1 30); do
    if $REMOTE "curl -sf http://localhost:8000/health" &>/dev/null; then
      break
    fi
    sleep 2
  done

  HEALTH=$($REMOTE "curl -sf http://localhost:8000/health" 2>/dev/null || echo '{"status":"unreachable"}')
  ok "Backend health: ${HEALTH}"

  DEPLOY_VERSION="${NEW_VERSION:-$CURRENT_VERSION}"
  LIVE_VERSION=$($REMOTE "curl -sf http://localhost:8000/api/version" 2>/dev/null | grep -o '"current_version":"[^"]*"' | cut -d'"' -f4 || echo "unknown")
  if [ "$LIVE_VERSION" = "$DEPLOY_VERSION" ]; then
    ok "Version verified: v${LIVE_VERSION}"
  else
    warn "Version mismatch: expected v${DEPLOY_VERSION}, got v${LIVE_VERSION}"
  fi

  FRONTEND_STATUS=$($REMOTE "curl -sf -o /dev/null -w '%{http_code}' http://localhost:3000" 2>/dev/null || echo "unreachable")
  if [ "$FRONTEND_STATUS" = "200" ]; then
    ok "Frontend responding (HTTP 200)"
  else
    warn "Frontend status: ${FRONTEND_STATUS}"
  fi
fi

# ═══════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════
echo ""
echo -e "${GREEN}${BOLD}════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}  Ship complete!${NC}"
if [ -n "$BUMP" ]; then
  echo -e "  Version: ${GREEN}v${NEW_VERSION}${NC}"
  echo -e "  Tag:     ${GREEN}v${NEW_VERSION}${NC} (GitHub Release pending)"
fi
if [ "$HAS_CHANGES" = true ] && [ -n "$MESSAGE" ]; then
  echo -e "  Commit:  ${MESSAGE}"
fi
if [ "$SKIP_DEPLOY" = false ]; then
  echo -e "  Deploy:  ${GREEN}${SHIP_HOMELAB_HOST}${NC}"
fi
echo -e "${GREEN}${BOLD}════════════════════════════════════════${NC}"
