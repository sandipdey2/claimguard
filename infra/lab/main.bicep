// Lab / existing-resource-group entry point (no subscription-scope rights needed). Used for the Udacity Vocareum lab deployment.
//   az deployment group create -g <existing-rg> -f infra/lab/main.bicep -p infra/lab/lab.parameters.json -p principalId=<your object id> deployApps=false
targetScope = 'resourceGroup'

param location string = resourceGroup().location
param environmentName string = 'lab'
param appImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
param principalId string = ''
param deployOpenAi bool = true
param searchSku string = 'free'
param deployApps bool = true
param deployApi bool = true

module resources '../resources.bicep' = {
  name: 'claimguard-resources'
  params: {
    location: location
    tags: { 'azd-env-name': environmentName, app: 'claimguard' }
    token: toLower(uniqueString(resourceGroup().id, environmentName, location))
    appImage: appImage
    apiImage: appImage
    openAiCapacity: 30
    principalId: principalId
    deployOpenAi: deployOpenAi
    searchSku: searchSku
    deployApps: deployApps
    deployApi: deployApi
    purgeProtection: false
  }
}

output AZURE_SEARCH_ENDPOINT string = resources.outputs.searchEndpoint
output AZURE_STORAGE_ACCOUNT_URL string = resources.outputs.blobEndpoint
output AZURE_KEY_VAULT_URL string = resources.outputs.keyVaultUri
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = resources.outputs.registryLoginServer
output SERVICE_APP_URL string = resources.outputs.appUrl
output SERVICE_API_URL string = resources.outputs.apiUrl
