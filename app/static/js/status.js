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

const refreshIntervalMilliseconds = 10_000;
let refreshTimer = null;
let refreshInProgress = false;
let backupRefreshInProgress = false;

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

refreshTimer = window.setInterval(() => {
    if (document.visibilityState === "visible") {
        loadSystemStatus();
    }
}, refreshIntervalMilliseconds);

window.addEventListener("pagehide", () => {
    window.clearInterval(refreshTimer);
});

loadSystemStatus();
loadBackups();
