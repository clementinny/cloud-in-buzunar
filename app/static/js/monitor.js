const monitorStatus = document.querySelector("#monitor-status");
const connectionStatus = document.querySelector(
    "#monitor-connection-status",
);
const refreshButton = document.querySelector(
    "#refresh-monitor-button",
);
const connectButton = document.querySelector(
    "#connect-monitor-button",
);
const disconnectButton = document.querySelector(
    "#disconnect-monitor-button",
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

let availableSession = null;
let peerConnection = null;
let connectedSessionId = null;
let refreshTimer = null;


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
    if (peerConnection) {
        peerConnection.close();
        peerConnection = null;
    }

    connectedSessionId = null;
    remoteVideo.srcObject = null;
    remoteVideo.hidden = true;
    placeholder.hidden = false;
    liveBadge.hidden = true;
    disconnectButton.disabled = true;

    if (message) {
        connectionStatus.textContent = message;
    }

    connectButton.disabled = !availableSession;
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


async function loadMonitorStatus() {
    const response = await fetch("/api/monitor/status");
    const data = await readJsonResponse(response);

    if (!data.active || !data.offer) {
        availableSession = null;
        monitorStatus.textContent = "Nicio sursă activă";
        stopSourceButton.disabled = true;
        connectButton.disabled = true;

        if (peerConnection) {
            closeViewerConnection(
                "Sursa de pe telefon a fost oprită.",
            );
        }

        return;
    }

    if (
        connectedSessionId
        && connectedSessionId !== data.session_id
    ) {
        closeViewerConnection(
            "A fost pornită o sursă nouă.",
        );
    }

    availableSession = data;
    monitorStatus.textContent =
        `Activă · pornită de ${data.source.username}`;
    stopSourceButton.disabled = false;
    connectButton.disabled = (
        peerConnection !== null
        || connectedSessionId === data.session_id
    );
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
        disconnectButton.disabled = false;

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
        disconnectButton.disabled = false;
        connectionStatus.textContent =
            "Răspuns trimis. Se așteaptă fluxul...";
    } catch (error) {
        closeViewerConnection(
            "Conexiunea nu a putut fi stabilită.",
        );
        showError(error.message);
    }
}


async function stopSource() {
    if (!availableSession) {
        return;
    }

    if (!window.confirm(
        "Oprești camera și microfonul de pe telefon?",
    )) {
        return;
    }

    clearError();
    stopSourceButton.disabled = true;

    try {
        const sessionId = encodeURIComponent(
            availableSession.session_id,
        );
        const response = await fetch(
            `/api/monitor/session/${sessionId}`,
            {
                method: "DELETE",
            },
        );

        await readJsonResponse(response);
        availableSession = null;
        closeViewerConnection(
            "Transmisia a fost oprită de administrator.",
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


connectButton.addEventListener("click", () => {
    connectToSource();
});


disconnectButton.addEventListener("click", () => {
    closeViewerConnection(
        "Vizualizarea a fost deconectată. Sursa rămâne activă.",
    );
});


stopSourceButton.addEventListener("click", () => {
    stopSource();
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
    }, 3000);
}


window.addEventListener("pagehide", () => {
    if (refreshTimer) {
        window.clearInterval(refreshTimer);
    }

    if (peerConnection) {
        peerConnection.close();
    }
});


initializeMonitorPage();
