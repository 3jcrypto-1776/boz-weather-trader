Ship the current changes by performing these steps in order:

1. Run `git status` to check for changes
2. If there are changes: `git add -A` then commit. Use the message provided in `$ARGUMENTS` if given, otherwise generate one from the diff. Always append the Co-Authored-By trailer:
   Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
3. Push to origin: `git push`
4. Rebuild Docker images: `docker compose build --no-cache`
5. Restart containers: `docker compose down && docker compose up -d`
6. Run `docker compose ps` and report a summary

If there are no changes to commit, skip steps 1-3 and go straight to Docker rebuild.
