---
name: ship
description: Commit all changes, push to origin, and rebuild Docker containers
disable-model-invocation: true
argument-hint: "[commit message]"
---

## Current git status
!`git status --short`

## Instructions

Ship the current changes by performing these steps in order:

1. **Stage all changes**: `git add -A`
2. **Commit** with the message provided in `$ARGUMENTS`. If no message is provided, generate an appropriate commit message based on the staged diff. Always append:
   ```
   Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
   ```
3. **Push** to origin: `git push`
4. **Rebuild Docker images** (no cache): `docker compose build --no-cache`
5. **Restart containers**: `docker compose down && docker compose up -d`
6. **Verify**: Run `docker compose ps` and confirm all containers are running

If there are no changes to commit, skip steps 1-3 and go straight to the Docker rebuild.

Report a summary when done: commit hash, number of files changed, and number of running containers.
