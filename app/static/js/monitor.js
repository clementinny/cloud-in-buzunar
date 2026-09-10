const monitorStatus = document.querySelector("#monitor-status");
const connectionStatus = document.querySelector(
    "#monitor-connection-status",
);
const refreshButton = document.querySelector(
    "#refresh-monitor-button",
);
const startRemoteButton = document.querySelector(
    "#start-remote-button",
);
const connectButton = document.querySelector(
    "#connect-monitor-button",
);
const stopSourceButton = document.querySelector(
    "#stop-source-button",
);
const remoteVideo = document.querySelector("#remote-video");
const placeholder = document.querySelector(
    "#monitor-placeholder",
);
const liveBadge = document.querySelector(
    "#monitor-live-badge",
);
const monitorError = document.querySelector("#monitor-error");
const createPairingCodeButton = document.querySelector(
    "#create-pairing-code-button",
);
const pairingCode = document.querySelector("#pairing-code");
const pairingCodeStatus = document.querySelector(
    "#pairing-code-status",
);
const cameraFacingSelect = document.querySelector(
    "#monitor-camera-facing",
);

let availableSession = null;
let sourceIsArmed = false;
let peerConnection = null;
let connectedSessionId = null;
let refreshTimer = null;
let viewerHeartbeatTimer = null;
let connectWhenReady = false;
let cameraSelectionInitialized = false;


async function readJsonResponse(response) {
    let data = null;

    try {
        data = await response.json();
    } catch (error) {
        data = null;
    }

    if (!response.ok) {
        throw new Error(
            data?.error
            ?? `Cererea a eșuat: HTTP ${response.status}`,
        );
    }

    return data;
}


function showError(message) {
    monitorError.textContent = message;
    monitorError.hidden = false;
}


function clearError() {
    monitorError.textContent = "";
    monitorError.hidden = true;
}


function waitForIceGatheringComplete(connection) {
    if (connection.iceGatheringState === "complete") {
        return Promise.resolve();
    }

    return new Promise((resolve) => {
        const timeoutId = window.setTimeout(() => {
            connection.removeEventListener(
                "icegatheringstatechange",
                handleStateChange,
            );
            resolve();
        }, 8000);

        function handleStateChange() {
            if (connection.iceGatheringState !== "complete") {
                return;
            }

            window.clearTimeout(timeoutId);
            connection.removeEventListener(
                "icegatheringstatechange",
                handleStateChange,
            );
            resolve();
        }

        connection.addEventListener(
            "icegatheringstatechange",
            handleStateChange,
        );
    });
}


function closeViewerConnection(message = null) {
    if (viewerHeartbeatTimer) {
        window.clearInterval(viewerHeartbeatTimer);
        viewerHeartbeatTimer = null;
    }

    if (peerConnection) {
        peerConnection.close();
        peerConnection = null;
    }

    connectedSessionId = null;
    remoteVideo.srcObject = null;
    remoteVideo.hidden = true;
    placeholder.hidden = false;
    liveBadge.hidden = true;

    if (message) {
        connectionStatus.textContent = message;
    }

    connectButton.disabled = !availableSession;
}


async function sendViewerHeartbeat() {
    if (!connectedSessionId) {
        return;
    }

    const response = await fetch(
        "/api/monitor/viewer/heartbeat",
        {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                session_id: connectedSessionId,
            }),
        },
    );
    const data = await readJsonResponse(response);

    if (!data.active) {
        closeViewerConnection(
            "Sesiunea de vizualizare s-a încheiat.",
        );
    }
}


function updateConnectionState() {
    if (!peerConnection) {
        return;
    }

    const state = peerConnection.connectionState;

    if (state === "connected") {
        connectionStatus.textContent =
            "Conectat direct la camera telefonului.";
        liveBadge.hidden = false;
        return;
    }

    if (state === "connecting") {
        connectionStatus.textContent = "Se stabilește conexiunea...";
        return;
    }

    if (["failed", "disconnected", "closed"].includes(state)) {
        closeViewerConnection(
            "Conexiunea cu sursa s-a încheiat.",
        );
    }
}


