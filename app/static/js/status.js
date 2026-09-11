const overallIndicator = document.querySelector("#overall-indicator");
const overallTitle = document.querySelector("#overall-title");
const overallSummary = document.querySelector("#overall-summary");
const lastUpdated = document.querySelector("#last-updated");
const refreshButton = document.querySelector("#refresh-status-button");
const statusError = document.querySelector("#status-error");
const serviceGrid = document.querySelector("#service-grid");
const refreshBackupsButton = document.querySelector(
    "#refresh-backups-button",
);
const backupActionStatus = document.querySelector(
    "#backup-action-status",
);
const backupList = document.querySelector("#backup-list");
const backupListEmpty = document.querySelector("#backup-list-empty");
const refreshResourcesButton = document.querySelector(
    "#refresh-resources-button",
);
const processSort = document.querySelector("#process-sort");
const resourceError = document.querySelector("#resource-error");
const resourceSummary = document.querySelector("#resource-summary");
const managedServiceList = document.querySelector(
    "#managed-service-list",
);
const processList = document.querySelector("#process-list");
const processListEmpty = document.querySelector("#process-list-empty");
const processNote = document.querySelector("#process-note");
const resourceUpdated = document.querySelector("#resource-updated");

const refreshIntervalMilliseconds = 10_000;
const resourceRefreshIntervalMilliseconds = 8_000;
let refreshTimer = null;
let resourceRefreshTimer = null;
let refreshInProgress = false;
let backupRefreshInProgress = false;
let resourceRefreshInProgress = false;
let latestProcesses = [];

const stateLabels = {
    healthy: "Funcționează",
    warning: "Atenție",
    critical: "Critic",
    offline: "Offline",
    idle: "Oprit intenționat",
    unavailable: "Indisponibil",
};

const overallTitles = {
    healthy: "Sistem funcțional",
    warning: "Atenție necesară",
    critical: "Intervenție necesară",
};

async function readJsonResponse(response) {
    let payload = {};

    try {
        payload = await response.json();
    } catch (error) {
        payload = {};
    }

    if (!response.ok) {
        throw new Error(
            payload.error ||
            `Verificarea a eșuat: HTTP ${response.status}`,
        );
    }

    return payload;
}

function createMetricList(metrics) {
    const list = document.createElement("dl");
    list.className = "service-metrics";

    for (const item of metrics) {
        const row = document.createElement("div");
        const term = document.createElement("dt");
        const value = document.createElement("dd");

        term.textContent = item.label;
        value.textContent = item.value;
        row.append(term, value);
        list.append(row);
    }

    return list;
}

function createServiceCard(service) {
    const card = document.createElement("article");
    card.className = `service-card is-${service.state}`;

    const heading = document.createElement("div");
    heading.className = "service-card-heading";

    const title = document.createElement("h2");
    title.textContent = service.name;

    const badge = document.createElement("span");
    badge.className = "service-badge";
    badge.textContent = stateLabels[service.state] || service.state;

    const summary = document.createElement("p");
    summary.className = "service-summary";
    summary.textContent = service.summary;

    heading.append(title, badge);
    card.append(heading, summary);

    if (Array.isArray(service.metrics) && service.metrics.length > 0) {
        card.append(createMetricList(service.metrics));
    }

    return card;
}

function renderStatus(payload) {
    const overall = payload.overall || "warning";

    overallIndicator.className = `status-indicator is-${overall}`;
    overallTitle.textContent =
        overallTitles[overall] || "Stare necunoscută";
    overallSummary.textContent = payload.summary || "—";

    const generatedAt = new Date(payload.generated_at);
    lastUpdated.textContent = Number.isNaN(generatedAt.getTime())
        ? "Actualizat acum"
        : `Actualizat la ${generatedAt.toLocaleTimeString("ro-RO", {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
        })}`;

    serviceGrid.replaceChildren(
        ...payload.services.map(createServiceCard),
    );
}

