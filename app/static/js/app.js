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

const folderToolbar =
    document.querySelector("#folder-toolbar");
const folderBreadcrumbs =
    document.querySelector("#folder-breadcrumbs");
const backFolderButton =
    document.querySelector("#back-folder-button");
const newFolderButton =
    document.querySelector("#new-folder-button");
const vaultModeSwitch =
    document.querySelector("#vault-mode-switch");
const personalVaultButton =
    document.querySelector("#personal-vault-button");
const adminVaultButton =
    document.querySelector("#admin-vault-button");
const adminVaultControls =
    document.querySelector("#admin-vault-controls");
const adminVaultSelect =
    document.querySelector("#admin-vault-select");
const folderDialog =
    document.querySelector("#folder-dialog");
const folderForm =
    document.querySelector("#folder-form");
const folderNameInput =
    document.querySelector("#folder-name-input");
const folderError =
    document.querySelector("#folder-error");
const cancelFolderButton =
    document.querySelector("#cancel-folder-button");

const renameDialog =
    document.querySelector("#rename-dialog");
const renameForm =
    document.querySelector("#rename-form");
const renameCurrentName =
    document.querySelector("#rename-current-name");
const renameNameInput =
    document.querySelector("#rename-name-input");
const renameError =
    document.querySelector("#rename-error");
const cancelRenameButton =
    document.querySelector("#cancel-rename-button");

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

let currentPath = "";
let currentParentPath = null;

let vaultMode = "personal";
let selectedVaultUserId = null;
let selectedVaultOwner = null;
const maximumUploadSize = 100 * 1024 * 1024;

let selectedFile = null;

let entryBeingRenamed = null;

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

function getVaultApiBase() {
    if (vaultMode !== "admin") {
        return "/api";
    }

    if (selectedVaultUserId === null) {
        throw new Error(
            "Nu a fost selectat niciun seif.",
        );
    }

    const encodedUserId =
        encodeURIComponent(
            String(selectedVaultUserId),
        );

    return `/api/admin/vaults/${encodedUserId}`;
}

async function renameEntry(relativePath, newName) {
    const encodedPath =
        encodeRelativePath(relativePath);

    const response = await fetch(
        `${getVaultApiBase()}/entries/${encodedPath}`,
        {
            method: "PATCH",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                name: newName,
            }),
        },
    );

    if (!response.ok) {
        let message =
            `Redenumirea a eșuat: HTTP ${response.status}`;

        const data = await response
            .json()
            .catch(() => null);

        if (data?.error) {
            message = data.error;
        } else if (response.status === 409) {
            message =
                "Există deja un fișier sau folder cu acest nume.";
        } else if (response.status === 404) {
            message =
                "Fișierul sau folderul nu mai există.";
        }

        throw new Error(message);
    }

    return response.json();
}

async function createFolder(parentPath, folderName) {
    const response = await fetch(
    `${getVaultApiBase()}/folders`,
    {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({
            path: parentPath,
            name: folderName,
        }),
    });

    const data = await response.json();

    if (!response.ok) {
        throw new Error(
            data.error ?? `HTTP ${response.status}`,
        );
    }

    return data;
}

function renderFolderNavigation(path, parentPath) {
    currentPath = path;
    currentParentPath = parentPath;

    folderToolbar.hidden = false;
    backFolderButton.disabled = parentPath === null;
    folderBreadcrumbs.replaceChildren();

    function addBreadcrumb(label, targetPath) {
        const button = document.createElement("button");

        button.type = "button";
        button.className = "breadcrumb-button";
        button.textContent = label;

        button.addEventListener("click", () => {
            loadFiles(targetPath).catch((error) => {
                filesMessage.textContent = error.message;
                filesMessage.classList.add("is-error");
                filesMessage.hidden = false;
            });
        });

        folderBreadcrumbs.append(button);
    }

    addBreadcrumb("Acasă", "");

    if (!path) {
        return;
    }

    let accumulatedPath = "";

    for (const part of path.split("/")) {
        const separator = document.createElement("span");

        separator.className = "breadcrumb-separator";
        separator.textContent = "/";

        folderBreadcrumbs.append(separator);

        accumulatedPath = accumulatedPath
            ? `${accumulatedPath}/${part}`
            : part;

        addBreadcrumb(part, accumulatedPath);
    }

    const currentButton =
        folderBreadcrumbs.lastElementChild;

    currentButton?.setAttribute(
        "aria-current",
        "page",
    );
}

