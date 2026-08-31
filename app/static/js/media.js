const adminPanel =
    document.querySelector("#media-admin-panel");
const personalMediaButton =
    document.querySelector("#personal-media-button");
const adminMediaButton =
    document.querySelector("#admin-media-button");
const ownerControls =
    document.querySelector("#media-owner-controls");
const ownerSelect =
    document.querySelector("#media-owner-select");

const userStatus =
    document.querySelector("#media-user-status");
const refreshButton =
    document.querySelector("#refresh-media-button");
const uploadForm =
    document.querySelector("#media-upload-form");
const dropZone =
    document.querySelector("#media-drop-zone");
const fileInput =
    document.querySelector("#media-file-input");
const uploadDetails =
    document.querySelector("#media-upload-details");
const selectedName =
    document.querySelector("#media-selected-name");
const selectedSize =
    document.querySelector("#media-selected-size");
const clearButton =
    document.querySelector("#clear-media-button");
const uploadButton =
    document.querySelector("#upload-media-button");
const progressWrapper =
    document.querySelector("#media-progress-wrapper");
const uploadProgress =
    document.querySelector("#media-upload-progress");
const uploadPercent =
    document.querySelector("#media-upload-percent");
const uploadMessage =
    document.querySelector("#media-upload-message");
const filters =
    document.querySelector("#media-filters");
const mediaCount =
    document.querySelector("#media-count");
const mediaMessage =
    document.querySelector("#media-message");
const mediaGrid =
    document.querySelector("#media-grid");

const maximumUploadSize =
    50 * 1024 * 1024 * 1024;
const uploadChunkSize =
    16 * 1024 * 1024;
let selectedFile = null;
let mediaFiles = [];
let activeFilter = "all";
let currentUser = null;
let mediaMode = "personal";
let selectedOwnerId = null;
let selectedOwnerName = null;


function getOwnerQuery(download = false) {
    const parameters = new URLSearchParams();

    if (
        mediaMode === "admin"
        && selectedOwnerId !== null
    ) {
        parameters.set(
            "owner_id",
            String(selectedOwnerId),
        );
    }

    if (download) {
        parameters.set("download", "1");
    }

    const query = parameters.toString();

    return query ? `?${query}` : "";
}

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


function encodeMediaPath(path) {
    return path
        .split("/")
        .map((part) => encodeURIComponent(part))
        .join("/");
}

function getMediaUrl(path, download = false) {
    const encodedPath = encodeMediaPath(path);

    return (
        `/api/media/${encodedPath}` +
        getOwnerQuery(download)
    );
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
            "Fișierul depășește limita de 50 GB.";
        uploadMessage.classList.add("is-error");
        uploadMessage.hidden = false;
        return;
    }

    selectedFile = file;
    selectedName.textContent = file.name;
    selectedSize.textContent = formatBytes(file.size);
    uploadDetails.hidden = false;
}


function createPreview(file) {
    const preview = document.createElement("div");
    const mediaUrl = getMediaUrl(file.path);

    preview.className =
        `media-preview media-preview-${file.media_type}`;

    if (file.media_type === "image") {
        const image = document.createElement("img");

        image.src = mediaUrl;
        image.alt = file.name;
        image.loading = "lazy";

        preview.append(image);
        return preview;
    }

    if (file.media_type === "video") {
        const video = document.createElement("video");

        video.src = mediaUrl;
        video.controls = true;
        video.preload = "metadata";

        preview.append(video);
        return preview;
    }

    const audioIcon = document.createElement("span");
    const audio = document.createElement("audio");

    audioIcon.className = "media-audio-icon";
    audioIcon.textContent = "♫";

    audio.src = mediaUrl;
    audio.controls = true;
    audio.preload = "metadata";

    preview.append(audioIcon, audio);
    return preview;
}


async function deleteMedia(file) {
    const confirmed = window.confirm(
        `Ștergi definitiv „${file.name}”?`,
    );

    if (!confirmed) {
        return;
    }

    const response = await fetch(
        getMediaUrl(file.path),
        {
            method: "DELETE",
        },
    );

    if (!response.ok) {
        throw new Error(
            `Ștergerea a eșuat: HTTP ${response.status}`,
        );
    }

    await loadMedia();

    mediaMessage.textContent =
        `${file.name} a fost șters.`;
    mediaMessage.classList.remove("is-error");
    mediaMessage.hidden = false;
}


