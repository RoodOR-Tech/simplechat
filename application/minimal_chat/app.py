# app.py
"""
Minimal Chat: a small, standalone Flask chat app for Azure OpenAI / Azure AI Foundry.

Users pick one of the admin-approved model deployments and chat with it. Replies
stream back over server-sent events. There is no database: conversation history
lives in the browser tab and is sent with each request.

Authentication:
  * To Azure OpenAI: Microsoft Entra ID via DefaultAzureCredential (managed identity
    on App Service, `az login` locally). No API keys.
  * For users: App Service Easy Auth (Entra ID) in front of the app. The app also
    refuses requests that lack the Easy Auth principal header unless
    REQUIRE_EASY_AUTH=false (for local development only).

This app is intentionally independent of application/single_app and does not
import any of its modules.
"""

import json
import logging
import os

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from flask import Flask, Response, abort, jsonify, render_template, request
from openai import OpenAI, OpenAIError

APP_VERSION = "1.0.0"

# Limits that keep a single request bounded. Override with environment variables.
MAX_MESSAGES = int(os.getenv("MAX_MESSAGES", "50"))
MAX_TOTAL_CHARS = int(os.getenv("MAX_TOTAL_CHARS", "200000"))
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "4096"))

ALLOWED_ROLES = {"user", "assistant"}
TOKEN_SCOPE = "https://cognitiveservices.azure.com/.default"

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("minimal_chat")

app = Flask(__name__)


def parse_deployments(raw):
    """Parse AZURE_OPENAI_DEPLOYMENTS.

    Format: comma-separated entries, each either `deployment` or
    `deployment=Display Label`. Example:
        gpt-4.1=GPT-4.1,gpt-4.1-mini=GPT-4.1 mini,o4-mini
    Returns an ordered list of {"id": ..., "label": ...}.
    """
    models = []
    seen = set()
    for entry in (raw or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        deployment, _, label = entry.partition("=")
        deployment = deployment.strip()
        label = label.strip() or deployment
        if deployment and deployment not in seen:
            seen.add(deployment)
            models.append({"id": deployment, "label": label})
    return models


def load_config():
    """Read configuration from the environment."""
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip().rstrip("/")
    models = parse_deployments(os.getenv("AZURE_OPENAI_DEPLOYMENTS", ""))
    return {
        "endpoint": endpoint,
        "models": models,
        "system_prompt": os.getenv("SYSTEM_PROMPT", "You are a helpful assistant."),
        "require_easy_auth": os.getenv("REQUIRE_EASY_AUTH", "true").lower() != "false",
    }


CONFIG = load_config()
_client = None


def get_client():
    """Return a cached OpenAI client pointed at the Azure v1 endpoint.

    The v1 endpoint (`{resource}/openai/v1/`) works for both Azure OpenAI and
    Azure AI Foundry resources and needs no api-version parameter. The token
    provider is called per request, so tokens refresh automatically.
    """
    global _client
    if _client is None:
        if not CONFIG["endpoint"]:
            raise RuntimeError("AZURE_OPENAI_ENDPOINT is not set.")
        token_provider = get_bearer_token_provider(DefaultAzureCredential(), TOKEN_SCOPE)
        _client = OpenAI(base_url=f"{CONFIG['endpoint']}/openai/v1/", api_key=token_provider)
    return _client


def current_user():
    """Return the signed-in user's name from Easy Auth headers.

    App Service strips these headers from inbound requests and sets them itself
    when Easy Auth is enabled, so they cannot be forged by the client.
    """
    principal_id = request.headers.get("X-MS-CLIENT-PRINCIPAL-ID")
    if not principal_id:
        if CONFIG["require_easy_auth"]:
            return None
        return "local developer"
    return request.headers.get("X-MS-CLIENT-PRINCIPAL-NAME") or principal_id


@app.before_request
def enforce_authentication():
    """Reject requests that did not come through Easy Auth (health check excepted)."""
    if request.path == "/healthz":
        return None
    if current_user() is None:
        abort(401)
    return None


def validate_messages(messages):
    """Validate the client-supplied conversation. Returns (clean_messages, error)."""
    if not isinstance(messages, list) or not messages:
        return None, "messages must be a non-empty list."
    if len(messages) > MAX_MESSAGES:
        return None, f"Conversation is too long (max {MAX_MESSAGES} messages). Start a new chat."
    clean = []
    total_chars = 0
    for message in messages:
        if not isinstance(message, dict):
            return None, "Each message must be an object."
        role = message.get("role")
        content = message.get("content")
        if role not in ALLOWED_ROLES or not isinstance(content, str):
            return None, "Each message needs role 'user' or 'assistant' and string content."
        total_chars += len(content)
        clean.append({"role": role, "content": content})
    if total_chars > MAX_TOTAL_CHARS:
        return None, "Conversation is too large. Start a new chat."
    if clean[-1]["role"] != "user":
        return None, "The last message must be from the user."
    return clean, None


def sse(event):
    """Format one server-sent event."""
    return f"data: {json.dumps(event)}\n\n"


@app.get("/")
def index():
    return render_template(
        "index.html",
        user=current_user(),
        has_models=bool(CONFIG["models"]),
        app_version=APP_VERSION,
    )


@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok", "version": APP_VERSION})


@app.get("/api/models")
def list_models():
    return jsonify({"models": CONFIG["models"]})


@app.post("/api/chat")
def chat():
    payload = request.get_json(silent=True) or {}
    allowed_ids = {model["id"] for model in CONFIG["models"]}
    model = payload.get("model")
    if model not in allowed_ids:
        return jsonify({"error": "Unknown or disallowed model."}), 400

    messages, error = validate_messages(payload.get("messages"))
    if error:
        return jsonify({"error": error}), 400

    full_messages = [{"role": "system", "content": CONFIG["system_prompt"]}] + messages
    user = current_user()

    def generate():
        try:
            # temperature and similar knobs are deliberately not sent: reasoning
            # models (o-series, gpt-5 family) reject them.
            stream = get_client().chat.completions.create(
                model=model,
                messages=full_messages,
                max_completion_tokens=MAX_OUTPUT_TOKENS,
                stream=True,
            )
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                text = getattr(delta, "content", None)
                if text:
                    yield sse({"type": "delta", "text": text})
            yield sse({"type": "done"})
        except OpenAIError as exc:
            logger.warning("Model call failed for user=%s model=%s: %s", user, model, exc)
            yield sse({"type": "error", "message": f"The model call failed: {exc.__class__.__name__}."})
        except Exception:
            logger.exception("Unexpected error for user=%s model=%s", user, model)
            yield sse({"type": "error", "message": "Unexpected server error."})

    logger.info("chat user=%s model=%s messages=%d", user, model, len(messages))
    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.errorhandler(401)
def unauthorized(_error):
    return jsonify({"error": "Sign-in required."}), 401


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=False)
