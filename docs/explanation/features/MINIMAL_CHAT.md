# Minimal Chat

## Overview

Minimal Chat is a small, standalone Flask app in `application/minimal_chat/`. Users sign in with Entra ID, choose one of a set of admin-approved Azure OpenAI / Azure AI Foundry deployments, and chat with streamed replies. It is for cases where the full SimpleChat app (workspaces, RAG, Cosmos DB, AI Search) is more than is needed.

**Version:** 0.261.066

**Dependencies:** Flask, `openai` (v1 Azure endpoint), `azure-identity`, gunicorn; Azure App Service (Linux, Python 3.12); an Azure OpenAI or AI Foundry resource.

## Technical Specifications

### Architecture

- **User auth:** App Service Easy Auth (Entra ID, ID-token flow, no client secret). The app also returns 401 for any request without the `X-MS-CLIENT-PRINCIPAL-ID` header unless `REQUIRE_EASY_AUTH=false`.
- **Model auth:** `DefaultAzureCredential` → bearer token for `https://cognitiveservices.azure.com/.default`. That is the managed identity on App Service and `az login` locally. The web app's identity gets the *Cognitive Services OpenAI User* role on the resource.
- **Model calls:** `OpenAI(base_url="{endpoint}/openai/v1/")` chat completions with `stream=True`. No `temperature` is sent, so reasoning models work.
- **State:** none on the server. The browser keeps the conversation and sends it with each request.

### APIs

| Route | Method | Description |
|-------|--------|-------------|
| `/` | GET | Chat page |
| `/api/models` | GET | `{"models": [{"id", "label"}]}` from `AZURE_OPENAI_DEPLOYMENTS` |
| `/api/chat` | POST | Body `{"model", "messages": [{"role": "user"/"assistant", "content"}]}`. Returns an SSE stream of `delta`, `done` or `error` events. |
| `/healthz` | GET | Health probe (unauthenticated) |

`/api/chat` rejects models outside the allow-list, `system` messages from the client, malformed history, and requests over `MAX_MESSAGES` / `MAX_TOTAL_CHARS`, all before calling Azure.

### Configuration

See `application/minimal_chat/README.md` for the full settings table.

### File Structure

```
application/minimal_chat/
├── app.py
├── requirements.txt
├── README.md
├── templates/index.html
├── static/chat.js, chat.css
└── infra/main.bicep, openai-role.bicep
```

### Relationship to SimpleChat conventions

This app does not import `single_app` modules, so it uses Python `logging` instead of `log_event` and plain Flask routes without `swagger_route`. It has no settings document to sanitize.

## Usage

Deployment (app registration, Bicep, redirect URI, zip deploy) and local run steps are in `application/minimal_chat/README.md`. To change which models users can pick, edit the `AZURE_OPENAI_DEPLOYMENTS` app setting and restart.

## Testing and Validation

- `functional_tests/test_minimal_chat_model_selection.py` covers auth enforcement, deployment list parsing, the model allow-list, payload validation, SSE streaming, and the request sent to the model (with a stubbed client).
- Browser check (Playwright, stubbed model): model list loads, multi-turn chat streams, the selected model is remembered across reloads, and *New chat* clears the conversation.
- `infra/main.bicep` compiles and lints cleanly with Bicep CLI 0.49.2. It has **not** been deployed to a live subscription as part of this change.
- **Limitations:** no saved history, no RAG, plain-text rendering, tenant-wide access unless Enterprise App assignment is required.
