#!/usr/bin/env bash
# ship.sh — Commit, push, and rebuild Docker in one command.
#
# Usage:
#   ./scripts/ship.sh "Phase 32: Performance + Calendar"
#   ./scripts/ship.sh                # auto-generates message from staged diff
#
# What it does:
#   1. Stages all changes (git add -A)
#   2. Commits with Co-Authored-By tag
#   3. Pushes to origin
#   4. Rebuilds Docker images (no cache)
#   5. Restarts all containers
#
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

# ── Colors ──
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

step() { echo -e "\n${CYAN}▸ $1${NC}"; }
ok()   { echo -e "${GREEN}✓ $1${NC}"; }

# ── 1. Check for changes ──
if git diff --quiet && git diff --cached --quiet && [ -z "$(git ls-files --others --exclude-standard)" ]; then
  echo -e "${YELLOW}No changes to commit. Skipping commit/push.${NC}"
  SKIP_COMMIT=true
else
  SKIP_COMMIT=false
fi

# ── 2. Commit ──
if [ "$SKIP_COMMIT" = false ]; then
  step "Staging all changes..."
  git add -A

  # Use provided message or generate one
  if [ -n "${1:-}" ]; then
    MSG="$1"
  else
    MSG="Update $(date +%Y-%m-%d)"
  fi

  step "Committing: ${MSG}"
  git commit -m "$(cat <<EOF
${MSG}

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
  ok "Committed"

  # ── 3. Push ──
  step "Pushing to origin..."
  git push
  ok "Pushed"
fi

# ── 4. Rebuild Docker ──
step "Rebuilding Docker images (no cache)..."
docker compose build --no-cache
ok "Images rebuilt"

# ── 5. Restart containers ──
step "Restarting containers..."
docker compose down
docker compose up -d
ok "Containers up"

# ── 6. Summary ──
echo ""
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo -e "${GREEN}  Ship complete! 🚀${NC}"
if [ "$SKIP_COMMIT" = false ]; then
  echo -e "  Commit: ${MSG}"
fi
echo -e "  Containers: $(docker compose ps --format '{{.Name}}' | wc -l) running"
echo -e "${GREEN}════════════════════════════════════════${NC}"
