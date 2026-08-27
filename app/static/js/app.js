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
const uploadForm = document.querySelector("#upload-form");
const dropZone = document.querySelector("#drop-zone");
const fileInput = document.querySelector("#file-input");
const uploadDetails = document.querySelector("#upload-details");
const selectedFileName =
    document.querySelector("#selected-file-name");
const selectedFileSize =
    document.querySelector("#selected-file-size");
const clearFileButton =
    document.querySelector("#clear-file-button");
const uploadButton = document.querySelector("#upload-button");
const uploadProgressWrapper =
    document.querySelector("#upload-progress-wrapper");
const uploadProgress =
    document.querySelector("#upload-progress");
const uploadPercent =
    document.querySelector("#upload-percent");
const uploadMessage =
    document.querySelector("#upload-message");
let apiToken = sessionStorage.getItem(storageKey) ?? "";
const maximumUploadSize = 100 * 1024 * 1024;

let selectedFile = null;

function formatBytes(bytes) {
    if (bytes === 0) {
        return "0 B";
    }
function clearSelectedFile() {
    selectedFile = null;
    fileInput.value = "";
    uploadDetails.hidden = true;
}


function selectFile(file) {
    uploadMessage.hidden = true;
    uploadMessage.classList.remove("is-error");

    if (file.size > maximumUploadSize) {
        clearSelectedFile();
        uploadMessage.textContent =
            "Fișierul depășește limita de 100 MB.";
        uploadMessage.classList.add("is-error");
        uploadMessage.hidden = false;
        return;
    }

    selectedFile = file;
    selectedFileName.textContent = file.name;
    selectedFileSize.textContent = formatBytes(file.size);
    uploadDetails.hidden = false;
}


function uploadFile(file, token) {
    return new Promise((resolve, reject) => {
        const formData = new FormData();
        const request = new XMLHttpRequest();

        formData.append("file", file);

        request.open("POST", "/api/files");

        request.setRequestHeader(
            "Authorization",
            `Bearer ${token}`,
        );

        request.upload.addEventListener("progress", (event) => {
            if (!event.lengthComputable) {
                return;
            }

            const percent = Math.round(
                (event.loaded / event.total) * 100,
            );

            uploadProgress.value = percent;
            uploadPercent.textContent = `${percent}%`;
        });

        request.addEventListener("load", () => {
            if (request.status === 201) {
                resolve(JSON.parse(request.responseText));
                return;
            }

            let message = `Upload eșuat: HTTP ${request.status}`;

            if (request.status === 409) {
                message = "Există deja un fișier cu acest nume.";
            } else if (request.status === 401) {
                message = "Sesiunea nu mai este autorizată.";
            } else if (request.status === 413) {
                message = "Fișierul depășește limita serverului.";
            }

            reject(new Error(message));
        });

        request.addEventListener("error", () => {
            reject(new Error("Conexiunea cu serverul a eșuat."));
        });

        request.send(formData);
    });
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
    uploadForm.hidden = true;
    clearSelectedFile();
}


function showConnectedState(fileCount) {
    const label = fileCount === 1 ? "fișier" : "fișiere";

    connectionStatus.textContent =
        `Conectat · ${fileCount} ${label}`;
    loginButton.textContent = "Deconectare";
uploadForm.hidden = false;
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

fileInput.addEventListener("change", () => {
    const file = fileInput.files[0];

    if (file) {
        selectFile(file);
    }
});


clearFileButton.addEventListener("click", () => {
    clearSelectedFile();
    uploadMessage.hidden = true;
});


for (const eventName of ["dragenter", "dragover"]) {
    dropZone.addEventListener(eventName, (event) => {
        event.preventDefault();
        dropZone.classList.add("is-dragging");
    });
}


for (const eventName of ["dragleave", "drop"]) {
    dropZone.addEventListener(eventName, (event) => {
        event.preventDefault();
        dropZone.classList.remove("is-dragging");
    });
}


dropZone.addEventListener("drop", (event) => {
    const file = event.dataTransfer.files[0];

    if (file) {
        selectFile(file);
    }
});


uploadForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    if (!selectedFile || !apiToken) {
        return;
    }

    uploadButton.disabled = true;
    uploadProgress.value = 0;
    uploadPercent.textContent = "0%";
    uploadProgressWrapper.hidden = false;
    uploadMessage.hidden = true;
    uploadMessage.classList.remove("is-error");

    try {
        const uploadedFile =
            await uploadFile(selectedFile, apiToken);

        uploadMessage.textContent =
            `${uploadedFile.filename} a fost încărcat.`;
        uploadMessage.hidden = false;

        clearSelectedFile();
        await loadFiles(apiToken);
    } catch (error) {
        uploadMessage.textContent = error.message;
        uploadMessage.classList.add("is-error");
        uploadMessage.hidden = false;
    } finally {
        uploadButton.disabled = false;
        uploadProgressWrapper.hidden = true;
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
