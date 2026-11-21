# Minimal Chat

A small, standalone chat app. Users sign in with Entra ID, pick a model from a dropdown, and chat with it. Every model call goes to your Azure OpenAI / Azure AI Foundry resource using the app's managed identity, so there are no API keys.

It is separate from the main SimpleChat app in `application/single_app` and shares no code with it. There is no database: a conversation lasts as long as the browser tab.

```
Browser ──Entra sign-in (Easy Auth)──> App Service (Flask) ──managed identity──> Azure OpenAI / Foundry
```

| File | Purpose |
|------|---------|
| `app.py` | Flask app: `/`, `/api/models`, `/api/chat` (SSE stream), `/healthz` |
| `templates/index.html`, `static/` | UI |
| `infra/main.bicep` | App Service, managed identity, Easy Auth, role assignment |
| `infra/openai-role.bicep` | Role assignment module (supports a different resource group) |

## Configuration

| Setting | Required | Description |
|---------|----------|-------------|
| `AZURE_OPENAI_ENDPOINT` | yes | e.g. `https://my-resource.openai.azure.com` or `https://my-resource.cognitiveservices.azure.com`. Set automatically by the Bicep template. |
| `AZURE_OPENAI_DEPLOYMENTS` | yes | Deployments users may pick, as a comma-separated list with optional labels: `gpt-4.1=GPT-4.1,gpt-4.1-mini=GPT-4.1 mini,o4-mini`. These are **deployment names**, not model names. |
| `SYSTEM_PROMPT` | no | Defaults to `You are a helpful assistant.` |
| `REQUIRE_EASY_AUTH` | no | Defaults to `true`. Set `false` **only** for local development. |
| `MAX_MESSAGES` / `MAX_TOTAL_CHARS` / `MAX_OUTPUT_TOKENS` | no | Request limits. Defaults: 50 / 200000 / 4096. |

To add or remove a model later, deploy it in the Foundry portal, then edit `AZURE_OPENAI_DEPLOYMENTS` in the web app's Environment variables and restart. The app refuses any model that isn't in that list.

## Prerequisites

- An Azure OpenAI or Azure AI Foundry resource with at least one model deployed.
- Azure CLI, logged in with rights to create resources and role assignments (Owner or User Access Administrator on the OpenAI resource), and to create an Entra app registration.

## Deploy

**1. Create the Entra app registration** that users will sign in with:

```bash
az ad app create --display-name minimal-chat --sign-in-audience AzureADMyOrg --enable-id-token-issuance true --query appId -o tsv
```

Note the `appId` it prints.

**2. Deploy the infrastructure:**

```bash
az group create -n rg-minimal-chat -l eastus2
```

```bash
az deployment group create -g rg-minimal-chat -f infra/main.bicep -p namePrefix=mychat openAiAccountName=<your-openai-resource> openAiResourceGroup=<its-resource-group> deployments="gpt-4.1=GPT-4.1,gpt-4.1-mini=GPT-4.1 mini" authClientId=<appId> --query properties.outputs
```

Note the `webAppName` and `authRedirectUri` outputs.

**3. Register the sign-in redirect URI:**

```bash
az ad app update --id <appId> --web-redirect-uris <authRedirectUri>
```

**4. Deploy the code** (run from `application/minimal_chat`):

```bash
zip -r /tmp/minimal_chat.zip app.py requirements.txt templates static
```

```bash
az webapp deploy -g rg-minimal-chat -n <webAppName> --src-path /tmp/minimal_chat.zip --type zip
```

Open the `webAppUrl`. The first model call can return a permission error for a few minutes while the new role assignment propagates.

## Run locally

Your own account needs the **Cognitive Services OpenAI User** role on the OpenAI resource.

```bash
az login
```

```bash
pip install -r requirements.txt
```

```bash
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com AZURE_OPENAI_DEPLOYMENTS="gpt-4.1,gpt-4.1-mini" REQUIRE_EASY_AUTH=false python app.py
```

Then open http://127.0.0.1:5000.

## Test

```bash
python functional_tests/test_minimal_chat_model_selection.py
```

The test stubs the Azure client, so it needs no Azure access.

## Limitations

- No saved history and no document upload or RAG. Use the main SimpleChat app for those.
- Responses are shown as plain text; Markdown is not rendered.
- Easy Auth admits anyone in your tenant. To restrict access to specific people, set *Assignment required* on the app's Enterprise Application and assign users or groups.
