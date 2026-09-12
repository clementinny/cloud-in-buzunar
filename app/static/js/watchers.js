const watcherForm = document.querySelector("#watcher-form");
const watcherId = document.querySelector("#watcher-id");
const watcherName = document.querySelector("#watcher-name");
const watcherUrl = document.querySelector("#watcher-url");
const watcherMode = document.querySelector("#watcher-mode");
const watcherNeedle = document.querySelector("#watcher-needle");
const needleField = document.querySelector("#needle-field");
const watcherInterval = document.querySelector("#watcher-interval");
const watcherEnabled = document.querySelector("#watcher-enabled");
const saveWatcherButton = document.querySelector("#save-watcher");
const cancelEditButton = document.querySelector("#cancel-edit");
const refreshButton = document.querySelector("#refresh-watchers");
const watcherList = document.querySelector("#watcher-list");
const watcherEmpty = document.querySelector("#watcher-empty");
const watcherCount = document.querySelector("#watcher-count");
const formMessage = document.querySelector("#form-message");
const pageMessage = document.querySelector("#page-message");

let watchers = [];


async function readJson(response) {
    const data = await response.json().catch(() => ({}));

    if (response.status === 401) {
        window.location.assign("/");
        throw new Error("Sesiunea a expirat.");
    }

    if (!response.ok) {
        throw new Error(data.error ?? `Cererea a eșuat: HTTP ${response.status}`);
    }

    return data;
}


function formatDate(value) {
    if (!value) {
        return "niciodată";
    }

    return new Intl.DateTimeFormat("ro-RO", {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
    }).format(new Date(value));
}


function statusLabel(watcher) {
    if (!watcher.enabled) return "Pauză";

    return {
        never: "În așteptare",
        ok: "Normal",
        changed: "Schimbare detectată",
        alert: "Condiție activă",
        error: "Eroare",
    }[watcher.last_status] ?? watcher.last_status;
}


function modeLabel(watcher) {
    if (watcher.mode === "change") return "Orice schimbare de conținut";
    if (watcher.mode === "contains") return `Apare: „${watcher.needle}”`;
    return `Dispare: „${watcher.needle}”`;
}


function createButton(label, className, handler) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.className = className;
    button.addEventListener("click", handler);
    return button;
}


function renderWatcher(watcher) {
    const card = document.createElement("article");
    card.className = `watcher-card is-${watcher.last_status}`;

    const heading = document.createElement("div");
    heading.className = "watcher-heading";
    const title = document.createElement("h3");
    title.textContent = watcher.name;
    const status = document.createElement("span");
    status.className = `watcher-status${watcher.enabled ? "" : " is-paused"}`;
    status.textContent = statusLabel(watcher);
    heading.append(title, status);

    const url = document.createElement("a");
    url.className = "watcher-url";
    url.href = watcher.url;
    url.target = "_blank";
    url.rel = "noopener noreferrer";
    url.textContent = watcher.url;

    const condition = document.createElement("p");
    condition.textContent = modeLabel(watcher);

    const meta = document.createElement("div");
    meta.className = "watcher-meta";
    const interval = document.createElement("span");
    interval.textContent = `La ${watcher.interval_minutes} min`;
    const checked = document.createElement("span");
    checked.textContent = `Verificat: ${formatDate(watcher.last_checked_at)}`;
    const next = document.createElement("span");
    next.textContent = watcher.enabled
        ? `Următoarea: ${formatDate(watcher.next_check_at)}`
        : "Verificarea este oprită";
    meta.append(interval, checked, next);

    card.append(heading, url, condition, meta);

    if (watcher.last_error) {
        const error = document.createElement("p");
        error.className = "watcher-error";
        error.textContent = watcher.last_error;
        card.append(error);
    }

    const actions = document.createElement("div");
    actions.className = "watcher-actions";
    const checkButton = createButton("Verifică acum", "", async () => {
        checkButton.disabled = true;

        try {
            const response = await fetch(`/api/watchers/${watcher.id}/check`, {
                method: "POST",
            });
            const data = await readJson(response);
            showPageMessage(
                data.ok
                    ? "Verificarea s-a terminat."
                    : data.error,
                !data.ok,
            );
            await loadWatchers();
        } catch (error) {
            showPageMessage(error.message, true);
        } finally {
            checkButton.disabled = false;
        }
    });
    const toggleButton = createButton(
        watcher.enabled ? "Pune pe pauză" : "Pornește",
        "secondary-button",
        async () => {
            toggleButton.disabled = true;

            try {
                const response = await fetch(
                    `/api/watchers/${watcher.id}/enabled`,
                    {
                        method: "PATCH",
                        headers: {"Content-Type": "application/json"},
                        body: JSON.stringify({enabled: !watcher.enabled}),
                    },
                );
                await readJson(response);
                await loadWatchers();
            } catch (error) {
                showPageMessage(error.message, true);
            } finally {
                toggleButton.disabled = false;
            }
        },
    );
    const editButton = createButton("Editează", "secondary-button", () => {
        startEditing(watcher);
    });
    const deleteButton = createButton("Șterge", "danger-button", async () => {
        if (!window.confirm(`Ștergi urmărirea „${watcher.name}”?`)) return;

        deleteButton.disabled = true;

        try {
            const response = await fetch(`/api/watchers/${watcher.id}`, {
                method: "DELETE",
            });
            await readJson(response);
            await loadWatchers();
        } catch (error) {
            showPageMessage(error.message, true);
            deleteButton.disabled = false;
        }
    });
    actions.append(checkButton, toggleButton, editButton, deleteButton);
    card.append(actions);
    return card;
}


