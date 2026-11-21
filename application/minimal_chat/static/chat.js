// chat.js
// Minimal Chat front end: model picker, in-memory history, streamed replies.

(function () {
    "use strict";

    const MODEL_STORAGE_KEY = "minimalChat.model";

    const modelSelect = document.getElementById("model-select");
    const messagesEl = document.getElementById("messages");
    const emptyState = document.getElementById("empty-state");
    const errorBanner = document.getElementById("error-banner");
    const form = document.getElementById("chat-form");
    const promptInput = document.getElementById("prompt");
    const sendButton = document.getElementById("send");
    const newChatButton = document.getElementById("new-chat");

    let history = [];
    let busy = false;

    function showError(message) {
        errorBanner.textContent = message;
        errorBanner.classList.remove("d-none");
    }

    function clearError() {
        errorBanner.textContent = "";
        errorBanner.classList.add("d-none");
    }

    function setBusy(value) {
        busy = value;
        sendButton.disabled = value;
        modelSelect.disabled = value;
        newChatButton.disabled = value;
        sendButton.textContent = value ? "..." : "Send";
    }

    function addMessage(role, text, modelLabel) {
        emptyState.classList.add("d-none");
        const wrapper = document.createElement("div");
        wrapper.className = `message ${role}`;
        const roleEl = document.createElement("div");
        roleEl.className = "role";
        roleEl.textContent = role === "user" ? "You" : (modelLabel || "Assistant");
        const bodyEl = document.createElement("div");
        bodyEl.className = "body";
        bodyEl.textContent = text;
        wrapper.append(roleEl, bodyEl);
        messagesEl.appendChild(wrapper);
        messagesEl.scrollTop = messagesEl.scrollHeight;
        return bodyEl;
    }

    async function loadModels() {
        try {
            const response = await fetch("/api/models");
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const data = await response.json();
            let savedModel = null;
            try {
                savedModel = localStorage.getItem(MODEL_STORAGE_KEY);
            } catch (err) {
                savedModel = null;
            }
            for (const model of data.models) {
                const option = document.createElement("option");
                option.value = model.id;
                option.textContent = model.label;
                if (model.id === savedModel) {
                    option.selected = true;
                }
                modelSelect.appendChild(option);
            }
            if (!data.models.length) {
                sendButton.disabled = true;
            }
        } catch (err) {
            showError(`Could not load models: ${err.message}`);
        }
    }

    // Parse an SSE stream from a fetch response and call onEvent for each JSON event.
    async function readEventStream(response, onEvent) {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (true) {
            const { value, done } = await reader.read();
            if (done) {
                break;
            }
            buffer += decoder.decode(value, { stream: true });
            let boundary = buffer.indexOf("\n\n");
            while (boundary !== -1) {
                const rawEvent = buffer.slice(0, boundary);
                buffer = buffer.slice(boundary + 2);
                for (const line of rawEvent.split("\n")) {
                    if (line.startsWith("data: ")) {
                        onEvent(JSON.parse(line.slice(6)));
                    }
                }
                boundary = buffer.indexOf("\n\n");
            }
        }
    }

    async function sendMessage(text) {
        clearError();
        const model = modelSelect.value;
        const modelLabel = modelSelect.options[modelSelect.selectedIndex]?.textContent;
        history.push({ role: "user", content: text });
        addMessage("user", text);
        const replyEl = addMessage("assistant", "", modelLabel);
        let replyText = "";
        let failed = false;
        setBusy(true);

        try {
            const response = await fetch("/api/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ model, messages: history }),
            });
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(data.error || `HTTP ${response.status}`);
            }
            await readEventStream(response, (event) => {
                if (event.type === "delta") {
                    replyText += event.text;
                    replyEl.textContent = replyText;
                    messagesEl.scrollTop = messagesEl.scrollHeight;
                } else if (event.type === "error") {
                    failed = true;
                    showError(event.message);
                }
            });
        } catch (err) {
            failed = true;
            showError(err.message);
        } finally {
            setBusy(false);
        }

        if (failed && !replyText) {
            // Drop the failed turn so the user can retry without a dangling message.
            history.pop();
            replyEl.parentElement.remove();
            promptInput.value = text;
        } else {
            history.push({ role: "assistant", content: replyText });
        }
        promptInput.focus();
    }

    form.addEventListener("submit", (event) => {
        event.preventDefault();
        const text = promptInput.value.trim();
        if (!text || busy || !modelSelect.value) {
            return;
        }
        promptInput.value = "";
        sendMessage(text);
    });

    promptInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            form.requestSubmit();
        }
    });

    modelSelect.addEventListener("change", () => {
        try {
            localStorage.setItem(MODEL_STORAGE_KEY, modelSelect.value);
        } catch (err) {
            // Storage unavailable; the choice just won't be remembered.
        }
    });

    newChatButton.addEventListener("click", () => {
        history = [];
        clearError();
        for (const el of messagesEl.querySelectorAll(".message")) {
            el.remove();
        }
        emptyState.classList.remove("d-none");
        promptInput.focus();
    });

    loadModels();
})();
