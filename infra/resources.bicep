// All ClaimGuard resources in one resource group. Managed identity everywhere; no keys are output.
param location string
param tags object
@minLength(13)
@maxLength(13)
param token string
param appImage string
param openAiCapacity int
param principalId string

var roles = {
  openAiUser: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'      // Cognitive Services OpenAI User
  cogUser: 'a97b65f3-24c7-4388-baec-2e87135dc908'         // Cognitive Services User (Content Safety Prompt Shields)
  searchIndexReader: '1407120a-92aa-4202-b7e9-c0e197c71c8f' // Search Index Data Reader
  searchIndexContributor: '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
  blobContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe' // Storage Blob Data Contributor
  kvSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
  kvSecretsOfficer: 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-claimguard-${token}'
  location: location
  tags: tags
}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-claimguard-${token}'
  location: location
  tags: tags
  properties: { sku: { name: 'PerGB2018' }, retentionInDays: 30 }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-claimguard-${token}'
  location: location
  tags: tags
  kind: 'web'
  properties: { Application_Type: 'web', WorkspaceResourceId: logs.id }
}

// Azure AI Foundry resource (AIServices) + project + gpt-4o-mini deployment. The same endpoint serves Content Safety.
resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: 'aif-claimguard-${token}'
  location: location
  tags: tags
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: 'aif-claimguard-${token}'
    allowProjectManagement: true
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: foundry
  name: 'claimguard'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: { displayName: 'ClaimGuard', description: 'Cited appeal drafts and denial-risk briefs (gpt-4o-mini)' }
}

resource gpt4oMini 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundry
  name: 'gpt-4o-mini'
  sku: { name: 'GlobalStandard', capacity: openAiCapacity }
  properties: {
    model: { format: 'OpenAI', name: 'gpt-4o-mini', version: '2024-07-18' }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}

resource search 'Microsoft.Search/searchServices@2023-11-01' = {
  name: 'srch-claimguard-${token}'
  location: location
  tags: tags
  sku: { name: 'basic' }
  properties: {
    replicaCount: 1
    partitionCount: 1
    semanticSearch: 'free'
    authOptions: { aadOrApiKey: { aadAuthFailureMode: 'http401WithBearerChallenge' } }
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'stcg${token}'
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource receipts 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'receipts'
  properties: { publicAccess: 'None' }
}

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kv-cg-${token}'
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    enablePurgeProtection: true
  }
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'crcg${token}'
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

// ---- role assignments for the app's managed identity (and the deploying user on Key Vault)
var mi = identity.properties.principalId
resource raOpenAi 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, identity.id, roles.openAiUser)
  properties: { principalId: mi, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.openAiUser) }
}
resource raCog 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, identity.id, roles.cogUser)
  properties: { principalId: mi, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.cogUser) }
}
resource raSearch 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, identity.id, roles.searchIndexReader)
  properties: { principalId: mi, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchIndexReader) }
}
resource raBlob 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, identity.id, roles.blobContributor)
  properties: { principalId: mi, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.blobContributor) }
}
resource raKv 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: vault
  name: guid(vault.id, identity.id, roles.kvSecretsUser)
  properties: { principalId: mi, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.kvSecretsUser) }
}
resource raAcr 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: registry
  name: guid(registry.id, identity.id, roles.acrPull)
  properties: { principalId: mi, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull) }
}
resource raUserKv 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  scope: vault
  name: guid(vault.id, principalId, roles.kvSecretsOfficer)
  properties: { principalId: principalId, principalType: 'User', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.kvSecretsOfficer) }
}
resource raUserSearch 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  scope: search
  name: guid(search.id, principalId, roles.searchIndexContributor)
  properties: { principalId: principalId, principalType: 'User', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchIndexContributor) }
}

// ---- Container Apps: Streamlit app (public) with the API and HTTP MCP server reachable inside the environment
resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-claimguard-${token}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: { customerId: logs.properties.customerId, sharedKey: logs.listKeys().primarySharedKey }
    }
  }
}

var commonEnv = [
  { name: 'CG_LLM_PROVIDER', value: 'azure' }
  { name: 'AZURE_OPENAI_ENDPOINT', value: foundry.properties.endpoints['OpenAI Language Model Instance API'] }
  { name: 'AZURE_OPENAI_DEPLOYMENT', value: gpt4oMini.name }
  { name: 'AZURE_OPENAI_MODEL', value: 'gpt-4o-mini' }
  { name: 'AZURE_OPENAI_API_VERSION', value: '2024-10-21' }
  { name: 'AZURE_CONTENT_SAFETY_ENDPOINT', value: foundry.properties.endpoint }
  { name: 'AZURE_SEARCH_ENDPOINT', value: 'https://${search.name}.search.windows.net' }
  { name: 'AZURE_SEARCH_INDEX', value: 'claimguard-policy' }
  { name: 'AZURE_STORAGE_ACCOUNT_URL', value: storage.properties.primaryEndpoints.blob }
  { name: 'AZURE_STORAGE_CONTAINER', value: receipts.name }
  { name: 'AZURE_KEY_VAULT_URL', value: vault.properties.vaultUri }
  { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
  { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', secretRef: 'appinsights-connection-string' }
  { name: 'CG_RECEIPT_KEY', secretRef: 'cg-receipt-key' }
  { name: 'CG_API_KEY', secretRef: 'cg-api-key' }
]
var commonSecrets = [
  { name: 'appinsights-connection-string', value: appInsights.properties.ConnectionString }
  { name: 'cg-receipt-key', keyVaultUrl: '${vault.properties.vaultUri}secrets/CG-RECEIPT-KEY', identity: identity.id }
  { name: 'cg-api-key', keyVaultUrl: '${vault.properties.vaultUri}secrets/CG-API-KEY', identity: identity.id }
]

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-cg-${token}'
  location: location
  tags: union(tags, { 'azd-service-name': 'app' })
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  dependsOn: [raKv, raAcr]
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      ingress: { external: true, targetPort: 8501, transport: 'auto' }
      registries: [{ server: registry.properties.loginServer, identity: identity.id }]
      secrets: commonSecrets
    }
    template: {
      containers: [
        {
          name: 'app'
          image: appImage
          resources: { cpu: json('1.0'), memory: '2Gi' }
          env: commonEnv
        }
      ]
      scale: { minReplicas: 0, maxReplicas: 3, rules: [{ name: 'http', http: { metadata: { concurrentRequests: '20' } } }] }
    }
  }
}

output openAiEndpoint string = foundry.properties.endpoints['OpenAI Language Model Instance API']
output openAiDeployment string = gpt4oMini.name
output projectName string = project.name
output searchEndpoint string = 'https://${search.name}.search.windows.net'
output blobEndpoint string = storage.properties.primaryEndpoints.blob
output keyVaultUri string = vault.properties.vaultUri
output registryLoginServer string = registry.properties.loginServer
output appUrl string = 'https://${app.properties.configuration.ingress.fqdn}'
