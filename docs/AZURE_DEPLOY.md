# Deploying ClaimGuard to Azure (Azure AI Foundry + Container Apps)

**Status: not deployed yet.** What has been checked offline:

- `infra/main.bicep` (with `infra/resources.bicep`) **builds and lints clean** with Bicep CLI 0.49.2.
- The Azure adapters (Azure OpenAI, AI Search, Blob, Prompt Shields) pass tests against mocked endpoints (`tests/test_azure_adapters.py`).

No Azure resource has been created. A deployment needs your own subscription and sign-in. Never paste a password into chat or into this repo: sign in only through the `azd`/`az` browser login.

## What gets provisioned

| Resource | Purpose | Setting |
|---|---|---|
| Azure AI Foundry resource (`Microsoft.CognitiveServices/accounts`, kind AIServices) + project `claimguard` | model hosting; also serves Content Safety Prompt Shields | local (key) auth disabled, Entra ID only |
| Deployment `gpt-4o-mini` (model version 2024-07-18, GlobalStandard) | the only LLM ClaimGuard calls | 30k tokens per minute by default (`openAiCapacity`) |
| Azure AI Search (basic, semantic free tier) | hybrid keyword + vector + semantic search over NCD chunks | Entra ID or key |
| Storage account + `receipts` container | signed receipts | no public access, no shared keys |
| Key Vault (RBAC) | `CG-RECEIPT-KEY`, `CG-API-KEY` | Container App reads them via Key Vault references |
| Container Registry + Container Apps environment + app | Streamlit app on port 8501, scaling 0-3 replicas | user-assigned managed identity |
| Log Analytics + Application Insights | OpenTelemetry traces (`APPLICATIONINSIGHTS_CONNECTION_STRING`) | 30 days retention |

The managed identity gets these roles:

- Cognitive Services OpenAI User and Cognitive Services User (Foundry);
- Search Index Data Reader;
- Storage Blob Data Contributor;
- Key Vault Secrets User;
- AcrPull.

Your user (`principalId`) gets Key Vault Secrets Officer and Search Index Data Contributor, so you can load secrets and the index.

## Steps

```bash
# 0. tools: Azure CLI, Azure Developer CLI (azd), Docker not required (remote build)
az login                       # opens the browser; use your own account
azd auth login

# 1. provision + deploy (asks for an environment name, subscription and region)
#    pick a region where gpt-4o-mini GlobalStandard is available, e.g. eastus2 or swedencentral
azd env set AZURE_PRINCIPAL_ID $(az ad signed-in-user show --query id -o tsv)
azd provision                  # creates the resource group and everything above

# 2. secrets (generated locally, stored only in Key Vault)
KV=$(azd env get-value AZURE_KEY_VAULT_URL | sed 's#https://##; s#.vault.azure.net/##')
az keyvault secret set --vault-name $KV --name CG-RECEIPT-KEY --value "$(python -c 'import secrets;print(secrets.token_hex(32))')" -o none
az keyvault secret set --vault-name $KV --name CG-API-KEY --value "$(python -c 'import secrets;print(secrets.token_urlsafe(24))')" -o none

# 3. search index (1,034 NCD chunks with 256-d vectors), using your Entra login
export AZURE_SEARCH_ENDPOINT=$(azd env get-value AZURE_SEARCH_ENDPOINT) AZURE_SEARCH_INDEX=claimguard-policy
python scripts/azure_search_index.py --push

# 4. build + deploy the container (remote ACR build of the Dockerfile)
azd deploy
azd env get-value SERVICE_APP_URL
```

## Verify

1. Open the app URL. The sidebar should show `LLM: gpt-4o-mini via azure · connected`, with the Azure adapters ai_search, blob, content_safety and app_insights ✅.
2. Run a published case. The Checks & receipt tab should show 12 PASS and a receipt `key_id` of `CG_RECEIPT_KEY:…`.
3. In Application Insights, open **Transaction search** and look for spans named `llm.*` and `mcp.tools/call.*`.
4. Check the Blob container `receipts`, which should hold one JSON per API run.

## Local run against the Azure resources

Set `CG_LLM_PROVIDER=azure`, `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini`. Sign in with `az login`; `DefaultAzureCredential` is used when no `AZURE_OPENAI_API_KEY` is set. Then run `python scripts/live_run.py MN25-45854`.

## Cost notes (check current prices before deploying)

- **gpt-4o-mini:** a run uses about 8-10 calls and 15-25k tokens, roughly $0.003-0.005 at list price.
- **AI Search Basic:** a fixed monthly charge, the largest fixed cost. Delete the resource group (`azd down --purge`) when you are done.
- **Container Apps:** scales to zero when idle.

## Not covered

- Private networking (VNet, private endpoints) and the API as its own Container App (run `uvicorn api.main:app` locally or add a second app).
- The HTTP MCP server as a sidecar. Set `CG_MCP_URL` and `CG_MCP_TOKEN`; the default is a stdio subprocess inside the app container.
- Region and quota checks. Run `az cognitiveservices usage list -l <region>` first.