async function loadSystemStatus() {
    if (refreshInProgress) {
        return;
    }

    refreshInProgress = true;
    refreshButton.disabled = true;
    refreshButton.textContent = "Se verifică...";
    statusError.hidden = true;

    try {
        const response = await fetch("/api/system/status", {
            headers: {
                Accept: "application/json",
            },
            cache: "no-store",
        });
        const payload = await readJsonResponse(response);
        renderStatus(payload);
    } catch (error) {
        statusError.textContent = error.message;
        statusError.hidden = false;
    } finally {
        refreshInProgress = false;
        refreshButton.disabled = false;
        refreshButton.textContent = "Reîncarcă";
    }
}

function formatBytes(byteCount) {
    const bytes = Number(byteCount);

    if (!Number.isFinite(bytes) || bytes < 0) {
        return "Dimensiune necunoscută";
    }

    if (bytes < 1024) {
        return `${bytes} B`;
    }

    const units = ["KB", "MB", "GB", "TB"];
    let value = bytes / 1024;
    let unitIndex = 0;

    while (value >= 1024 && unitIndex < units.length - 1) {
        value /= 1024;
        unitIndex += 1;
    }

    return `${value.toFixed(value >= 10 ? 1 : 2)} ${units[unitIndex]}`;
}

function formatBackupDate(dateValue) {
    const date = new Date(dateValue);

    if (Number.isNaN(date.getTime())) {
        return "Dată necunoscută";
    }

    return date.toLocaleString("ro-RO", {
        dateStyle: "medium",
        timeStyle: "medium",
    });
}

function formatDuration(secondsValue) {
    const seconds = Math.max(0, Number(secondsValue) || 0);
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);

    if (days > 0) {
        return `${days}z ${hours}h`;
    }

    if (hours > 0) {
        return `${hours}h ${minutes}m`;
    }

    if (minutes > 0) {
        return `${minutes}m`;
    }

    return `${Math.round(seconds)}s`;
}

function formatFrequency(hertz) {
    const value = Number(hertz);

    if (!Number.isFinite(value) || value <= 0) {
        return "Frecvență indisponibilă";
    }

    return value >= 1_000_000_000
        ? `${(value / 1_000_000_000).toFixed(2)} GHz`
        : `${(value / 1_000_000).toFixed(0)} MHz`;
}

function createResourceCard(label, value, detail, state = "normal") {
    const card = document.createElement("article");
    card.className = `resource-card is-${state}`;
    const labelElement = document.createElement("span");
    const valueElement = document.createElement("strong");
    const detailElement = document.createElement("small");

    labelElement.textContent = label;
    valueElement.textContent = value;
    detailElement.textContent = detail;
    card.append(labelElement, valueElement, detailElement);

    return card;
}

function usageState(percent, warningAt = 75, criticalAt = 90) {
    if (!Number.isFinite(percent)) {
        return "unknown";
    }

    if (percent >= criticalAt) {
        return "critical";
    }

    if (percent >= warningAt) {
        return "warning";
    }

    return "normal";
}

