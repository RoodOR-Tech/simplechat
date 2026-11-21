// main.bicep
// Minimal Chat: Linux App Service (Python) with a system-assigned managed identity,
// Entra ID sign-in (Easy Auth), and the "Cognitive Services OpenAI User" role on an
// existing Azure OpenAI / Azure AI Foundry resource. No keys are stored anywhere.

targetScope = 'resourceGroup'

@description('Short prefix used to name resources. The web app name must be globally unique.')
@minLength(3)
@maxLength(20)
param namePrefix string

@description('Region for the App Service resources.')
param location string = resourceGroup().location

@description('Name of the existing Azure OpenAI or Azure AI Foundry (AIServices) resource.')
param openAiAccountName string

@description('Resource group of the existing Azure OpenAI / Foundry resource.')
param openAiResourceGroup string = resourceGroup().name

@description('Comma-separated deployment names users may choose from. Optional labels: "gpt-4.1=GPT-4.1,o4-mini".')
param deployments string

@description('Application (client) ID of the Entra app registration used for user sign-in.')
param authClientId string

@description('Entra tenant ID for user sign-in.')
param authTenantId string = tenant().tenantId

@description('System prompt sent with every conversation.')
param systemPrompt string = 'You are a helpful assistant.'

@description('App Service plan SKU. B1 is the cheapest tier that supports Always On.')
param skuName string = 'B1'

var webAppName = '${namePrefix}-chat-${uniqueString(resourceGroup().id)}'
// Built-in role: Cognitive Services OpenAI User (call inference APIs, no management rights).
var openAiUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

resource openAi 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
    name: openAiAccountName
    scope: resourceGroup(openAiResourceGroup)
}

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
    name: '${namePrefix}-chat-plan'
    location: location
    kind: 'linux'
    sku: {
        name: skuName
    }
    properties: {
        reserved: true
    }
}

resource webApp 'Microsoft.Web/sites@2023-12-01' = {
    name: webAppName
    location: location
    kind: 'app,linux'
    identity: {
        type: 'SystemAssigned'
    }
    properties: {
        serverFarmId: plan.id
        httpsOnly: true
        siteConfig: {
            linuxFxVersion: 'PYTHON|3.12'
            alwaysOn: true
            ftpsState: 'Disabled'
            minTlsVersion: '1.2'
            http20Enabled: true
            healthCheckPath: '/healthz'
            appCommandLine: 'gunicorn --bind=0.0.0.0:8000 --worker-class gthread --workers 2 --threads 8 --timeout 600 app:app'
            appSettings: [
                {
                    name: 'AZURE_OPENAI_ENDPOINT'
                    value: openAi.properties.endpoint
                }
                {
                    name: 'AZURE_OPENAI_DEPLOYMENTS'
                    value: deployments
                }
                {
                    name: 'SYSTEM_PROMPT'
                    value: systemPrompt
                }
                {
                    name: 'REQUIRE_EASY_AUTH'
                    value: 'true'
                }
                {
                    name: 'SCM_DO_BUILD_DURING_DEPLOYMENT'
                    value: 'true'
                }
            ]
        }
    }
}

// Easy Auth: every request must be signed in with Entra ID before it reaches the app.
// Uses the ID-token flow, so no client secret is needed; the app registration must
// have "ID tokens" enabled and the redirect URI below registered.
resource authSettings 'Microsoft.Web/sites/config@2023-12-01' = {
    parent: webApp
    name: 'authsettingsV2'
    properties: {
        platform: {
            enabled: true
        }
        globalValidation: {
            requireAuthentication: true
            unauthenticatedClientAction: 'RedirectToLoginPage'
            redirectToProvider: 'azureactivedirectory'
            excludedPaths: [
                '/healthz'
            ]
        }
        identityProviders: {
            azureActiveDirectory: {
                enabled: true
                registration: {
                    clientId: authClientId
                    openIdIssuer: '${environment().authentication.loginEndpoint}${authTenantId}/v2.0'
                }
                validation: {
                    allowedAudiences: [
                        'api://${authClientId}'
                        authClientId
                    ]
                }
            }
        }
        login: {
            tokenStore: {
                enabled: true
            }
        }
    }
}

module openAiRole 'openai-role.bicep' = {
    name: 'minimal-chat-openai-role'
    scope: resourceGroup(openAiResourceGroup)
    params: {
        openAiAccountName: openAiAccountName
        principalId: webApp.identity.principalId
        roleDefinitionId: openAiUserRoleId
    }
}

output webAppName string = webApp.name
output webAppUrl string = 'https://${webApp.properties.defaultHostName}'
output authRedirectUri string = 'https://${webApp.properties.defaultHostName}/.auth/login/aad/callback'
output openAiEndpoint string = openAi.properties.endpoint