async function loadAdminVaults() {
    const response = await fetch("/api/admin/vaults");

    if (!response.ok) {
        throw new Error(
            `Lista seifurilor nu poate fi încărcată: HTTP ${response.status}`,
        );
    }

    const data = await response.json();

    adminVaultSelect.replaceChildren();

    for (const vault of data.vaults) {
        const option = document.createElement("option");
        const entryLabel =
            vault.entry_count === 1 ? "element" : "elemente";

        option.value = String(vault.user.id);
        option.textContent =
            `${vault.user.username} · ` +
            `${vault.entry_count} ${entryLabel}`;

        adminVaultSelect.append(option);
    }

    if (data.vaults.length === 0) {
        selectedVaultUserId = null;
        selectedVaultOwner = null;
        return [];
    }

    const selectedVault =
        data.vaults.find(
            (vault) =>
                vault.user.id === selectedVaultUserId,
        ) ?? data.vaults[0];

    selectedVaultUserId = selectedVault.user.id;
    selectedVaultOwner = selectedVault.user;
    adminVaultSelect.value =
        String(selectedVaultUserId);

    return data.vaults;
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

function uploadFile(file, path) {
    return new Promise((resolve, reject) => {
        const formData = new FormData();
        const request = new XMLHttpRequest();

        formData.append("file", file);
        formData.append("path", path);
        request.open(
    "POST",
    `${getVaultApiBase()}/files`,
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

function encodeRelativePath(path) {
    return path
        .split("/")
        .map((part) => encodeURIComponent(part))
        .join("/");
}

async function openFile(relativePath) {
    const previewWindow = window.open("about:blank", "_blank");

    if (!previewWindow) {
        throw new Error(
            "Browserul a blocat deschiderea unui tab nou.",
        );
    }

    try {
        const encodedPath = encodeRelativePath(relativePath);

        const response = await fetch(
    `${getVaultApiBase()}/files/${encodedPath}`,
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

async function downloadFile(relativePath, filename) {
    const encodedPath =
        encodeRelativePath(relativePath);

    const response = await fetch(
        `${getVaultApiBase()}/files/${encodedPath}`,
    );

    if (!response.ok) {
        throw new Error(
            `Fișierul nu poate fi descărcat: HTTP ${response.status}`,
        );
    }

    const fileBlob = await response.blob();
    const fileUrl = URL.createObjectURL(fileBlob);
    const downloadLink =
        document.createElement("a");

    downloadLink.href = fileUrl;
    downloadLink.download = filename;
    downloadLink.hidden = true;

    document.body.append(downloadLink);
    downloadLink.click();
    downloadLink.remove();

    setTimeout(() => {
        URL.revokeObjectURL(fileUrl);
    }, 60_000);
}

async function deleteFile(relativePath) {
    const encodedPath = encodeRelativePath(relativePath);

    const response = await fetch(
    `${getVaultApiBase()}/files/${encodedPath}`,
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

async function deleteFolder(relativePath) {
    const encodedPath =
        encodeRelativePath(relativePath);

    const response = await fetch(
        `${getVaultApiBase()}/folders/${encodedPath}`,
        {
            method: "DELETE",
        },
    );

    if (!response.ok) {
        let message =
            `Folderul nu poate fi șters: HTTP ${response.status}`;

        if (response.status === 404) {
            message = "Folderul nu mai există.";
        } else if (response.status === 400) {
            message =
                "Folderul nu poate fi șters din această locație.";
        }

        throw new Error(message);
    }

    return response.json();
}

function renderFiles(entries) {
    fileList.replaceChildren();

    if (entries.length === 0) {
        filesMessage.textContent =
            "Folderul este gol.";
        filesMessage.classList.remove("is-error");
        filesMessage.hidden = false;
        return;
    }

    filesMessage.hidden = true;

    for (const entry of entries) {
        const item = document.createElement("li");
        const information = document.createElement("div");
        const actions = document.createElement("div");
        const name = document.createElement("span");
        const details = document.createElement("span");
        const openButton = document.createElement("button");

        item.className = "file-row";
        information.className = "file-information";
        actions.className = "file-actions";
        name.className = "file-name";
        details.className = "file-details";
        openButton.className = "file-open-button";

        if (entry.type === "folder") {
            name.textContent = `📁 ${entry.name}`;
            details.textContent = "Folder";
            openButton.textContent = "Deschide";
        } else {
            name.textContent = `📄 ${entry.name}`;
            details.textContent =
                formatBytes(entry.size_bytes);
            openButton.textContent = "Deschide";
        }

        openButton.type = "button";

        openButton.addEventListener(
            "click",
            async () => {
                openButton.disabled = true;
                openButton.textContent =
                    entry.type === "folder"
                        ? "Se deschide..."
                        : "Se încarcă...";

                try {
                    if (entry.type === "folder") {
                        await loadFiles(entry.path);
                    } else {
                        await openFile(entry.path);
                    }
                } catch (error) {
                    filesMessage.textContent =
                        error.message;
                    filesMessage.classList.add(
                        "is-error",
                    );
                    filesMessage.hidden = false;
                } finally {
                    openButton.disabled = false;
                    openButton.textContent = "Deschide";
                }
            },
        );

        information.append(name, details);
        actions.append(openButton);

if (entry.type === "file") {
    const downloadButton =
        document.createElement("button");

    downloadButton.className =
        "file-open-button download-button";
    downloadButton.textContent = "Descarcă";
    downloadButton.type = "button";

    downloadButton.addEventListener(
        "click",
        async () => {
            downloadButton.disabled = true;
            downloadButton.textContent =
                "Se descarcă...";

            try {
                await downloadFile(
                    entry.path,
                    entry.name,
                );
            } catch (error) {
                filesMessage.textContent =
                    error.message;
                filesMessage.classList.add(
                    "is-error",
                );
                filesMessage.hidden = false;
            } finally {
                downloadButton.disabled = false;
                downloadButton.textContent =
                    "Descarcă";
            }
        },
    );

    actions.append(downloadButton);
}

const renameButton =
    document.createElement("button");

renameButton.className =
    "file-open-button rename-button";
renameButton.textContent = "Redenumește";
renameButton.type = "button";

renameButton.addEventListener(
    "click",
    () => {
        entryBeingRenamed = entry;

        renameCurrentName.textContent =
            `Nume actual: ${entry.name}`;

        renameNameInput.value = entry.name;

        renameError.textContent = "";
        renameError.hidden = true;

        renameDialog.showModal();
        renameNameInput.focus();
        renameNameInput.select();
    },
);

actions.append(renameButton);

        const deleteButton =
    document.createElement("button");

deleteButton.className = "delete-button";
deleteButton.textContent = "Șterge";
deleteButton.type = "button";

deleteButton.addEventListener(
    "click",
    async () => {
        const confirmationMessage =
            entry.type === "folder"
                ? (
                    `Ștergi folderul „${entry.name}” ` +
                    "și TOT conținutul lui? " +
                    "Acțiunea nu poate fi anulată."
                )
                : (
                    `Ștergi definitiv fișierul ` +
                    `„${entry.name}”?`
                );

        const confirmed =
            window.confirm(confirmationMessage);

        if (!confirmed) {
            return;
        }

        deleteButton.disabled = true;
        deleteButton.textContent = "Se șterge...";

        try {
            if (entry.type === "folder") {
                await deleteFolder(entry.path);
            } else {
                await deleteFile(entry.path);
            }

            await loadFiles(currentPath);

            filesMessage.textContent =
                entry.type === "folder"
                    ? `Folderul ${entry.name} a fost șters.`
                    : `${entry.name} a fost șters.`;

            filesMessage.classList.remove(
                "is-error",
            );
            filesMessage.hidden = false;
        } catch (error) {
            filesMessage.textContent =
                error.message;
            filesMessage.classList.add(
                "is-error",
            );
            filesMessage.hidden = false;

            deleteButton.disabled = false;
            deleteButton.textContent = "Șterge";
        }
    },
);

actions.append(deleteButton);


        item.append(information, actions);
        fileList.append(item);
    }
}


function showDisconnectedState() {
    currentUser = null;
    currentPath = "";
    currentParentPath = null;

    vaultMode = "personal";
    selectedVaultUserId = null;
    selectedVaultOwner = null;

    vaultModeSwitch.hidden = true;
    adminVaultControls.hidden = true;
    adminVaultSelect.replaceChildren();

    personalVaultButton.classList.add("is-active");
    adminVaultButton.classList.remove("is-active");

    folderToolbar.hidden = true;
    folderBreadcrumbs.replaceChildren();
    newFolderButton.hidden = false;

    connectionStatus.textContent = "Neconectat";
    loginButton.textContent = "Conectare";

    filesMessage.textContent =
        "Conectează-te pentru a vedea fișierele.";
    filesMessage.hidden = false;

    fileList.replaceChildren();
    uploadForm.hidden = true;
    clearSelectedFile();

    uploadMessage.textContent = "";
    uploadMessage.classList.remove("is-error");
    uploadMessage.hidden = true;
}


function showConnectedState(fileCount) {
    const label =
        fileCount === 1 ? "element" : "elemente";

    vaultModeSwitch.hidden =
        currentUser.role !== "admin";

    if (vaultMode === "admin") {
        const ownerName =
            selectedVaultOwner?.username ??
            "utilizator necunoscut";

        connectionStatus.textContent =
            `Administrezi seiful lui ${ownerName} · ` +
            `${fileCount} ${label}`;

        uploadForm.hidden = false;
        newFolderButton.hidden = false;
        adminVaultControls.hidden = false;
    } else {
        const roleLabel =
            currentUser.role === "admin"
                ? "administrator"
                : "utilizator";

        connectionStatus.textContent =
            `${currentUser.username} · ${roleLabel} · ` +
            `${fileCount} ${label}`;

        uploadForm.hidden = false;
        newFolderButton.hidden = false;
        adminVaultControls.hidden = true;
    }

    loginButton.textContent = "Deconectare";
}

async function loadFiles(path = currentPath) {
    const query = new URLSearchParams({
        path,
    });

    let endpoint = `/api/files?${query.toString()}`;

    if (vaultMode === "admin") {
        if (selectedVaultUserId === null) {
            throw new Error(
                "Nu a fost selectat niciun seif.",
            );
        }

        const encodedUserId =
            encodeURIComponent(
                String(selectedVaultUserId),
            );

        endpoint =
            `/api/admin/vaults/${encodedUserId}/files` +
            `?${query.toString()}`;
    }

    const response = await fetch(endpoint);

    if (!response.ok) {
        throw new Error(
            `API returned ${response.status}`,
        );
    }

    const data = await response.json();

    if (vaultMode === "admin") {
        selectedVaultOwner = data.owner;
    }

    renderFolderNavigation(
        data.path,
        data.parent_path,
    );

    renderFiles(data.entries);
    showConnectedState(data.count);
}


function showVaultError(error) {
    filesMessage.textContent = error.message;
    filesMessage.classList.add("is-error");
    filesMessage.hidden = false;
}


personalVaultButton.addEventListener(
    "click",
    async () => {
        vaultMode = "personal";
        selectedVaultUserId = null;
        selectedVaultOwner = null;
        currentPath = "";
        currentParentPath = null;

        personalVaultButton.classList.add(
            "is-active",
        );
        adminVaultButton.classList.remove(
            "is-active",
        );
        adminVaultControls.hidden = true;

        try {
            await loadFiles("");
        } catch (error) {
            showVaultError(error);
        }
    },
);


adminVaultButton.addEventListener(
    "click",
    async () => {
        if (
            currentUser === null ||
            currentUser.role !== "admin"
        ) {
            return;
        }

        vaultMode = "admin";
        currentPath = "";
        currentParentPath = null;

        personalVaultButton.classList.remove(
            "is-active",
        );
        adminVaultButton.classList.add(
            "is-active",
        );
        adminVaultControls.hidden = false;

        try {
            const vaults = await loadAdminVaults();

            if (vaults.length === 0) {
                fileList.replaceChildren();
                folderToolbar.hidden = true;
                uploadForm.hidden = true;

                filesMessage.textContent =
                    "Nu există seifuri.";
                filesMessage.hidden = false;
                return;
            }

            await loadFiles("");
        } catch (error) {
            showVaultError(error);
        }
    },
);


adminVaultSelect.addEventListener(
    "change",
    async () => {
        const userId = Number.parseInt(
            adminVaultSelect.value,
            10,
        );

        if (!Number.isInteger(userId)) {
            return;
        }

        selectedVaultUserId = userId;
        selectedVaultOwner = null;
        currentPath = "";
        currentParentPath = null;

        try {
            await loadFiles("");
        } catch (error) {
            showVaultError(error);
        }
    },
);


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


backFolderButton.addEventListener(
    "click",
    async () => {
        if (currentParentPath === null) {
            return;
        }

        backFolderButton.disabled = true;

        try {
            await loadFiles(currentParentPath);
        } catch (error) {
            filesMessage.textContent = error.message;
            filesMessage.classList.add("is-error");
            filesMessage.hidden = false;

            backFolderButton.disabled = false;
        }
    },
);


newFolderButton.addEventListener("click", () => {
    folderForm.reset();
    folderError.hidden = true;
    folderDialog.showModal();
    folderNameInput.focus();
});

cancelFolderButton.addEventListener(
    "click",
    () => {
        folderDialog.close();
        folderForm.reset();
        folderError.hidden = true;
    },
);

folderForm.addEventListener(
    "submit",
    async (event) => {
        event.preventDefault();

        const folderName =
            folderNameInput.value.trim();
        const submitButton =
            folderForm.querySelector(
                'button[type="submit"]',
            );

        folderError.hidden = true;
        submitButton.disabled = true;

        try {
            const createdFolder =
                await createFolder(
                    currentPath,
                    folderName,
                );

            folderDialog.close();
            folderForm.reset();

            await loadFiles(currentPath);

            filesMessage.textContent =
                `Folderul „${createdFolder.name}” a fost creat.`;
            filesMessage.classList.remove(
                "is-error",
            );
            filesMessage.hidden = false;
        } catch (error) {
            folderError.textContent =
                error.message;
            folderError.hidden = false;
        } finally {
            submitButton.disabled = false;
        }
    },
);


cancelRenameButton.addEventListener(
    "click",
    () => {
        renameDialog.close();
    },
);


renameDialog.addEventListener(
    "close",
    () => {
        renameForm.reset();
        renameCurrentName.textContent = "";
        renameError.textContent = "";
        renameError.hidden = true;
        entryBeingRenamed = null;
    },
);


renameForm.addEventListener(
    "submit",
    async (event) => {
        event.preventDefault();

        if (entryBeingRenamed === null) {
            return;
        }

        const newName =
            renameNameInput.value.trim();

        if (!newName) {
            renameError.textContent =
                "Numele nu poate fi gol.";
            renameError.hidden = false;
            return;
        }

        const entryToRename =
            entryBeingRenamed;

        const submitButton =
            renameForm.querySelector(
                'button[type="submit"]',
            );

        renameError.hidden = true;
        submitButton.disabled = true;
        submitButton.textContent =
            "Se salvează...";

        let renamedEntry;

        try {
            renamedEntry = await renameEntry(
                entryToRename.path,
                newName,
            );
        } catch (error) {
            renameError.textContent =
                error.message;
            renameError.hidden = false;
            return;
        } finally {
            submitButton.disabled = false;
            submitButton.textContent =
                "Salvează numele";
        }

        renameDialog.close();

        try {
            await loadFiles(currentPath);

            filesMessage.textContent =
                `${entryToRename.name} a fost ` +
                `redenumit în ${renamedEntry.name}.`;

            filesMessage.classList.remove(
                "is-error",
            );
            filesMessage.hidden = false;
        } catch (error) {
            showVaultError(error);
        }
    },
);

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
            await uploadFile(
                selectedFile,
                currentPath,
);

        uploadMessage.textContent =
            `${uploadedFile.name} a fost încărcat.`;
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
