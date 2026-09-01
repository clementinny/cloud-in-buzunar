const aiStatus = document.querySelector("#ai-status");
const aiUserStatus =
    document.querySelector("#ai-user-status");
const generationStatus =
    document.querySelector("#ai-generation-status");
const messagesContainer =
    document.querySelector("#ai-messages");
const aiError = document.querySelector("#ai-error");
const aiForm = document.querySelector("#ai-form");
const promptInput =
    document.querySelector("#ai-prompt-input");
const sendButton =
    document.querySelector("#ai-send-button");
const clearChatButton =
    document.querySelector("#clear-chat-button");
const modelControls =
    document.querySelector("#ai-model-controls");
const modelSelect =
    document.querySelector("#ai-model-select");
const modelSwitchButton =
    document.querySelector("#ai-model-switch-button");
const modelMessage =
    document.querySelector("#ai-model-message");

let currentUser = null;
let messages = [];
let requestIsRunning = false;
let activeModelMode = null;


async function readJsonResponse(response) {
    let data = null;

    try {
        data = await response.json();
    } catch (error) {
        data = null;
    }

    if (!response.ok) {
        throw new Error(
            data?.error
            ?? `Cererea a eșuat: HTTP ${response.status}`
        );
    }

    return data;
}


async function loadServerMessages() {
    const response = await fetch("/api/ai/history");
    const data = await readJsonResponse(response);

    if (!Array.isArray(data.messages)) {
        return [];
    }

    return data.messages.filter(
        (message) =>
            message
            && ["user", "assistant"].includes(
                message.role
            )
            && typeof message.content === "string"
    );
}


function createMessageElement(message) {
    const article = document.createElement("article");
    const label = document.createElement("p");
    const content = document.createElement("p");

    article.className =
        `ai-message ai-message-${message.role}`;
    label.className = "ai-message-label";
    content.className = "ai-message-content";

    label.textContent =
        message.role === "user" ? "Tu" : "Qwen";
    content.textContent = message.content;

    article.append(label, content);

    return article;
}


function renderMessages() {
    messagesContainer.replaceChildren();

    if (messages.length === 0) {
        const welcome = document.createElement("div");

        welcome.className = "ai-welcome";
        welcome.textContent =
            "Începe o conversație cu modelul local Qwen.";
        messagesContainer.append(welcome);
        return;
    }

    for (const message of messages) {
        messagesContainer.append(
            createMessageElement(message)
        );
    }

    messagesContainer.scrollTop =
        messagesContainer.scrollHeight;
}


function setBusyState(isBusy) {
    requestIsRunning = isBusy;
    sendButton.disabled = isBusy;
    promptInput.disabled = isBusy;
    clearChatButton.disabled = isBusy;

    if (isBusy) {
        generationStatus.textContent =
            "Qwen generează răspunsul...";
        generationStatus.hidden = false;
    } else {
        generationStatus.hidden =
            !generationStatus.textContent;
    }
}


function updateModelSwitchButton() {
    modelSwitchButton.disabled =
        requestIsRunning
        || !modelSelect.value
        || modelSelect.value === activeModelMode;
}


async function loadAiStatus() {
    const response = await fetch("/api/ai/status");
    const data = await readJsonResponse(response);

    activeModelMode = data.mode;
    aiStatus.textContent = data.online
        ? `${data.model} · online`
        : `${data.model} · indisponibil`;

    modelControls.hidden = !data.can_manage;

    if (data.can_manage) {
        modelSelect.replaceChildren();

        for (const model of data.available_models) {
            const option = document.createElement("option");

            option.value = model.mode;
            option.textContent = model.label;
            option.title = model.description;
            modelSelect.append(option);
        }

        modelSelect.value = data.mode;
        updateModelSwitchButton();
    }
}


modelSelect.addEventListener("change", () => {
    modelMessage.hidden = true;
    updateModelSwitchButton();
});


