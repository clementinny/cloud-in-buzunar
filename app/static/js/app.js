const loginButton = document.querySelector("#login-button");
const loginDialog = document.querySelector("#login-dialog");
const loginForm = document.querySelector("#login-form");
const closeLoginButton = document.querySelector("#close-login");
const usernameInput =
    document.querySelector("#username-input");
const passwordInput =
    document.querySelector("#password-input");
const loginError = document.querySelector("#login-error");
const connectionStatus = document.querySelector("#connection-status");
const filesMessage = document.querySelector("#files-message");
const fileList = document.querySelector("#file-list");

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
let currentUser = null;
const maximumUploadSize = 100 * 1024 * 1024;

let selectedFile = null;

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

async function loginUser(username, password) {
    const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({
            username,
            password,
        }),
    });

    if (!response.ok) {
        if (response.status === 429) {
            throw new Error(
                "Prea multe încercări. Încearcă din nou peste 10 minute.",
            );
        }

        if (response.status === 401) {
            throw new Error(
                "Utilizatorul sau parola sunt incorecte.",
            );
        }

        throw new Error(
            `Autentificarea a eșuat: HTTP ${response.status}`,
        );
    }
    const data = await response.json();

    return data.user;
}


async function logoutUser() {
    const response = await fetch("/api/auth/logout", {
        method: "POST",
    });

    if (!response.ok) {
        throw new Error("Logout failed");
    }
}


async function restoreSession() {
    const response = await fetch("/api/auth/me");

    if (response.status === 401) {
        return null;
    }

    if (!response.ok) {
        throw new Error("Session check failed");
    }

    const data = await response.json();

    return data.user;
}

function uploadFile(file) {
    return new Promise((resolve, reject) => {
        const formData = new FormData();
        const request = new XMLHttpRequest();

        formData.append("file", file);

        request.open("POST", "/api/files");



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

async function openFile(filename) {
    const previewWindow = window.open("about:blank", "_blank");

    if (!previewWindow) {
        throw new Error(
            "Browserul a blocat deschiderea unui tab nou.",
        );
    }

    try {
        const encodedFilename = encodeURIComponent(filename);

        const response = await fetch(
    `/api/files/${encodedFilename}`,
);

        if (!response.ok) {
            throw new Error(
                `Fișierul nu poate fi deschis: HTTP ${response.status}`,
            );
        }

        const fileBlob = await response.blob();
        const fileUrl = URL.createObjectURL(fileBlob);

        previewWindow.location.href = fileUrl;

        setTimeout(() => {
            URL.revokeObjectURL(fileUrl);
        }, 60_000);
    } catch (error) {
        previewWindow.close();
        throw error;
    }
}

async function deleteFile(filename) {
    const encodedFilename = encodeURIComponent(filename);

    const response = await fetch(
    `/api/files/${encodedFilename}`,
    {
        method: "DELETE",
    },
);

    if (!response.ok) {
        throw new Error(
            `Fișierul nu poate fi șters: HTTP ${response.status}`,
        );
    }

    return response.json();
}
function renderFiles(files) {
    fileList.replaceChildren();

    if (files.length === 0) {
        filesMessage.textContent = "Nu există fișiere încă.";
        filesMessage.classList.remove("is-error");
        filesMessage.hidden = false;
        return;
    }

    filesMessage.hidden = true;

    for (const file of files) {
        const item = document.createElement("li");
        const information = document.createElement("div");
        const actions = document.createElement("div");
        const name = document.createElement("span");
        const details = document.createElement("span");
        const openButton = document.createElement("button");
        const deleteButton = document.createElement("button");

        item.className = "file-row";
        information.className = "file-information";
        actions.className = "file-actions";
        name.className = "file-name";
        details.className = "file-details";
        openButton.className = "file-open-button";
        deleteButton.className = "delete-button";

        name.textContent = file.filename;
        details.textContent = formatBytes(file.size_bytes);

        openButton.textContent = "Deschide";
        openButton.type = "button";

        deleteButton.textContent = "Șterge";
        deleteButton.type = "button";

        openButton.addEventListener("click", async () => {
            openButton.disabled = true;
            openButton.textContent = "Se deschide...";

            try {
                await openFile(file.filename);
            } catch (error) {
                filesMessage.textContent = error.message;
                filesMessage.classList.add("is-error");
                filesMessage.hidden = false;
            } finally {
                openButton.disabled = false;
                openButton.textContent = "Deschide";
            }
        });

        deleteButton.addEventListener("click", async () => {
            const confirmed = window.confirm(
                `Ștergi definitiv fișierul „${file.filename}”?`,
            );

            if (!confirmed) {
                return;
            }

            deleteButton.disabled = true;
            deleteButton.textContent = "Se șterge...";

            try {
                await deleteFile(file.filename);
                await loadFiles();

                filesMessage.textContent =
                    `${file.filename} a fost șters.`;
                filesMessage.classList.remove("is-error");
                filesMessage.hidden = false;
            } catch (error) {
                filesMessage.textContent = error.message;
                filesMessage.classList.add("is-error");
                filesMessage.hidden = false;

                deleteButton.disabled = false;
                deleteButton.textContent = "Șterge";
            }
        });

        information.append(name, details);
        actions.append(openButton);

if (currentUser?.role === "admin") {
    actions.append(deleteButton);
}
        item.append(information, actions);
        fileList.append(item);
    }
}
function showDisconnectedState() {
currentUser = null;    
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
    const roleLabel =
        currentUser.role === "admin"
            ? "administrator"
            : "utilizator";

    connectionStatus.textContent =
        `${currentUser.username} · ${roleLabel} · ` +
        `${fileCount} ${label}`;

    loginButton.textContent = "Deconectare";
    uploadForm.hidden = false;
}

async function loadFiles() {
    const response = await fetch("/api/files");

    if (!response.ok) {
        throw new Error(`API returned ${response.status}`);
    }

    const data = await response.json();

    renderFiles(data.files);
    showConnectedState(data.count);
}

loginButton.addEventListener("click", async () => {
    if (currentUser) {
        try {
            await logoutUser();
            showDisconnectedState();
        } catch (error) {
            connectionStatus.textContent =
                "Deconectarea a eșuat.";
        }

        return;
    }

    loginError.hidden = true;
    loginDialog.showModal();
    usernameInput.focus();
});


closeLoginButton.addEventListener("click", () => {
    loginDialog.close();
    loginForm.reset();
    loginError.hidden = true;
});


loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const username = usernameInput.value.trim();
    const password = passwordInput.value;

    loginError.hidden = true;

    try {
        currentUser = await loginUser(username, password);
        await loadFiles();

        loginDialog.close();
        loginForm.reset();
    } catch (error) {
        currentUser = null;
        loginError.textContent = error.message;
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

    if (!selectedFile || !currentUser) {
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
            await uploadFile(selectedFile);

        uploadMessage.textContent =
            `${uploadedFile.filename} a fost încărcat.`;
        uploadMessage.hidden = false;

        clearSelectedFile();
        await loadFiles();
    } catch (error) {
        uploadMessage.textContent = error.message;
        uploadMessage.classList.add("is-error");
        uploadMessage.hidden = false;
    } finally {
        uploadButton.disabled = false;
        uploadProgressWrapper.hidden = true;
    }
});

async function initializeApplication() {
    try {
        const user = await restoreSession();

        if (user === null) {
            showDisconnectedState();
            return;
        }

        currentUser = user;
        await loadFiles();
    } catch (error) {
        showDisconnectedState();
    }
}


initializeApplication();