function renderMedia() {
    mediaGrid.replaceChildren();

    const visibleFiles =
        activeFilter === "all"
            ? mediaFiles
            : mediaFiles.filter(
                (file) =>
                    file.media_type === activeFilter,
            );

    mediaCount.textContent =
        `${mediaFiles.length} ${
            mediaFiles.length === 1
                ? "element"
                : "elemente"
        }`;

    filters.hidden = mediaFiles.length === 0;

    if (visibleFiles.length === 0) {
        mediaMessage.textContent =
            mediaFiles.length === 0
                ? "Biblioteca este goală."
                : "Nu există elemente în această categorie.";

        mediaMessage.classList.remove("is-error");
        mediaMessage.hidden = false;
        return;
    }

    mediaMessage.hidden = true;

    for (const file of visibleFiles) {
        const card = document.createElement("article");
        const preview = createPreview(file);
        const information = document.createElement("div");
        const name = document.createElement("h3");
        const details = document.createElement("p");
        const actions = document.createElement("div");
        const downloadLink = document.createElement("a");
        const deleteButton = document.createElement("button");

        card.className = "media-card";
        information.className = "media-card-information";
        actions.className = "media-card-actions";

        name.textContent = file.name;
        details.textContent =
            `${formatBytes(file.size_bytes)} · ` +
            file.media_type;

        downloadLink.href = getMediaUrl(
            file.path,
            true,
        );
        downloadLink.textContent = "Descarcă";
        downloadLink.className = "media-download-button";
        downloadLink.setAttribute("download", file.name);

        deleteButton.type = "button";
        deleteButton.textContent = "Șterge";
        deleteButton.className = "delete-button";

        deleteButton.addEventListener(
            "click",
            async () => {
                deleteButton.disabled = true;
                deleteButton.textContent = "Se șterge...";

                try {
                    await deleteMedia(file);
                } catch (error) {
                    mediaMessage.textContent =
                        error.message;
                    mediaMessage.classList.add(
                        "is-error",
                    );
                    mediaMessage.hidden = false;

                    deleteButton.disabled = false;
                    deleteButton.textContent = "Șterge";
                }
            },
        );

        information.append(name, details);
        actions.append(downloadLink, deleteButton);
        card.append(preview, information, actions);
        mediaGrid.append(card);
    }
}


async function loadMedia() {
    refreshButton.disabled = true;

    try {
        const response = await fetch(
            `/api/media${getOwnerQuery()}`,
);

        if (response.status === 401) {
            throw new Error(
                "Conectează-te din dashboard.",
            );
        }

        if (!response.ok) {
            throw new Error(
                `Biblioteca nu poate fi încărcată: HTTP ${response.status}`,
            );
        }

        const data = await response.json();

        mediaFiles = data.files;
        renderMedia();
    } finally {
        refreshButton.disabled = false;
    }
}





async function readJsonResponse(response) {
    let data = null;

    try {
        data = await response.json();
    } catch (error) {
        data = null;
    }

    if (!response.ok) {
        throw new Error(
            data?.error ??
            `Cererea a eșuat: HTTP ${response.status}`,
        );
    }

    return data;
}


async function initializeUpload(file) {
    const fingerprint =
        `${file.name}:${file.size}:${file.lastModified}`;

    const response = await fetch(
        `/api/media/uploads${getOwnerQuery()}`,
        {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                filename: file.name,
                size: file.size,
                fingerprint,
            }),
        },
    );

    return readJsonResponse(response);
}


async function sendUploadChunk(
    uploadId,
    chunk,
    offset,
) {
    const response = await fetch(
        `/api/media/uploads/${uploadId}` +
            getOwnerQuery(),
        {
            method: "PUT",
            headers: {
                "Content-Type":
                    "application/octet-stream",
                "X-Upload-Offset":
                    String(offset),
            },
            body: chunk,
        },
    );

    return readJsonResponse(response);
}

function updateMediaStatus() {
    if (
        mediaMode === "admin"
        && selectedOwnerName
    ) {
        userStatus.textContent =
            `Administrezi biblioteca lui ` +
            `${selectedOwnerName}`;
        return;
    }

    userStatus.textContent =
        `${currentUser.username} · ${
            currentUser.role === "admin"
                ? "administrator"
                : "utilizator"
        }`;
}


async function loadMediaOwners() {
    const response = await fetch(
        "/api/admin/vaults"
    );

    const data = await readJsonResponse(response);

    ownerSelect.replaceChildren();

    for (const vault of data.vaults) {
        const option = document.createElement(
            "option"
        );

        option.value = String(vault.user.id);
        option.textContent = vault.user.username;

        ownerSelect.append(option);
    }

    if (data.vaults.length === 0) {
        selectedOwnerId = null;
        selectedOwnerName = null;
        return;
    }

    const firstOwner = data.vaults[0].user;

    selectedOwnerId = firstOwner.id;
    selectedOwnerName = firstOwner.username;
    ownerSelect.value = String(firstOwner.id);
}


async function completeUpload(uploadId) {
    const response = await fetch(
        `/api/media/uploads/${uploadId}/complete` +
            getOwnerQuery(),
        {
            method: "POST",
        },
    );

    return readJsonResponse(response);
}


