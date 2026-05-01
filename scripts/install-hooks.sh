#!/bin/bash
# Install local git hooks. Run this once after cloning the repo.
# Hooks live under .githooks/ (versioned in git) instead of .git/hooks/
# (not versioned) so they survive `git clone` and stay in sync with the
# code they protect.

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

git config core.hooksPath .githooks
chmod +x .githooks/* 2>/dev/null || true

echo "==> git hooks installed (.githooks/)"
echo "    pre-commit will run backend regression tests."
echo "    Skip once with: git commit --no-verify"
