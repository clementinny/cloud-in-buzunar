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
const androidProcessList = document.querySelector("#android-process-list");
const androidProcessListEmpty = document.querySelector(
    "#android-process-list-empty",
);
const androidProcessNote = document.querySelector("#android-process-note");
const resourceUpdated = document.querySelector("#resource-updated");
const powerError = document.querySelector("#power-error");
const batteryMetrics = document.querySelector("#battery-metrics");
const guardianState = document.querySelector(".guardian-state");
const guardianTitle = document.querySelector("#guardian-title");
const guardianDetail = document.querySelector("#guardian-detail");
const thermalSensors = document.querySelector("#thermal-sensors");
const thermalPolicyForm = document.querySelector("#thermal-policy-form");
const thermalEnabled = document.querySelector("#thermal-enabled");
const warningTemperature = document.querySelector("#warning-temperature");
const criticalTemperature = document.querySelector("#critical-temperature");
const recoveryTemperature = document.querySelector("#recovery-temperature");
const thermalStopAi = document.querySelector("#thermal-stop-ai");
const thermalStopTransmission = document.querySelector(
    "#thermal-stop-transmission",
);
const thermalStopAria2 = document.querySelector("#thermal-stop-aria2");
const chargeLimitSelect = document.querySelector("#charge-limit-select");
const applyChargeLimitButton = document.querySelector("#apply-charge-limit");
const chargeLimitNote = document.querySelector("#charge-limit-note");
const historyHours = document.querySelector("#history-hours");
const usageHistoryChart = document.querySelector("#usage-history-chart");
const temperatureHistoryChart = document.querySelector(
    "#temperature-history-chart",
);
const historyEmpty = document.querySelector("#history-empty");

const refreshIntervalMilliseconds = 10_000;
const resourceRefreshIntervalMilliseconds = 8_000;
const powerRefreshIntervalMilliseconds = 60_000;
let refreshTimer = null;
let resourceRefreshTimer = null;
let powerRefreshTimer = null;
let refreshInProgress = false;
let backupRefreshInProgress = false;
let resourceRefreshInProgress = false;
let powerRefreshInProgress = false;
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