async function connectToSource() {
    if (!availableSession || peerConnection) {
        return;
    }

    clearError();
    connectButton.disabled = true;
    connectionStatus.textContent = "Se pregătește conexiunea...";

    const requestedSession = availableSession;
    const connection = new RTCPeerConnection({
        iceServers: [],
    });

    peerConnection = connection;
    connectedSessionId = requestedSession.session_id;

    connection.addEventListener(
        "connectionstatechange",
        updateConnectionState,
    );

    connection.addEventListener("track", (event) => {
        const [stream] = event.streams;

        if (stream) {
            remoteVideo.srcObject = stream;
        } else {
            const currentStream = (
                remoteVideo.srcObject
                ?? new MediaStream()
            );

            currentStream.addTrack(event.track);
            remoteVideo.srcObject = currentStream;
        }

        remoteVideo.hidden = false;
        placeholder.hidden = true;

        remoteVideo.play().catch(() => {
            connectionStatus.textContent =
                "Conectat. Apasă Play pentru a activa sunetul.";
        });
    });

    try {
        await connection.setRemoteDescription(
            requestedSession.offer,
        );

        const answer = await connection.createAnswer();
        await connection.setLocalDescription(answer);
        await waitForIceGatheringComplete(connection);

        const response = await fetch("/api/monitor/answer", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                session_id: requestedSession.session_id,
                answer: connection.localDescription,
            }),
        });

        await readJsonResponse(response);
        connectWhenReady = false;
        connectionStatus.textContent =
            "Răspuns trimis. Se așteaptă fluxul...";

        viewerHeartbeatTimer = window.setInterval(() => {
            sendViewerHeartbeat().catch((error) => {
                showError(error.message);
            });
        }, 3000);
    } catch (error) {
        closeViewerConnection(
            "Conexiunea nu a putut fi stabilită.",
        );
        showError(error.message);
    }
}


async function loadMonitorStatus() {
    const response = await fetch("/api/monitor/status");
    const data = await readJsonResponse(response);

    sourceIsArmed = data.armed;

    if (!data.armed) {
        cameraSelectionInitialized = false;
        cameraFacingSelect.disabled = true;
        availableSession = null;
        connectWhenReady = false;
        monitorStatus.textContent = "Nicio sursă armată";
        startRemoteButton.disabled = true;
        stopSourceButton.disabled = true;
        connectButton.disabled = true;

        if (peerConnection) {
            closeViewerConnection(
                "Pagina sursă nu mai este disponibilă.",
            );
        }

        return;
    }

    const ownerName = data.source?.username ?? "administrator";

    if (!cameraSelectionInitialized && data.camera_facing) {
        cameraFacingSelect.value = data.camera_facing;
        cameraSelectionInitialized = true;
    }

    if (data.source_state === "error") {
        monitorStatus.textContent =
            `Sursă armată de ${ownerName} · eroare`;
        startRemoteButton.disabled = true;
        stopSourceButton.disabled = false;
        cameraFacingSelect.disabled = true;

        if (data.source_error) {
            showError(data.source_error);
        }
    } else if (
        data.source_state === "starting"
        || data.desired_state === "live"
        && !data.active
    ) {
        monitorStatus.textContent =
            `Sursă armată de ${ownerName} · camera pornește...`;
        startRemoteButton.disabled = true;
        stopSourceButton.disabled = false;
        cameraFacingSelect.disabled = true;
    } else if (!data.active) {
        monitorStatus.textContent =
            `Sursă armată de ${ownerName} · camera este oprită`;
        startRemoteButton.disabled = false;
        stopSourceButton.disabled = true;
        cameraFacingSelect.disabled = false;
        connectButton.disabled = true;
        availableSession = null;

        if (peerConnection) {
            closeViewerConnection(
                "Camera și microfonul au fost oprite.",
            );
        }

        return;
    }

    if (!data.active || !data.offer) {
        availableSession = null;
        connectButton.disabled = true;
        return;
    }

    if (
        connectedSessionId
        && connectedSessionId !== data.session_id
    ) {
        closeViewerConnection(
            "A fost pornită o transmisie nouă.",
        );
    }

    availableSession = data;
    monitorStatus.textContent =
        `Camera este activă · pornită de ${ownerName}`;
    startRemoteButton.disabled = true;
    stopSourceButton.disabled = false;
    cameraFacingSelect.disabled = true;
    connectButton.disabled = peerConnection !== null;

    if (connectWhenReady && !peerConnection) {
        await connectToSource();
    }
}


