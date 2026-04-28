#!/bin/bash
# Shared helpers used by start.sh / stop.sh / smoke-test.sh / backup-db.sh.
# Source this file: `source "$(dirname "$0")/_lib.sh"` at the top of each script.

# Locate the docker binary even when the parent shell is PowerShell, cmd.exe,
# or a fresh Git Bash that didn't pick up the Docker Desktop PATH entry.
# Tries (in order):
#   1) docker already on PATH
#   2) standard Docker Desktop install path (Program Files)
#   3) older Docker Desktop install path (LocalAppData)
# Sets a global $DOCKER variable. Exits with a clear message if not found.
locate_docker() {
  if command -v docker >/dev/null 2>&1; then
    DOCKER="docker"
    return 0
  fi
  for cand in \
    "/c/Program Files/Docker/Docker/resources/bin/docker.exe" \
    "/c/Program Files/Docker/Docker/resources/bin/docker" \
    "$LOCALAPPDATA/Docker/Docker/resources/bin/docker.exe" \
    "/c/ProgramData/DockerDesktop/version-bin/docker.exe" \
  ; do
    if [ -x "$cand" ]; then
      DOCKER="$cand"
      # Also prepend the bin dir to PATH so child processes inherit it
      export PATH="$(dirname "$cand"):$PATH"
      return 0
    fi
  done
  echo "ERROR: docker not found." >&2
  echo "Looked in standard install locations and PATH." >&2
  echo "Make sure Docker Desktop is installed and running." >&2
  exit 1
}

# Wrap docker compose so callers don't have to remember to use $DOCKER.
dc() {
  "$DOCKER" compose "$@"
}
