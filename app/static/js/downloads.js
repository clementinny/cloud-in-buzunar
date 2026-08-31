const serviceStatus =
    document.querySelector(
        "#downloads-service-status"
    );
const refreshButton =
    document.querySelector(
        "#refresh-downloads-button"
    );
const downloadForm =
    document.querySelector("#new-download-form");
const urlInput =
    document.querySelector("#download-url-input");
const ownerSelect =
    document.querySelector(
        "#download-owner-select"
    );
const destinationSelect =
    document.querySelector(
        "#download-destination-select"
    );
const startButton =
    document.querySelector(
        "#start-download-button"
    );
const newDownloadMessage =
    document.querySelector(
        "#new-download-message"
    );
const downloadsCount =
    document.querySelector("#downloads-count");
const totalSpeed =
    document.querySelector(
        "#downloads-total-speed"
    );
const downloadsMessage =
    document.querySelector("#downloads-message");
const downloadsList =
    document.querySelector("#downloads-list");

let refreshTimer = null;
let refreshIsRunning = false;


function formatBytes(bytes) {
    if (!bytes) {
        return "0 B";
    }

    const units = ["B", "KB", "MB", "GB", "TB"];
    const unitIndex = Math.min(
        Math.floor(Math.log(bytes) / Math.log(1024)),
        units.length - 1,
    );

    const value = bytes / (1024 ** unitIndex);

    return `${value.toFixed(1)} ${units[unitIndex]}`;
}


function formatSpeed(bytesPerSecond) {
    return `${formatBytes(bytesPerSecond)}/s`;
}