async function uploadMedia(file) {
    const upload = await initializeUpload(file);

    let offset = upload.received_bytes;

    uploadProgress.value = Math.round(
        (offset / file.size) * 100,
    );
    uploadPercent.textContent =
        `${uploadProgress.value}%`;

    if (upload.resumed && offset > 0) {
        uploadMessage.textContent =
            `Upload reluat de la ${formatBytes(offset)}.`;
        uploadMessage.classList.remove("is-error");
        uploadMessage.hidden = false;
    }

    while (offset < file.size) {
        const nextOffset = Math.min(
            offset + uploadChunkSize,
            file.size,
        );

        const chunk = file.slice(
            offset,
            nextOffset,
        );

        const result = await sendUploadChunk(
            upload.upload_id,
            chunk,
            offset,
        );

        offset = result.received_bytes;

        const percent = Math.round(
            (offset / file.size) * 100,
        );

        uploadProgress.value = percent;
        uploadPercent.textContent =
            `${percent}%`;
    }

    return completeUpload(upload.upload_id);
}

async function initializeMediaPage() {
    try {
        const response = await fetch("/api/auth/me");

        if (!response.ok) {
            throw new Error(
                "Nu ești conectat. Revino în dashboard și conectează-te.",
            );
        }

        const data = await response.json();
        const user = data.user;
        currentUser = user;

        if (currentUser.role === "admin") {
            adminPanel.hidden = false;
            await loadMediaOwners();
}
        updateMediaStatus();

        uploadForm.hidden = false;
        refreshButton.disabled = false;

        await loadMedia();
    } catch (error) {
        userStatus.textContent = "Neconectat";
        mediaMessage.textContent = error.message;
        mediaMessage.classList.add("is-error");
        mediaMessage.hidden = false;
    }
}


fileInput.addEventListener("change", () => {
    const file = fileInput.files[0];

    if (file) {
        selectFile(file);
    }
});


clearButton.addEventListener("click", () => {
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


uploadForm.addEventListener(
    "submit",
    async (event) => {
        event.preventDefault();

        if (!selectedFile) {
            return;
        }

        uploadButton.disabled = true;
        clearButton.disabled = true;
        fileInput.disabled = true;
        progressWrapper.hidden = false;
        uploadProgress.value = 0;
        uploadPercent.textContent = "0%";
        uploadMessage.hidden = true;

        try {
            const uploadedFile =
                await uploadMedia(selectedFile);

            clearSelectedFile();
            await loadMedia();

            uploadMessage.textContent =
                `${uploadedFile.name} a fost încărcat.`;
            uploadMessage.classList.remove("is-error");
            uploadMessage.hidden = false;
        } catch (error) {
            uploadMessage.textContent = error.message;
            uploadMessage.classList.add("is-error");
            uploadMessage.hidden = false;
        } finally {
            uploadButton.disabled = false;
            clearButton.disabled = false;
            fileInput.disabled = false;
            progressWrapper.hidden = true;
        }
    },
);


filters.addEventListener("click", (event) => {
    const button = event.target.closest(
        "[data-filter]",
    );

    if (!button) {
        return;
    }

    activeFilter = button.dataset.filter;

    for (
        const filterButton
        of filters.querySelectorAll("[data-filter]")
    ) {
        filterButton.classList.toggle(
            "is-active",
            filterButton === button,
        );
    }

    renderMedia();
});


refreshButton.addEventListener("click", () => {
    loadMedia().catch((error) => {
        mediaMessage.textContent = error.message;
        mediaMessage.classList.add("is-error");
        mediaMessage.hidden = false;
    });
});

personalMediaButton.addEventListener(
    "click",
    async () => {
        mediaMode = "personal";

        personalMediaButton.classList.add(
            "is-active"
        );
        adminMediaButton.classList.remove(
            "is-active"
        );

        ownerControls.hidden = true;
        activeFilter = "all";

        updateMediaStatus();
        await loadMedia();
    },
);


adminMediaButton.addEventListener(
    "click",
    async () => {
        mediaMode = "admin";

        adminMediaButton.classList.add(
            "is-active"
        );
        personalMediaButton.classList.remove(
            "is-active"
        );

        ownerControls.hidden = false;
        activeFilter = "all";

        updateMediaStatus();
        await loadMedia();
    },
);


ownerSelect.addEventListener(
    "change",
    async () => {
        selectedOwnerId = Number(
            ownerSelect.value
        );

        selectedOwnerName =
            ownerSelect.options[
                ownerSelect.selectedIndex
            ]?.textContent ?? "";

        updateMediaStatus();
        await loadMedia();
    },
);

initializeMediaPage();
