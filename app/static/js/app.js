const loginButton = document.querySelector("#login-button");
const loginDialog = document.querySelector("#login-dialog");
const loginForm = document.querySelector("#login-form");
const closeLoginButton = document.querySelector("#close-login");
const tokenInput = document.querySelector("#token-input");
const loginError = document.querySelector("#login-error");
const connectionStatus = document.querySelector("#connection-status");
const filesMessage = document.querySelector("#files-message");
const fileList = document.querySelector("#file-list");

const storageKey = "cloudInBuzunar.apiToken";

let apiToken = sessionStorage.getItem(storageKey) ?? "";


function formatBytes(bytes) {
    if (bytes === 0) {
        return "0 B";
    }

    const units = ["B", "KB", "MB", "GB"];
    const unitIndex = Math.min(
        Math.floor(Math.log(bytes) / Math.log(1024)),
        units.length - 1,
    );

    const value = bytes / (1024 ** unitIndex);

    return `${value.toFixed(1)} ${units[unitIndex]}`;
}


function renderFiles(files) {
    fileList.replaceChildren();

    if (files.length === 0) {
        filesMessage.textContent = "Nu există fișiere încă.";
        filesMessage.hidden = false;
        return;
    }

    filesMessage.hidden = true;

    for (const file of files) {
        const item = document.createElement("li");
        const name = document.createElement("span");
        const details = document.createElement("span");

        item.className = "file-row";
        name.className = "file-name";
        details.className = "file-details";

        name.textContent = file.filename;
        details.textContent = formatBytes(file.size_bytes);

        item.append(name, details);
        fileList.append(item);
    }
}


function showDisconnectedState() {
    connectionStatus.textContent = "Neconectat";
    loginButton.textContent = "Conectare";
    filesMessage.textContent =
        "Conectează-te pentru a vedea fișierele.";
    filesMessage.hidden = false;
    fileList.replaceChildren();
}


function showConnectedState(fileCount) {
    const label = fileCount === 1 ? "fișier" : "fișiere";

    connectionStatus.textContent =
        `Conectat · ${fileCount} ${label}`;
    loginButton.textContent = "Deconectare";
}


async function loadFiles(token) {
    const response = await fetch("/api/files", {
        headers: {
            Authorization: `Bearer ${token}`,
        },
    });

    if (!response.ok) {
        throw new Error(`API returned ${response.status}`);
    }

    const data = await response.json();

    renderFiles(data.files);
    showConnectedState(data.count);
}


loginButton.addEventListener("click", () => {
    if (apiToken) {
        apiToken = "";
        sessionStorage.removeItem(storageKey);
        showDisconnectedState();
        return;
    }

    loginError.hidden = true;
    loginDialog.showModal();
    tokenInput.focus();
});


closeLoginButton.addEventListener("click", () => {
    loginDialog.close();
    loginForm.reset();
    loginError.hidden = true;
});


loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const candidateToken = tokenInput.value.trim();

    loginError.hidden = true;

    try {
        await loadFiles(candidateToken);

        apiToken = candidateToken;
        sessionStorage.setItem(storageKey, apiToken);

        loginDialog.close();
        loginForm.reset();
    } catch (error) {
        loginError.hidden = false;
    }
});


if (apiToken) {
    loadFiles(apiToken).catch(() => {
        apiToken = "";
        sessionStorage.removeItem(storageKey);
        showDisconnectedState();
    });
} else {
    showDisconnectedState();
}
