#!/bin/bash
# End-of-day shutdown — commits any uncommitted work, pushes to GitHub,
# stops containers cleanly. Containers will auto-restart on next boot
# (restart: unless-stopped in docker-compose.yml), so the platform comes
# back up whenever Docker Desktop starts.

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

export PATH="/c/Program Files/Docker/Docker/resources/bin:$PATH"

echo "==> 1/3 Checking for uncommitted work..."
if [ -n "$(git status --porcelain)" ]; then
  echo "  uncommitted changes detected:"
  git status --short
  echo
  echo "  REVIEW THE LIST ABOVE. To commit, run manually:"
  echo "      git add -A"
  echo "      git commit -m 'wip: end of day'"
  echo "      git push"
  echo "  (NOT auto-committing — you should review changes first)"
else
  echo "  working tree clean"
fi

echo "==> 2/3 Pushing committed work to GitHub..."
ahead=$(git rev-list --count origin/main..main 2>/dev/null || echo "0")
if [ "$ahead" -gt 0 ]; then
  git push origin main
  echo "  pushed $ahead commit(s)"
else
  echo "  remote already in sync"
fi

echo "==> 3/3 Stopping containers (volumes preserved)..."
docker compose stop
echo "  stopped — they will auto-restart when Docker Desktop boots"
echo
echo "Безопасно закрывать компьютер."