async function setRemoteCaptureState(state, cameraFacing = null) {
    const payload = {state};

    if (cameraFacing) {
        payload.camera_facing = cameraFacing;
    }

    const response = await fetch("/api/monitor/control", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
    });

    return readJsonResponse(response);
}


async function startRemoteCapture() {
    if (!sourceIsArmed) {
        return;
    }

    clearError();
    connectWhenReady = true;
    startRemoteButton.disabled = true;
    stopSourceButton.disabled = false;
    monitorStatus.textContent = "Comandă trimisă către telefon...";
    connectionStatus.textContent =
        "Camera pornește; conexiunea se va face automat.";

    try {
        await setRemoteCaptureState(
            "live",
            cameraFacingSelect.value,
        );
        await loadMonitorStatus();
    } catch (error) {
        connectWhenReady = false;
        showError(error.message);
        startRemoteButton.disabled = false;
    }
}


async function stopRemoteCapture({confirmAction = true} = {}) {
    if (!sourceIsArmed) {
        return;
    }

    if (
        confirmAction
        && !window.confirm(
            "Oprești camera și microfonul de pe telefon? "
            + "Pagina va rămâne armată.",
        )
    ) {
        return;
    }

    clearError();
    connectWhenReady = false;
    stopSourceButton.disabled = true;

    try {
        await setRemoteCaptureState("armed");
        availableSession = null;
        closeViewerConnection(
            "Camera și microfonul au fost oprite. Sursa rămâne armată.",
        );
        await loadMonitorStatus();
    } catch (error) {
        showError(error.message);
        stopSourceButton.disabled = false;
    }
}


refreshButton.addEventListener("click", async () => {
    clearError();
    refreshButton.disabled = true;

    try {
        await loadMonitorStatus();
    } catch (error) {
        showError(error.message);
    } finally {
        refreshButton.disabled = false;
    }
});


startRemoteButton.addEventListener("click", () => {
    startRemoteCapture();
});


connectButton.addEventListener("click", () => {
    connectToSource();
});


stopSourceButton.addEventListener("click", () => {
    stopRemoteCapture();
});


createPairingCodeButton.addEventListener("click", async () => {
    clearError();
    createPairingCodeButton.disabled = true;

    try {
        const response = await fetch(
            "/api/monitor/devices/pairing-code",
            {method: "POST"},
        );
        const data = await readJsonResponse(response);

        pairingCode.textContent = data.code;
        pairingCode.hidden = false;
        pairingCodeStatus.textContent =
            "Valabil 5 minute · o singură utilizare";
        pairingCodeStatus.hidden = false;
    } catch (error) {
        showError(error.message);
    } finally {
        createPairingCodeButton.disabled = false;
    }
});


async function initializeMonitorPage() {
    remoteVideo.hidden = true;

    try {
        await loadMonitorStatus();
    } catch (error) {
        monitorStatus.textContent = "Acces indisponibil";
        connectionStatus.textContent =
            "Autentifică-te ca administrator în dashboard.";
        showError(error.message);
        return;
    }

    refreshTimer = window.setInterval(() => {
        loadMonitorStatus().catch((error) => {
            showError(error.message);
        });
    }, 1000);
}


window.addEventListener("pagehide", () => {
    if (refreshTimer) {
        window.clearInterval(refreshTimer);
    }

    if (peerConnection) {
        peerConnection.close();
    }

    if (sourceIsArmed && (availableSession || connectedSessionId)) {
        fetch("/api/monitor/control", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({state: "armed"}),
            keepalive: true,
        }).catch(() => {});
    }
});


initializeMonitorPage();
