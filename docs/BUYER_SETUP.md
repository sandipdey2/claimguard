# ClaimGuard - buyer setup guide

Time needed: about 15 minutes locally, or about 40 minutes to Azure. You need:

- Python 3.13;
- a gpt-4o-mini endpoint: OpenAI or another OpenAI-compatible gateway, or Azure OpenAI;
- for Azure only, an Azure subscription.

## 1. Install
```bash
git clone https://github.com/sandipdey2/claimguard && cd claimguard
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m claimguard verify-snapshot                      # checks the bundled public-data snapshot
python -m pytest -q && python scripts/verify_mcp.py       # offline: mock LLM, MCP over stdio + HTTP
```

## 2. Add your keys (never commit them)
```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```
Edit the file as follows:

- **OpenAI-compatible gateway:** set `CG_LLM_PROVIDER = "vocareum"` (the name of the OpenAI-compatible mode), `OPENAI_API_KEY`, and `OPENAI_API_BASE` (`https://api.openai.com/v1` for OpenAI).
- **Azure:** set `CG_LLM_PROVIDER = "azure"` and the `AZURE_OPENAI_*` lines.
- **Always:** set `CG_RECEIPT_KEY` to a long random string. Receipts verify only with the same key.

## 3. Run
```bash
streamlit run app.py                       # UI; saved live runs open even without a key
python scripts/live_run.py MN25-45854      # one live run on a published case (~$0.004)
uvicorn api.main:app --port 8000           # REST API; send X-API-Key = CG_API_KEY
docker compose up --build                  # app + API + HTTP MCP server (secrets from .env)
```

## 4. Refresh data / retrain
```bash
python scripts/fetch_data.py               # downloads the public sources into data/raw/, rebuilds data/snapshot + checksums
python scripts/train_models.py             # P3 + P4 models and P2 statistics -> eval/*.json
python scripts/run_eval.py                 # retrieval, gate mutation, injection, live-run quality -> eval/summary.json
python scripts/garden.py                   # recurring failure patterns -> eval/garden_report.json (propose-only)
```

## 5. Deploy to Azure
Follow [AZURE_DEPLOY.md](AZURE_DEPLOY.md) (`azd provision`, Key Vault secrets, `scripts/azure_search_index.py --push`, `azd deploy`).

## 6. Add CI
Copy `ci/ci.yml` to `.github/workflows/ci.yml` in the GitHub web UI (see `ci/README.md`).

## Responsibilities that stay with you

- Only de-identified text may be pasted. PHI detection is regex-based, and the app blocks denial text that looks like it contains identifiers.
- A qualified human must review and sign off every draft. ClaimGuard never files or sends anything.
- Before commercial use, check the NY DFS portal terms. Do not enable LCD indexing in a product you redistribute, because of the AMA CPT terms.
- The risk signals describe past published California reviews; they are not a prediction for an individual appeal.
