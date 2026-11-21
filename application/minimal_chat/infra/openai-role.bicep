// openai-role.bicep
// Grants a principal a role on an Azure OpenAI / Foundry account. Deployed as a module
// so the account can live in a different resource group from the web app.

param openAiAccountName string
param principalId string
param roleDefinitionId string

resource openAi 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
    name: openAiAccountName
}

resource roleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
    name: guid(openAi.id, principalId, roleDefinitionId)
    scope: openAi
    properties: {
        principalId: principalId
        principalType: 'ServicePrincipal'
        roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleDefinitionId)
    }
}
