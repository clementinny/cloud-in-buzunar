const overallIndicator = document.querySelector("#overall-indicator");
const overallTitle = document.querySelector("#overall-title");
const overallSummary = document.querySelector("#overall-summary");
const lastUpdated = document.querySelector("#last-updated");
const refreshButton = document.querySelector("#refresh-status-button");
const statusError = document.querySelector("#status-error");
const serviceGrid = document.querySelector("#service-grid");

const refreshIntervalMilliseconds = 10_000;
let refreshTimer = null;
let refreshInProgress = false;

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

refreshButton.addEventListener("click", loadSystemStatus);

refreshTimer = window.setInterval(() => {
    if (document.visibilityState === "visible") {
        loadSystemStatus();
    }
}, refreshIntervalMilliseconds);

window.addEventListener("pagehide", () => {
    window.clearInterval(refreshTimer);
});

loadSystemStatus();