modelSwitchButton.addEventListener("click", async () => {
    const requestedMode = modelSelect.value;

    if (
        requestIsRunning
        || !requestedMode
        || requestedMode === activeModelMode
    ) {
        return;
    }

    const selectedLabel =
        modelSelect.selectedOptions[0]?.textContent
        ?? requestedMode;

    if (!window.confirm(
        `Schimbi modelul AI în ${selectedLabel}?`
    )) {
        modelSelect.value = activeModelMode;
        updateModelSwitchButton();
        return;
    }

    requestIsRunning = true;
    sendButton.disabled = true;
    promptInput.disabled = true;
    clearChatButton.disabled = true;
    modelSelect.disabled = true;
    modelSwitchButton.disabled = true;

    modelMessage.textContent =
        "Se oprește modelul curent și se încarcă modelul ales...";
    modelMessage.classList.remove("is-error");
    modelMessage.hidden = false;
    aiError.hidden = true;

    try {
        const response = await fetch("/api/ai/model", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                mode: requestedMode,
            }),
        });
        const data = await readJsonResponse(response);

        activeModelMode = data.mode;
        modelMessage.textContent =
            `${data.model} este pregătit.`;
        await loadAiStatus();
    } catch (error) {
        modelMessage.textContent = error.message;
        modelMessage.classList.add("is-error");
        modelSelect.value = activeModelMode;
    } finally {
        requestIsRunning = false;
        sendButton.disabled = false;
        promptInput.disabled = false;
        clearChatButton.disabled = false;
        modelSelect.disabled = false;
        updateModelSwitchButton();
        promptInput.focus();
    }
});


aiForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    if (requestIsRunning) {
        return;
    }

    const content = promptInput.value.trim();

    if (!content) {
        return;
    }

    messages.push({
        role: "user",
        content,
    });
    messages = messages.slice(-10);

    promptInput.value = "";
    aiError.hidden = true;
    renderMessages();
    setBusyState(true);

    try {
        const response = await fetch("/api/ai/chat", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                message: content,
            }),
        });
        const data = await readJsonResponse(response);

        messages.push(data.message);
        messages = messages.slice(-10);
            renderMessages();

        const speed = Number(
            data.usage?.tokens_per_second ?? 0
        );

        generationStatus.textContent = speed > 0
            ? `Răspuns generat cu ${speed.toFixed(1)} tokeni/s`
            : "Răspuns generat local";
        generationStatus.hidden = false;
    } catch (error) {
        generationStatus.textContent = "";
        aiError.textContent = error.message;
        aiError.hidden = false;
    } finally {
        setBusyState(false);
        promptInput.focus();
    }
});


promptInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.ctrlKey) {
        event.preventDefault();
        aiForm.requestSubmit();
    }
});


clearChatButton.addEventListener("click", async () => {
    if (requestIsRunning || messages.length === 0) {
        return;
    }

    if (!window.confirm(
        "Ștergi definitiv conversația din baza de date?"
    )) {
        return;
    }

    requestIsRunning = true;
    clearChatButton.disabled = true;
    sendButton.disabled = true;
    promptInput.disabled = true;
    aiError.hidden = true;

    try {
        const response = await fetch("/api/ai/history", {
            method: "DELETE",
        });
        await readJsonResponse(response);

        messages = [];
        renderMessages();
        generationStatus.textContent = "";
        generationStatus.hidden = true;
    } catch (error) {
        aiError.textContent = error.message;
        aiError.hidden = false;
    } finally {
        requestIsRunning = false;
        clearChatButton.disabled = false;
        sendButton.disabled = false;
        promptInput.disabled = false;
        updateModelSwitchButton();
        promptInput.focus();
    }
});


async function initializeAiPage() {
    try {
        const sessionResponse = await fetch("/api/auth/me");
        const sessionData = await readJsonResponse(
            sessionResponse
        );

        currentUser = sessionData.user;
        aiUserStatus.textContent =
            `Conectat ca ${currentUser.username}`;

        messages = await loadServerMessages();
        renderMessages();

        await loadAiStatus();

        aiForm.hidden = false;
        promptInput.focus();
    } catch (error) {
        aiStatus.textContent = "Indisponibil";
        aiUserStatus.textContent =
            "Conectează-te din dashboard pentru a folosi AI-ul.";
        aiError.textContent = error.message;
        aiError.hidden = false;
    }
}


initializeAiPage();