function renderWatchers() {
    watcherList.replaceChildren(...watchers.map(renderWatcher));
    watcherEmpty.hidden = watchers.length !== 0;
    watcherCount.textContent = watchers.length === 1
        ? "1 urmărire configurată"
        : `${watchers.length} urmăriri configurate`;
}


function showPageMessage(message, isError = false) {
    pageMessage.textContent = message;
    pageMessage.hidden = !message;
    pageMessage.classList.toggle("is-error", isError);
}


function updateNeedleVisibility() {
    const requiresNeedle = watcherMode.value !== "change";
    needleField.hidden = !requiresNeedle;
    watcherNeedle.required = requiresNeedle;
}


function resetForm() {
    watcherForm.reset();
    watcherId.value = "";
    watcherInterval.value = "60";
    watcherEnabled.checked = true;
    saveWatcherButton.textContent = "Salvează urmărirea";
    cancelEditButton.hidden = true;
    formMessage.textContent = "";
    formMessage.classList.remove("is-error");
    updateNeedleVisibility();
}


function startEditing(watcher) {
    watcherId.value = String(watcher.id);
    watcherName.value = watcher.name;
    watcherUrl.value = watcher.url;
    watcherMode.value = watcher.mode;
    watcherNeedle.value = watcher.needle ?? "";
    watcherInterval.value = String(watcher.interval_minutes);
    watcherEnabled.checked = watcher.enabled;
    saveWatcherButton.textContent = "Salvează modificările";
    cancelEditButton.hidden = false;
    updateNeedleVisibility();
    watcherName.focus();
    window.scrollTo({top: 0, behavior: "smooth"});
}


async function loadWatchers() {
    refreshButton.disabled = true;

    try {
        const response = await fetch("/api/watchers");
        const data = await readJson(response);
        watchers = data.watchers;
        renderWatchers();
        showPageMessage("");
    } catch (error) {
        showPageMessage(error.message, true);
    } finally {
        refreshButton.disabled = false;
    }
}


watcherForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    saveWatcherButton.disabled = true;
    formMessage.textContent = "Se salvează...";
    formMessage.classList.remove("is-error");
    const editingId = watcherId.value;
    const payload = {
        name: watcherName.value.trim(),
        url: watcherUrl.value.trim(),
        mode: watcherMode.value,
        needle: watcherNeedle.value.trim(),
        interval_minutes: Number(watcherInterval.value),
        enabled: watcherEnabled.checked,
    };

    try {
        const response = await fetch(
            editingId ? `/api/watchers/${editingId}` : "/api/watchers",
            {
                method: editingId ? "PUT" : "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify(payload),
            },
        );
        await readJson(response);
        resetForm();
        formMessage.textContent = editingId
            ? "Modificările au fost salvate."
            : "Urmărirea a fost creată.";
        await loadWatchers();
    } catch (error) {
        formMessage.textContent = error.message;
        formMessage.classList.add("is-error");
    } finally {
        saveWatcherButton.disabled = false;
    }
});

watcherMode.addEventListener("change", updateNeedleVisibility);
cancelEditButton.addEventListener("click", resetForm);
refreshButton.addEventListener("click", loadWatchers);

async function initializePage() {
    try {
        const response = await fetch("/api/auth/me");
        const data = await readJson(response);

        if (data.user.role !== "admin") {
            throw new Error("Această pagină este disponibilă numai administratorului.");
        }

        updateNeedleVisibility();
        await loadWatchers();
    } catch (error) {
        showPageMessage(error.message, true);
        watcherForm.hidden = true;
        refreshButton.disabled = true;
    }
}

initializePage();
