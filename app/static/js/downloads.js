const torrentFileInput =
    document.querySelector(
        "#torrent-file-input"
    );
const startTorrentButton =
    document.querySelector(
        "#start-torrent-button"
    );

const serviceStatus =
    document.querySelector(
        "#downloads-service-status"
    );
const refreshButton =
    document.querySelector(
        "#refresh-downloads-button"
    );
const transmissionServiceButton =
    document.querySelector(
        "#transmission-service-button"
    );
const transmissionServiceMessage =
    document.querySelector(
        "#transmission-service-message"
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
let transmissionIsOnline = false;
let transmissionActionIsRunning = false;


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
        "seed-paused": "Seed oprit",
        checking: "Se verifică",
        seeding: "Se oferă la seed",
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
    download,
    action,
    method = "POST",
) {
    const suffix = action ? `/${action}` : "";
    const encodedId = encodeURIComponent(download.gid);
    const enginePrefix =
        download.engine === "transmission"
            ? "/transmission"
            : "";

    const response = await fetch(
        `/api/downloads${enginePrefix}/${encodedId}${suffix}`,
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

        const engineLabel =
            download.engine === "transmission"
                ? "Transmission"
                : "aria2";

        details.textContent =
            `${formatBytes(
                download.completed_bytes
            )} din ${totalLabel} · ${engineLabel}`;

        progress.max = 100;
        progress.value = download.progress;

        const percentage =
            document.createElement("span");
        const speed = document.createElement("span");

        percentage.textContent =
            `${download.progress.toFixed(1)}%`;
        const displayedSpeed =
            download.status === "seeding"
                ? download.upload_speed
                : download.download_speed;

        speed.textContent =
            download.status === "seeding"
                ? `↑ ${formatSpeed(displayedSpeed)}`
                : formatSpeed(displayedSpeed);

        progressLabel.append(percentage, speed);

        if (
            download.status === "active"
            || download.status === "waiting"
            || download.status === "checking"
        ) {
            actions.append(
                createActionButton(
                    "Pauză",
                    "secondary-button",
                    () => runDownloadAction(
                        download,
                        "pause",
                    ),
                ),
            );
        }

        if (download.status === "seeding") {
            actions.append(
                createActionButton(
                    "Oprește seed-ul",
                    "secondary-button",
                    () => runDownloadAction(
                        download,
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
                        download,
                        "resume",
                    ),
                ),
            );
        }

        if (download.status === "seed-paused") {
            actions.append(
                createActionButton(
                    "Pornește seed-ul",
                    "secondary-button",
                    () => runDownloadAction(
                        download,
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
                    download,
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

        transmissionIsOnline = Boolean(
            data.transmission?.online
        );
        transmissionServiceButton.disabled =
            transmissionActionIsRunning;
        transmissionServiceButton.textContent =
            transmissionIsOnline
                ? "Oprește Transmission"
                : "Pornește Transmission";
        startTorrentButton.disabled =
            !transmissionIsOnline;

        if (transmissionIsOnline) {
            transmissionServiceMessage.textContent =
                "Transmission rulează. Poți opri separat "
                + "seed-ul fiecărui torrent.";
        } else if (data.transmission?.enabled) {
            transmissionServiceMessage.textContent =
                "Transmission este configurat să ruleze, "
                + "dar momentan nu răspunde.";
        } else {
            transmissionServiceMessage.textContent =
                "Transmission este oprit intenționat și "
                + "watchdog-ul nu îl va reporni.";
        }

        const serviceLabels = {
            connected: "conectat",
            unavailable: "indisponibil",
            stopped: "oprit intenționat",
        };
        const serviceSummary = Object.entries(
            data.services ?? {}
        ).map(
            ([name, status]) =>
                `${name}: ${serviceLabels[status] ?? status}`,
        );

        serviceStatus.textContent =
            `${serviceSummary.join(" · ")} · actualizare automată`;
        refreshButton.disabled = false;

        renderDownloads(data.downloads);
    } catch (error) {
        serviceStatus.textContent =
            "Serviciile de download nu sunt disponibile";

        downloadsMessage.textContent =
            error.message;
        downloadsMessage.classList.add(
            "is-error"
        );
        downloadsMessage.hidden = false;
        transmissionServiceButton.disabled = false;
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


transmissionServiceButton.addEventListener(
    "click",
    async () => {
        transmissionActionIsRunning = true;
        transmissionServiceButton.disabled = true;
        startTorrentButton.disabled = true;
        transmissionServiceMessage.classList.remove(
            "is-error"
        );

        try {
            const response = await fetch(
                "/api/downloads/transmission/service",
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify({
                        enabled: !transmissionIsOnline,
                    }),
                },
            );
            const data = await readJsonResponse(response);

            transmissionServiceMessage.textContent =
                data.message;
            transmissionActionIsRunning = false;
            await loadDownloads();
        } catch (error) {
            transmissionActionIsRunning = false;
            transmissionServiceMessage.textContent =
                error.message;
            transmissionServiceMessage.classList.add(
                "is-error"
            );
            transmissionServiceButton.disabled = false;
        }
    },
);


document.addEventListener(
    "visibilitychange",
    () => {
        if (!document.hidden) {
            loadDownloads();
        }
    },
);

startTorrentButton.addEventListener(
    "click",
    async () => {
        const torrentFile =
            torrentFileInput.files[0];

        if (!torrentFile) {
            newDownloadMessage.textContent =
                "Selectează un fișier .torrent.";
            newDownloadMessage.classList.add(
                "is-error"
            );
            newDownloadMessage.hidden = false;
            return;
        }

        if (
            !torrentFile.name
                .toLowerCase()
                .endsWith(".torrent")
        ) {
            newDownloadMessage.textContent =
                "Fișierul trebuie să aibă extensia .torrent.";
            newDownloadMessage.classList.add(
                "is-error"
            );
            newDownloadMessage.hidden = false;
            return;
        }

        startTorrentButton.disabled = true;
        newDownloadMessage.hidden = true;

        const formData = new FormData();

        formData.append("file", torrentFile);
        formData.append(
            "owner_id",
            ownerSelect.value,
        );
        formData.append(
            "destination",
            destinationSelect.value,
        );

        try {
            const response = await fetch(
                "/api/downloads/torrent",
                {
                    method: "POST",
                    body: formData,
                },
            );

            const data =
                await readJsonResponse(response);

            torrentFileInput.value = "";

            newDownloadMessage.textContent =
                `Torrent pornit: ${data.torrent}`;
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
            startTorrentButton.disabled =
                !transmissionIsOnline;
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
