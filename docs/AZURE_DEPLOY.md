# Deploying ClaimGuard to Azure (Azure AI Foundry + Container Apps)

**Status: live on Azure (Udacity Vocareum lab subscription, westus), deployed 2026-11-15.**

| | URL |
|---|---|
| Streamlit app | https://ca-cg-awluz7evtffc4.redmushroom-2296ed24.westus.azurecontainerapps.io |
| FastAPI service (`X-API-Key`) | https://ca-cg-api-awluz7evtffc4.redmushroom-2296ed24.westus.azurecontainerapps.io (`GET /health` is open; every other route needs the key) |

## The lab deployment (what was actually used)

The lab account can't create resource groups, so it used the RG-scoped entry point [`infra/lab/main.bicep`](../infra/lab/main.bicep), which calls the same `infra/resources.bicep` as `azd`. Policies, role assignments and providers were probed first with `az deployment group what-if`; no Azure Policy assignment applied to the RG and the account could create role assignments, so the managed-identity design was kept unchanged (no keys in the app).

| Service | Status | Notes |
|---|---|---|
| Azure AI Foundry resource (AIServices) + project `claimguard` | deployed | Entra ID only (local auth disabled) |
| gpt-4o-mini deployment (2024-07-18) | deployed as **DataZoneStandard**, 30k TPM | GlobalStandard is refused with `ServiceModelDeprecating` ("…is in deprecating state and cannot be used for new deployments") and Standard with `ServiceModelDeprecated` ("…has been deprecated since 03/31/2026"). `openAiSku` now defaults to DataZoneStandard. |
| Azure AI Search | deployed, **Free** tier | index `claimguard-policy`, 1,034 NCD chunks with 256-d vectors, pushed with `scripts/azure_search_index.py --push`; the semantic ranker is off on Free |
| Storage + `receipts` container | deployed | API receipts are written here via managed identity |
| Key Vault (RBAC) | deployed, purge protection off for the lab | `CG-RECEIPT-KEY`, `CG-API-KEY`, read by the apps as Key Vault references |
| Content Safety Prompt Shields | active (same Foundry endpoint) | |
| ACR (Basic) + `az acr build` | deployed | no Docker needed; image `claimguard:d4fa1f7` |
| Container Apps environment + 2 apps | deployed | Streamlit (port 8501) and FastAPI (port 8000), consumption plan, scale 0-3 / 0-2 |
| Log Analytics + Application Insights | deployed | |
| Blocked | none | Only the GlobalStandard/Standard model SKUs above were refused. |

Steps used (any value in angle brackets is yours; never paste keys into chat or the repo):

```bash
RG=<existing-rg>; SUB=<subscription name>
OID=<your Entra object id>            # Graph is blocked in the lab; the oid claim of `az account get-access-token` works
# 1. everything except the Container Apps (Key Vault secrets must exist before the apps reference them)
az deployment group create --subscription "$SUB" -g $RG -f infra/lab/main.bicep -p principalId=$OID deployApps=false
# 2. secrets (written from local files, never echoed)
az keyvault secret set --subscription "$SUB" --vault-name <kv> --name CG-RECEIPT-KEY --file <receipt-key-file> -o none
az keyvault secret set --subscription "$SUB" --vault-name <kv> --name CG-API-KEY --file <api-key-file> -o none
# 3. search index
AZURE_SEARCH_ENDPOINT=https://<search>.search.windows.net AZURE_SEARCH_API_KEY=<admin key, from az search admin-key show> \
  python scripts/azure_search_index.py --push
# 4. image, then the apps
az acr build --subscription "$SUB" -r <acr> -t claimguard:$(git rev-parse --short HEAD) --build-arg GIT_SHA=$(git rev-parse --short HEAD) .
az deployment group create --subscription "$SUB" -g $RG -f infra/lab/main.bicep -p principalId=$OID deployApps=true appImage=<acr>.azurecr.io/claimguard:<sha>
```

### Verification on the live Azure deployment (2026-11-15)

`GET /health`: `provider: azure`, adapters `azure_openai`, `ai_search`, `blob`, `content_safety`, `app_insights` and `key_vault` all true. The Streamlit URL returns 200.

Three real runs of case MN25-45854 through `POST /v1/appeals` on the Azure API (Foundry gpt-4o-mini, Azure AI Search, Prompt Shields, Blob receipts). All are reported, including the failed ones:

| Run | Request text | Status | Checks | Latency | LLM calls | Cost |
|---|---|---|---|---|---|---|
| 6624778b | API default (short) | not_finalized | 11/12, `red_team_pass` FAIL | 84.4 s (cold start) | 10 | $0.0054 |
| 072c6c63 | API default (short) | not_finalized | 11/12, `red_team_pass` FAIL | 40.0 s | 10 | $0.0045 |
| 2dba9a64 | full request (as in `scripts/live_run.py`) | awaiting_human_signoff | 12/12 PASS | 26.9 s | 8 | $0.0033 |

Each receipt has `provider: azure`, `model: gpt-4o-mini`, `git_sha: d4fa1f7` and key id `CG_RECEIPT_KEY:dcccbcd5`, and `/v1/receipts/verify` returned `valid: true`. A local run against the same Foundry deployment and Search index (`eval/logs/live_MN25-45854_40c47e8f.json`) also passed 12/12 (47.3 s, $0.0036). Open issue: with the short default API request the red-team reviewer failed the draft twice; the cause has not been investigated yet.

### Cost and teardown

Expected idle cost is about $5/month, mostly ACR Basic (about $0.17/day). AI Search Free is $0, both Container Apps scale to zero, and Log Analytics, Storage and Key Vault cost cents at this volume. Each appeal run costs about $0.003-0.005 in gpt-4o-mini tokens. Check current prices before relying on these numbers.

The lab RG itself can't be deleted, so delete the resources inside it (apps first, then the rest):

```bash
az resource list --subscription "$SUB" -g $RG --query "[?tags.app=='claimguard'].id" -o tsv | xargs -r az resource delete --subscription "$SUB" --ids
az cognitiveservices account purge --subscription "$SUB" -g $RG -l westus -n <foundry-name>   # Foundry is soft-deleted for 48 h
az keyvault purge --subscription "$SUB" -n <kv-name>                                           # Key Vault is soft-deleted for 7 days
```

Run the first command twice if dependencies make some deletes fail the first time. Vocareum lab subscriptions can be reset or expire when the lab session or course ends, which deletes everything in them.

## What gets provisioned

| Resource | Purpose | Setting |
|---|---|---|
| Azure AI Foundry resource (`Microsoft.CognitiveServices/accounts`, kind AIServices) + project `claimguard` | model hosting; also serves Content Safety Prompt Shields | local (key) auth disabled, Entra ID only |
| Deployment `gpt-4o-mini` (model version 2024-07-18, DataZoneStandard; `openAiSku`) | the only LLM ClaimGuard calls | 30k tokens per minute by default (`openAiCapacity`) |
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
#    pick a region where gpt-4o-mini DataZoneStandard is available, e.g. westus, eastus2 or swedencentral
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

- Private networking (VNet, private endpoints). The API now runs as its own Container App (`deployApi`, on by default).
- The HTTP MCP server as a sidecar. Set `CG_MCP_URL` and `CG_MCP_TOKEN`; the default is a stdio subprocess inside the app container.
- Region and quota checks. Run `az cognitiveservices usage list -l <region>` first.