function renderResourceSummary(payload) {
    const cpu = payload.cpu || {};
    const memory = payload.memory || {};
    const storage = payload.storage || {};
    const network = payload.network || {};
    const gpu = payload.gpu || {};
    const temperature = payload.temperature || {};
    const cpuPercent = Number(cpu.usage_percent);
    const memoryPercent = Number(memory.used_percent);
    const storagePercent = Number(storage.used_percent);
    const gpuHasUsage = (
        gpu.usage_percent !== null &&
        gpu.usage_percent !== undefined &&
        Number.isFinite(Number(gpu.usage_percent))
    );
    const gpuPercent = gpuHasUsage ? Number(gpu.usage_percent) : null;
    const temperatureCelsius = Number(temperature.celsius);
    const networkDown = Number(network.received_bytes_per_second) || 0;
    const networkUp = Number(network.sent_bytes_per_second) || 0;
    const cards = [
        createResourceCard(
            "CPU total",
            cpu.available ? `${cpuPercent.toFixed(1)}%` : "Indisponibil",
            `${cpu.logical_cores || "?"} nuclee logice`,
            usageState(cpuPercent),
        ),
        createResourceCard(
            "RAM",
            memory.available ? `${memoryPercent.toFixed(1)}%` : "Indisponibil",
            memory.available
                ? `${formatBytes(memory.used_bytes)} din ` +
                  `${formatBytes(memory.total_bytes)}`
                : "Android nu a expus memoria",
            usageState(memoryPercent),
        ),
        createResourceCard(
            "Stocare",
            storage.available
                ? `${storagePercent.toFixed(1)}%`
                : "Indisponibil",
            storage.available
                ? `${formatBytes(storage.free_bytes)} liberi`
                : "Spațiul nu poate fi citit",
            usageState(storagePercent, 85, 95),
        ),
        createResourceCard(
            "Rețea acum",
            `↓ ${formatBytes(networkDown)}/s`,
            `↑ ${formatBytes(networkUp)}/s · LAN + internet`,
        ),
        createResourceCard(
            "GPU",
            gpuHasUsage
                ? `${gpuPercent.toFixed(1)}%`
                : "Utilizare indisponibilă",
            gpu.available
                ? formatFrequency(gpu.current_frequency_hz)
                : (gpu.note || "Restricționat de Android"),
            gpuHasUsage ? usageState(gpuPercent) : "unknown",
        ),
        createResourceCard(
            "Temperatură",
            temperature.available && Number.isFinite(temperatureCelsius)
                ? `${temperatureCelsius.toFixed(1)} °C`
                : "Indisponibil",
            temperature.health || "Temperatura bateriei",
            temperatureCelsius >= 45
                ? "critical"
                : temperatureCelsius >= 40
                    ? "warning"
                    : "normal",
        ),
    ];

    resourceSummary.replaceChildren(...cards);
}

function sortedProcesses() {
    const processes = [...latestProcesses];

    if (processSort.value === "ram") {
        processes.sort((left, right) => right.rss_bytes - left.rss_bytes);
    } else if (processSort.value === "name") {
        processes.sort((left, right) => left.name.localeCompare(
            right.name,
            "ro",
        ));
    } else {
        processes.sort((left, right) => (
            right.cpu_percent - left.cpu_percent ||
            right.rss_bytes - left.rss_bytes
        ));
    }

    return processes;
}

function renderProcesses() {
    const processes = sortedProcesses();
    const rows = processes.map((process) => {
        const row = document.createElement("tr");
        const values = [
            process.name,
            String(process.pid),
            `${Number(process.cpu_percent).toFixed(1)}%`,
            `${Number(process.ram_percent).toFixed(2)}%`,
            formatBytes(process.rss_bytes),
            formatDuration(process.uptime_seconds),
        ];

        for (const value of values) {
            const cell = document.createElement("td");
            cell.textContent = value;
            row.append(cell);
        }

        return row;
    });

    processList.replaceChildren(...rows);
    processListEmpty.hidden = processes.length !== 0;
}

