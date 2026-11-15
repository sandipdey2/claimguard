# Adding CI (one-time, in the GitHub web UI)

The automation token that pushes this repo has no `workflow` scope, so it cannot create `.github/workflows/*`. Add the workflow yourself:

1. Open https://github.com/sandipdey2/claimguard, click **Add file → Create new file**.
2. Name it `.github/workflows/ci.yml` (typing the slashes creates the folders).
3. Paste the contents of [`ci/ci.yml`](ci.yml) and click **Commit changes** on `main`.
4. Open the **Actions** tab: the `CI` workflow runs pytest (mock LLM, offline), the MCP stdio + HTTP check, ruff, mypy, the secret scan, and an offline Bicep build + lint. No secrets are needed.
