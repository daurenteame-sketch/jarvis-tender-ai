# GitHub Actions CI — how to enable

The CI workflow file lives in `docs/ci/github-actions.yml` (not
`.github/workflows/`) because the current GitHub Personal Access Token
used by `git push` does NOT have the `workflow` scope.

The local protections still work without GitHub Actions:
- `bash scripts/start.sh` runs `pytest` as step 2/6 every morning
- `.githooks/pre-commit` runs `pytest` before every commit
- `cd backend && python -m pytest tests/` on demand

To turn cloud CI on:

## Option A — Update token (recommended)
1. https://github.com/settings/tokens — tick **workflow** scope
2. Locally:
   ```bash
   mkdir -p .github/workflows
   cp docs/ci/github-actions.yml .github/workflows/ci.yml
   git add .github/workflows/ci.yml
   git commit -m "ci: enable Actions workflow"
   git push
   ```

## Option B — Use GitHub web UI (no token change needed)
1. Repo on GitHub → **Actions** tab → **set up a workflow yourself**
2. Paste contents of `docs/ci/github-actions.yml`
3. Commit through the web UI
4. `git pull` locally