async function setManagedService(service, enabled) {
    if (
        !enabled &&
        !window.confirm(
            `Oprești ${service.name}? ${service.impact}`,
        )
    ) {
        return;
    }

    for (const button of managedServiceList.querySelectorAll("button")) {
        button.disabled = true;
    }
    resourceError.hidden = true;

    try {
        const response = await fetch(
            `/api/system/resources/services/${encodeURIComponent(service.id)}`,
            {
                method: "POST",
                headers: {
                    Accept: "application/json",
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({ enabled }),
            },
        );
        await readJsonResponse(response);
        await loadResources();
        loadSystemStatus();
    } catch (error) {
        resourceError.textContent = error.message;
        resourceError.hidden = false;
    } finally {
        for (const button of managedServiceList.querySelectorAll("button")) {
            button.disabled = false;
        }
    }
}

function renderManagedServices(services) {
    const rows = services.map((service) => {
        const row = document.createElement("article");
        row.className = "managed-service-row";
        const information = document.createElement("div");
        const title = document.createElement("h4");
        const detail = document.createElement("p");
        const state = document.createElement("span");
        const button = document.createElement("button");

        title.textContent = service.name;
        detail.textContent = service.impact;
        state.className = service.running ? "is-running" : "is-stopped";
        state.textContent = service.running
            ? (service.enabled ? "Pornit" : "Pornit manual")
            : (service.enabled ? "Așteaptă repornirea" : "Oprit");
        button.type = "button";
        button.textContent = service.running ? "Oprește" : "Pornește";
        button.className = service.running ? "danger-button" : "";
        button.addEventListener("click", () => {
            setManagedService(service, !service.running);
        });

        information.append(title, detail);
        row.append(information, state, button);

        return row;
    });

    managedServiceList.replaceChildren(...rows);
}

function renderResources(payload) {
    renderResourceSummary(payload);
    latestProcesses = Array.isArray(payload.processes)
        ? payload.processes
        : [];
    renderProcesses();
    renderManagedServices(
        Array.isArray(payload.managed_services)
            ? payload.managed_services
            : [],
    );
    processNote.textContent = payload.process_note || processNote.textContent;

    const generatedAt = new Date(payload.generated_at);
    resourceUpdated.textContent = Number.isNaN(generatedAt.getTime())
        ? "Actualizat acum"
        : `Măsurat la ${generatedAt.toLocaleTimeString("ro-RO", {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
        })}`;
}

async function loadResources() {
    if (resourceRefreshInProgress) {
        return;
    }

    resourceRefreshInProgress = true;
    refreshResourcesButton.disabled = true;
    refreshResourcesButton.textContent = "Se măsoară...";
    resourceError.hidden = true;

    try {
        const response = await fetch("/api/system/resources", {
            headers: { Accept: "application/json" },
            cache: "no-store",
        });
        renderResources(await readJsonResponse(response));
    } catch (error) {
        resourceError.textContent = error.message;
        resourceError.hidden = false;
    } finally {
        resourceRefreshInProgress = false;
        refreshResourcesButton.disabled = false;
        refreshResourcesButton.textContent = "Actualizează";
    }
}

function showBackupActionStatus(message, isError = false) {
    backupActionStatus.textContent = message;
    backupActionStatus.className = isError ? "is-error" : "is-success";
    backupActionStatus.hidden = false;
}

function setBackupActionsDisabled(disabled) {
    refreshBackupsButton.disabled = disabled;

    for (const button of backupList.querySelectorAll("button")) {
        button.disabled = disabled;
    }
}

async function requestBackupAction(backupName, action, confirmation = null) {
    const requestOptions = {
        method: "POST",
        headers: {
            Accept: "application/json",
        },
    };

    if (confirmation !== null) {
        requestOptions.headers["Content-Type"] = "application/json";
        requestOptions.body = JSON.stringify({ confirmation });
    }

    const encodedName = encodeURIComponent(backupName);
    const response = await fetch(
        `/api/admin/backups/${encodedName}/${action}`,
        requestOptions,
    );

    return readJsonResponse(response);
}

function createBackupRow(backup) {
    const row = document.createElement("article");
    row.className = "backup-row";

    const information = document.createElement("div");
    information.className = "backup-information";

    const name = document.createElement("h3");
    name.textContent = backup.name;

    const metadata = document.createElement("p");
    metadata.className = "backup-metadata";
    metadata.textContent = [
        formatBackupDate(backup.created_at || backup.modified_at),
        formatBytes(backup.size_bytes),
    ].join(" · ");

    const properties = document.createElement("div");
    properties.className = "backup-properties";

    const propertyLabels = [
        backup.checksum_available ? "SHA-256 disponibil" : "SHA-256 lipsește",
        backup.uploads_included === true ? "Seifuri incluse" : "Fără seifuri",
        backup.message_encryption_key_included === true
            ? "Cheia mesajelor inclusă"
            : "Fără cheia mesajelor",
    ];

    if (backup.manifest_invalid) {
        propertyLabels.push("Manifest invalid");
    }

    for (const labelText of propertyLabels) {
        const label = document.createElement("span");
        label.textContent = labelText;
        properties.append(label);
    }

    information.append(name, metadata, properties);

    const actions = document.createElement("div");
    actions.className = "backup-actions";

    const verifyButton = document.createElement("button");
    verifyButton.type = "button";
    verifyButton.textContent = "Verifică";
    verifyButton.addEventListener("click", async () => {
        setBackupActionsDisabled(true);
        showBackupActionStatus(`Se verifică ${backup.name}...`);

        try {
            const payload = await requestBackupAction(backup.name, "verify");
            const shortChecksum = payload.backup.sha256.slice(0, 12);
            showBackupActionStatus(
                `Backup valid. SHA-256 începe cu ${shortChecksum}.`,
            );
        } catch (error) {
            showBackupActionStatus(error.message, true);
        } finally {
            setBackupActionsDisabled(false);
        }
    });

    const restoreButton = document.createElement("button");
    restoreButton.type = "button";
    restoreButton.className = "danger-button";
    restoreButton.textContent = "Restaurează";
    restoreButton.addEventListener("click", async () => {
        const confirmation = window.prompt(
            "Restaurarea înlocuiește datele curente. " +
            "Scrie exact numele backupului pentru a continua:\n\n" +
            backup.name,
        );

        if (confirmation === null) {
            return;
        }

        if (confirmation !== backup.name) {
            showBackupActionStatus(
                "Numele introdus nu corespunde. Restaurarea a fost anulată.",
                true,
            );
            return;
        }

        setBackupActionsDisabled(true);
        showBackupActionStatus(
            "Se verifică arhiva și se creează backupul de siguranță...",
        );

        try {
            const payload = await requestBackupAction(
                backup.name,
                "restore",
                confirmation,
            );
            showBackupActionStatus(
                `Restaurare reușită. Backup de siguranță: ` +
                `${payload.safety_backup}. Serverul se reîncarcă...`,
            );
            window.setTimeout(() => window.location.reload(), 3500);
        } catch (error) {
            showBackupActionStatus(error.message, true);
            setBackupActionsDisabled(false);
        }
    });

    actions.append(verifyButton, restoreButton);
    row.append(information, actions);

    return row;
}

async function loadBackups() {
    if (backupRefreshInProgress) {
        return;
    }

    backupRefreshInProgress = true;
    refreshBackupsButton.disabled = true;
    refreshBackupsButton.textContent = "Se încarcă...";

    try {
        const response = await fetch("/api/admin/backups", {
            headers: {
                Accept: "application/json",
            },
            cache: "no-store",
        });
        const payload = await readJsonResponse(response);
        const backups = Array.isArray(payload.backups) ? payload.backups : [];

        backupList.replaceChildren(...backups.map(createBackupRow));
        backupListEmpty.hidden = backups.length !== 0;
    } catch (error) {
        backupList.replaceChildren();
        backupListEmpty.hidden = true;
        showBackupActionStatus(error.message, true);
    } finally {
        backupRefreshInProgress = false;
        refreshBackupsButton.disabled = false;
        refreshBackupsButton.textContent = "Reîncarcă lista";
    }
}

refreshButton.addEventListener("click", loadSystemStatus);
refreshBackupsButton.addEventListener("click", loadBackups);
refreshResourcesButton.addEventListener("click", loadResources);
processSort.addEventListener("change", renderProcesses);

refreshTimer = window.setInterval(() => {
    if (document.visibilityState === "visible") {
        loadSystemStatus();
    }
}, refreshIntervalMilliseconds);

resourceRefreshTimer = window.setInterval(() => {
    if (document.visibilityState === "visible") {
        loadResources();
    }
}, resourceRefreshIntervalMilliseconds);

window.addEventListener("pagehide", () => {
    window.clearInterval(refreshTimer);
    window.clearInterval(resourceRefreshTimer);
});

loadSystemStatus();
loadBackups();
loadResources();
