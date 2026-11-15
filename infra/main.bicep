// ClaimGuard on Azure: resource group + all services (azd entry point). Validate offline: bicep build infra/main.bicep
targetScope = 'subscription'

@minLength(1)
@maxLength(40)
@description('azd environment name, used in resource names')
param environmentName string

@description('Primary region. Must offer gpt-4o-mini GlobalStandard, Azure AI Search and Container Apps.')
param location string

@description('Container image for the app; azd deploy replaces it. The default is a public placeholder so provisioning succeeds before the first build.')
param appImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('gpt-4o-mini deployment capacity in thousands of tokens per minute')
param openAiCapacity int = 30

@description('Object id of the deploying user, granted Key Vault Secrets Officer so azd/CLI can write CG_RECEIPT_KEY and CG_API_KEY')
param principalId string = ''

var tags = { 'azd-env-name': environmentName, app: 'claimguard' }

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-claimguard-${environmentName}'
  location: location
  tags: tags
}

module resources 'resources.bicep' = {
  name: 'claimguard-resources'
  scope: rg
  params: {
    location: location
    tags: tags
    token: toLower(uniqueString(subscription().id, environmentName, location))
    appImage: appImage
    openAiCapacity: openAiCapacity
    principalId: principalId
  }
}

output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_OPENAI_ENDPOINT string = resources.outputs.openAiEndpoint
output AZURE_OPENAI_DEPLOYMENT string = resources.outputs.openAiDeployment
output AZURE_AI_PROJECT_NAME string = resources.outputs.projectName
output AZURE_SEARCH_ENDPOINT string = resources.outputs.searchEndpoint
output AZURE_STORAGE_ACCOUNT_URL string = resources.outputs.blobEndpoint
output AZURE_KEY_VAULT_URL string = resources.outputs.keyVaultUri
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = resources.outputs.registryLoginServer
output SERVICE_APP_URL string = resources.outputs.appUrl