function getStatusLabel(status) {
    const labels = {
        active: "Se descarcă",
        waiting: "În așteptare",
        paused: "Pauză",
        complete: "Finalizat",
        error: "Eroare",
        removed: "Eliminat",
    };

    return labels[status] ?? status;
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


async function loadOwners() {
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
}


async function runDownloadAction(
    gid,
    action,
    method = "POST",
) {
    const suffix = action ? `/${action}` : "";

    const response = await fetch(
        `/api/downloads/${gid}${suffix}`,
        {
            method,
        },
    );

    await readJsonResponse(response);
    await loadDownloads();
}


function createActionButton(
    label,
    className,
    handler,
) {
    const button = document.createElement("button");

    button.type = "button";
    button.textContent = label;
    button.className = className;

    button.addEventListener(
        "click",
        async () => {
            button.disabled = true;

            try {
                await handler();
            } catch (error) {
                downloadsMessage.textContent =
                    error.message;
                downloadsMessage.classList.add(
                    "is-error"
                );
                downloadsMessage.hidden = false;
                button.disabled = false;
            }
        },
    );

    return button;
}


function renderDownloads(downloads) {
    downloadsList.replaceChildren();

    downloadsCount.textContent =
        `${downloads.length} ${
            downloads.length === 1
                ? "descărcare"
                : "descărcări"
        }`;

    const activeSpeed = downloads.reduce(
        (total, download) =>
            total + download.download_speed,
        0,
    );

    totalSpeed.textContent = formatSpeed(activeSpeed);

    if (downloads.length === 0) {
        downloadsMessage.textContent =
            "Nu există descărcări.";
        downloadsMessage.classList.remove(
            "is-error"
        );
        downloadsMessage.hidden = false;
        return;
    }

    downloadsMessage.hidden = true;

    for (const download of downloads) {
        const card = document.createElement("article");
        const header = document.createElement("div");
        const information = document.createElement("div");
        const name = document.createElement("h3");
        const status = document.createElement("span");
        const details = document.createElement("p");
        const progress = document.createElement(
            "progress"
        );
        const progressLabel =
            document.createElement("div");
        const actions = document.createElement("div");

        card.className = "download-card";
        header.className = "download-card-header";
        information.className =
            "download-information";
        status.className =
            `download-status status-${download.status}`;
        progressLabel.className =
            "download-progress-label";
        actions.className = "download-card-actions";

        name.textContent = download.name;
        status.textContent = getStatusLabel(
            download.status
        );

        const totalLabel =
            download.total_bytes > 0
                ? formatBytes(download.total_bytes)
                : "dimensiune necunoscută";

        details.textContent =
            `${formatBytes(
                download.completed_bytes
            )} din ${totalLabel}`;

        progress.max = 100;
        progress.value = download.progress;

        const percentage =
            document.createElement("span");
        const speed = document.createElement("span");

        percentage.textContent =
            `${download.progress.toFixed(1)}%`;
        speed.textContent = formatSpeed(
            download.download_speed
        );

        progressLabel.append(percentage, speed);

        if (
            download.status === "active"
            || download.status === "waiting"
        ) {
            actions.append(
                createActionButton(
                    "Pauză",
                    "secondary-button",
                    () => runDownloadAction(
                        download.gid,
                        "pause",
                    ),
                ),
            );
        }

        if (download.status === "paused") {
            actions.append(
                createActionButton(
                    "Continuă",
                    "secondary-button",
                    () => runDownloadAction(
                        download.gid,
                        "resume",
                    ),
                ),
            );
        }

        actions.append(
            createActionButton(
                "Elimină",
                "delete-button",
                () => runDownloadAction(
                    download.gid,
                    "",
                    "DELETE",
                ),
            ),
        );

        if (download.error_message) {
            const errorMessage =
                document.createElement("p");

            errorMessage.className =
                "download-error";
            errorMessage.textContent =
                download.error_message;

            information.append(
                name,
                details,
                errorMessage,
            );
        } else {
            information.append(name, details);
        }

        header.append(information, status);

        card.append(
            header,
            progress,
            progressLabel,
            actions,
        );

        downloadsList.append(card);
    }
}


async function loadDownloads() {
    if (refreshIsRunning) {
        return;
    }

    refreshIsRunning = true;

    try {
        const response = await fetch(
            "/api/downloads"
        );
        const data = await readJsonResponse(response);

        serviceStatus.textContent =
            "aria2 conectat · actualizare automată";
        refreshButton.disabled = false;

        renderDownloads(data.downloads);
    } catch (error) {
        serviceStatus.textContent =
            "Serviciul aria2 nu este disponibil";

        downloadsMessage.textContent =
            error.message;
        downloadsMessage.classList.add(
            "is-error"
        );
        downloadsMessage.hidden = false;
    } finally {
        refreshIsRunning = false;
    }
}


downloadForm.addEventListener(
    "submit",
    async (event) => {
        event.preventDefault();

        startButton.disabled = true;
        newDownloadMessage.hidden = true;

        try {
            const response = await fetch(
                "/api/downloads",
                {
                    method: "POST",
                    headers: {
                        "Content-Type":
                            "application/json",
                    },
                    body: JSON.stringify({
                        url: urlInput.value.trim(),
                        owner_id: Number(
                            ownerSelect.value
                        ),
                        destination:
                            destinationSelect.value,
                    }),
                },
            );

            const data =
                await readJsonResponse(response);

            urlInput.value = "";

            newDownloadMessage.textContent =
                `Download adăugat: ${data.gid}`;
            newDownloadMessage.classList.remove(
                "is-error"
            );
            newDownloadMessage.hidden = false;

            await loadDownloads();
        } catch (error) {
            newDownloadMessage.textContent =
                error.message;
            newDownloadMessage.classList.add(
                "is-error"
            );
            newDownloadMessage.hidden = false;
        } finally {
            startButton.disabled = false;
        }
    },
);


refreshButton.addEventListener(
    "click",
    loadDownloads,
);


document.addEventListener(
    "visibilitychange",
    () => {
        if (!document.hidden) {
            loadDownloads();
        }
    },
);


async function initializeDownloadsPage() {
    try {
        const response = await fetch("/api/auth/me");
        const data = await readJsonResponse(response);

        if (data.user.role !== "admin") {
            throw new Error(
                "Pagina este disponibilă numai administratorului."
            );
        }

        await loadOwners();

        downloadForm.hidden = false;
        refreshButton.disabled = false;

        await loadDownloads();

        refreshTimer = window.setInterval(
            loadDownloads,
            2500,
        );
    } catch (error) {
        serviceStatus.textContent = "Acces indisponibil";
        downloadsMessage.textContent = error.message;
        downloadsMessage.classList.add("is-error");
        downloadsMessage.hidden = false;
    }
}


window.addEventListener("beforeunload", () => {
    if (refreshTimer !== null) {
        window.clearInterval(refreshTimer);
    }
});


initializeDownloadsPage();