function formatGpuDetail(gpu) {
    const current = formatFrequency(gpu.current_frequency_hz);
    const maximum = formatFrequency(gpu.maximum_frequency_hz);
    const hasCurrent = current !== "Frecvență indisponibilă";
    const hasMaximum = maximum !== "Frecvență indisponibilă";

    if (hasCurrent && hasMaximum) {
        return `${current} / max ${maximum}${gpu.source === "root" ? " · root" : ""}`;
    }

    if (hasCurrent) {
        return `${current}${gpu.source === "root" ? " · root" : ""}`;
    }

    return gpu.note || "Frecvență indisponibilă";
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

function createBatteryMetric(label, value, detail = "") {
    const card = document.createElement("article");
    card.className = "battery-metric";
    const labelElement = document.createElement("span");
    const valueElement = document.createElement("strong");
    const detailElement = document.createElement("small");
    labelElement.textContent = label;
    valueElement.textContent = value;
    detailElement.textContent = detail;
    card.append(labelElement, valueElement, detailElement);
    return card;
}

function optionalNumber(value, digits = 1, suffix = "") {
    const number = Number(value);
    return value !== null && value !== undefined && Number.isFinite(number)
        ? `${number.toFixed(digits)}${suffix}`
        : "Indisponibil";
}

function renderPower(payload) {
    const battery = payload.battery || {};
    const thermal = payload.thermal || {};
    const guardian = payload.guardian || {};
    const policy = payload.policy || {};
    const capacityDetail = (
        battery.full_capacity_ah !== null &&
        battery.full_capacity_ah !== undefined
    )
        ? `${optionalNumber(battery.full_capacity_ah, 2, " Ah")} actual`
        : "Capacitate neraportată";
    const metrics = [
        createBatteryMetric(
            "Încărcare",
            optionalNumber(battery.percentage, 0, "%"),
            battery.status || "Stare necunoscută",
        ),
        createBatteryMetric(
            "Temperatură baterie",
            optionalNumber(battery.temperature_c, 1, " °C"),
            battery.health || "Sănătate necunoscută",
        ),
        createBatteryMetric(
            "Putere baterie",
            optionalNumber(battery.power_w, 2, " W"),
            `${optionalNumber(battery.voltage_v, 3, " V")} · ` +
            `${optionalNumber(battery.current_a, 3, " A")}`,
        ),
        createBatteryMetric(
            "Sănătate estimată",
            optionalNumber(battery.health_percent, 1, "%"),
            capacityDetail,
        ),
        createBatteryMetric(
            "Cicluri",
            optionalNumber(battery.cycle_count, 0),
            battery.technology || "Neraportat",
        ),
        createBatteryMetric(
            "CPU termic",
            optionalNumber(thermal.cpu_temperature_c, 1, " °C"),
            thermal.severity_label || "Nivel indisponibil",
        ),
        createBatteryMetric(
            "GPU termic",
            optionalNumber(thermal.gpu_temperature_c, 1, " °C"),
            "Senzor driver",
        ),
        createBatteryMetric(
            "Carcasă",
            optionalNumber(thermal.skin_temperature_c, 1, " °C"),
            "Senzor skin",
        ),
    ];
    batteryMetrics.replaceChildren(...metrics);

    const level = guardian.level || "unknown";
    guardianState.className = `guardian-state is-${level}`;
    guardianTitle.textContent = {
        normal: "Protecție activă · normal",
        warning: "Protecție activă · avertizare",
        critical: "Protecție activă · critic",
        recovering: "Telefonul se răcește",
        disabled: "Protecție dezactivată",
        unknown: "Date termice indisponibile",
    }[level] || "Guardian în așteptare";
    const guardianDetails = [
        guardian.message || "Nu există încă o citire.",
    ];
    const suspendedServices = Array.isArray(guardian.suspended_services)
        ? guardian.suspended_services
        : [];

    if (suspendedServices.length > 0) {
        guardianDetails.push(
            `Suspendate: ${suspendedServices.join(", ")}.`,
        );
    }

    if (guardian.last_error) {
        guardianDetails.push(`Eroare: ${guardian.last_error}`);
    }

    guardianDetail.textContent = guardianDetails.join(" ");

    thermalEnabled.checked = Boolean(policy.enabled);
    warningTemperature.value = policy.warning_temperature_c ?? 40;
    criticalTemperature.value = policy.critical_temperature_c ?? 43;
    recoveryTemperature.value = policy.recovery_temperature_c ?? 37.5;
    thermalStopAi.checked = Boolean(policy.stop_ai);
    thermalStopTransmission.checked = Boolean(policy.stop_transmission);
    thermalStopAria2.checked = Boolean(policy.stop_aria2_on_critical);

    const sensors = Array.isArray(thermal.sensors) ? thermal.sensors : [];
    thermalSensors.replaceChildren(...sensors.map((sensor) => {
        const item = document.createElement("span");
        item.textContent = `${sensor.name}: ${sensor.temperature_c.toFixed(1)} °C`;
        return item;
    }));

    if (sensors.length === 0) {
        const item = document.createElement("span");
        item.textContent = "Android nu a expus senzori termici.";
        thermalSensors.append(item);
    }

    const chargeControl = battery.charge_control || {};
    chargeLimitSelect.disabled = !chargeControl.supported;
    applyChargeLimitButton.disabled = !chargeControl.supported;
    const currentLimit = Number(chargeControl.current_limit_percent);
    const allowedLimits = Array.isArray(chargeControl.allowed_limits)
        ? chargeControl.allowed_limits.map(Number)
        : [];
    chargeLimitNote.textContent = [
        chargeControl.note || "Suport indisponibil.",
        Number.isFinite(currentLimit)
            ? `Limita curentă: ${currentLimit}%.`
            : "",
    ].filter(Boolean).join(" ");

    if (allowedLimits.includes(currentLimit)) {
        chargeLimitSelect.value = String(chargeControl.current_limit_percent);
    } else if (policy.charge_limit_percent) {
        chargeLimitSelect.value = String(policy.charge_limit_percent);
    } else {
        chargeLimitSelect.value = "85";
    }
}

function svgElement(name, attributes = {}) {
    const element = document.createElementNS("http://www.w3.org/2000/svg", name);

    for (const [attribute, value] of Object.entries(attributes)) {
        element.setAttribute(attribute, String(value));
    }

    return element;
}

function drawHistoryChart(svg, metrics, series, minimum, maximum, suffix) {
    svg.replaceChildren();
    const left = 68;
    const right = 980;
    const top = 18;
    const bottom = 198;
    const timestamps = metrics.map((metric) => Date.parse(metric.recorded_at));
    const firstTime = Math.min(...timestamps);
    const lastTime = Math.max(...timestamps);
    const timeRange = Math.max(1, lastTime - firstTime);

    for (let index = 0; index <= 4; index += 1) {
        const y = top + (bottom - top) * index / 4;
        const value = maximum - (maximum - minimum) * index / 4;
        svg.append(svgElement("line", {
            x1: left,
            x2: right,
            y1: y,
            y2: y,
            class: "chart-grid-line",
        }));
        const label = svgElement("text", {
            x: 4,
            y: y + 7,
            class: "chart-axis-label",
        });
        label.textContent = `${Math.round(value)}${suffix}`;
        svg.append(label);
    }

    for (const item of series) {
        const points = metrics.flatMap((metric, index) => {
            const value = Number(metric[item.key]);

            if (metric[item.key] === null || !Number.isFinite(value)) {
                return [];
            }

            const x = left + (timestamps[index] - firstTime) / timeRange * (right - left);
            const clamped = Math.min(maximum, Math.max(minimum, value));
            const y = bottom - (clamped - minimum) / (maximum - minimum) * (bottom - top);
            return [`${x.toFixed(1)},${y.toFixed(1)}`];
        });

        if (points.length > 0) {
            svg.append(svgElement("polyline", {
                points: points.join(" "),
                class: "chart-line",
                stroke: item.color,
            }));
        }
    }

    const startLabel = svgElement("text", { x: left, y: 232, class: "chart-axis-label" });
    const endLabel = svgElement("text", { x: right, y: 232, class: "chart-axis-label", "text-anchor": "end" });
    startLabel.textContent = new Date(firstTime).toLocaleString("ro-RO", { hour: "2-digit", minute: "2-digit" });
    endLabel.textContent = new Date(lastTime).toLocaleString("ro-RO", { hour: "2-digit", minute: "2-digit" });
    svg.append(startLabel, endLabel);
}

function renderHistory(metrics) {
    historyEmpty.hidden = metrics.length !== 0;

    if (metrics.length === 0) {
        usageHistoryChart.replaceChildren();
        temperatureHistoryChart.replaceChildren();
        return;
    }

    drawHistoryChart(
        usageHistoryChart,
        metrics,
        [
            { key: "cpu_usage_percent", color: "#22d3ee" },
            { key: "gpu_usage_percent", color: "#a78bfa" },
        ],
        0,
        100,
        "%",
    );

    const temperatures = metrics.flatMap((metric) => [
        metric.battery_temperature_c,
        metric.cpu_temperature_c,
        metric.gpu_temperature_c,
    ]).map(Number).filter(Number.isFinite);
    const maximum = Math.max(50, Math.ceil(Math.max(...temperatures, 50) / 10) * 10);
    drawHistoryChart(
        temperatureHistoryChart,
        metrics,
        [
            { key: "battery_temperature_c", color: "#fbbf24" },
            { key: "cpu_temperature_c", color: "#fb7185" },
            { key: "gpu_temperature_c", color: "#c084fc" },
        ],
        20,
        maximum,
        "°",
    );
}

async function loadPowerCenter() {
    if (powerRefreshInProgress) {
        return;
    }

    powerRefreshInProgress = true;
    powerError.hidden = true;

    try {
        const [powerResponse, historyResponse] = await Promise.all([
            fetch("/api/system/power", { headers: { Accept: "application/json" }, cache: "no-store" }),
            fetch(`/api/system/history?hours=${encodeURIComponent(historyHours.value)}`, { headers: { Accept: "application/json" }, cache: "no-store" }),
        ]);
        const power = await readJsonResponse(powerResponse);
        const history = await readJsonResponse(historyResponse);
        renderPower(power);
        renderHistory(Array.isArray(history.metrics) ? history.metrics : []);
    } catch (error) {
        powerError.textContent = error.message;
        powerError.hidden = false;
    } finally {
        powerRefreshInProgress = false;
    }
}

async function saveThermalPolicy(event) {
    event.preventDefault();
    const button = thermalPolicyForm.querySelector("button[type='submit']");
    button.disabled = true;
    powerError.hidden = true;

    try {
        const response = await fetch("/api/system/power/policy", {
            method: "POST",
            headers: { Accept: "application/json", "Content-Type": "application/json" },
            body: JSON.stringify({
                enabled: thermalEnabled.checked,
                warning_temperature_c: Number(warningTemperature.value),
                critical_temperature_c: Number(criticalTemperature.value),
                recovery_temperature_c: Number(recoveryTemperature.value),
                stop_ai: thermalStopAi.checked,
                stop_transmission: thermalStopTransmission.checked,
                stop_aria2_on_critical: thermalStopAria2.checked,
            }),
        });
        await readJsonResponse(response);
        await loadPowerCenter();
    } catch (error) {
        powerError.textContent = error.message;
        powerError.hidden = false;
    } finally {
        button.disabled = false;
    }
}

async function applyChargeLimit() {
    const limit = Number(chargeLimitSelect.value);

    if (!window.confirm(`Setezi limita de încărcare la ${limit}%?`)) {
        return;
    }

    applyChargeLimitButton.disabled = true;
    powerError.hidden = true;

    try {
        const response = await fetch("/api/system/power/charge-limit", {
            method: "POST",
            headers: { Accept: "application/json", "Content-Type": "application/json" },
            body: JSON.stringify({ limit_percent: limit }),
        });
        await readJsonResponse(response);
        await loadPowerCenter();
    } catch (error) {
        powerError.textContent = error.message;
        powerError.hidden = false;
    } finally {
        applyChargeLimitButton.disabled = chargeLimitSelect.disabled;
    }
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
    const cpuIsEstimate = cpu.source === "termux_estimate";
    const cards = [
        createResourceCard(
            cpuIsEstimate ? "CPU Termux estimat" : "CPU total",
            cpu.available ? `${cpuPercent.toFixed(1)}%` : "Indisponibil",
            cpu.available
                ? `${cpu.logical_cores || "?"} nuclee · ${cpu.note || ""}`
                : (cpu.note || "Android nu a expus utilizarea"),
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
                ? formatGpuDetail(gpu)
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

function renderAndroidProcesses(androidCpu) {
    const processes = Array.isArray(androidCpu.processes)
        ? androidCpu.processes
        : [];
    const rows = processes.map((process) => {
        const row = document.createElement("tr");
        const values = [
            process.name,
            String(process.pid),
            `${Number(process.cpu_percent).toFixed(1)}%`,
        ];

        for (const value of values) {
            const cell = document.createElement("td");
            cell.textContent = value;
            row.append(cell);
        }

        return row;
    });

    androidProcessList.replaceChildren(...rows);
    androidProcessListEmpty.hidden = processes.length !== 0;
    androidProcessNote.textContent = androidCpu.note || (
        androidCpu.available
            ? "Procese raportate de Android prin root."
            : "Lista completă nu este disponibilă."
    );
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
    renderAndroidProcesses(payload.android_cpu || {});
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
thermalPolicyForm.addEventListener("submit", saveThermalPolicy);
applyChargeLimitButton.addEventListener("click", applyChargeLimit);
historyHours.addEventListener("change", loadPowerCenter);

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

powerRefreshTimer = window.setInterval(() => {
    if (document.visibilityState === "visible") {
        loadPowerCenter();
    }
}, powerRefreshIntervalMilliseconds);

window.addEventListener("pagehide", () => {
    window.clearInterval(refreshTimer);
    window.clearInterval(resourceRefreshTimer);
    window.clearInterval(powerRefreshTimer);
});

loadSystemStatus();
loadBackups();
loadResources();
loadPowerCenter();
