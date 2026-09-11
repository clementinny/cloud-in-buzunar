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
const recordingStatus = document.querySelector("#recording-status");
const recordingModeSelect = document.querySelector("#recording-mode");
const recordingRetentionSelect = document.querySelector(
    "#recording-retention",
);
const recordingCameraFacingSelect = document.querySelector(
    "#recording-camera-facing",
);
const applyRecordingButton = document.querySelector(
    "#apply-recording-button",
);
const recordingCount = document.querySelector("#recording-count");
const recordingStorage = document.querySelector("#recording-storage");
const recordingList = document.querySelector("#recording-list");

let availableSession = null;
let sourceIsArmed = false;
let peerConnection = null;
let connectedSessionId = null;
let refreshTimer = null;
let viewerHeartbeatTimer = null;
let connectWhenReady = false;
let cameraSelectionInitialized = false;
let recordingSelectionInitialized = false;
let recordingsTimer = null;
let recordingArchiveMode = "off";
let browserMediaRecorder = null;
let browserRecordingChunks = [];
let browserRecordingStartedAt = null;
let browserRecordingMode = "off";
let browserRecordingTimer = null;
let browserRecordingStopPromise = null;

const browserRecordingSegmentMilliseconds = 10 * 60 * 1000;


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


function formatBytes(bytes) {
    if (!bytes) {
        return "0 B";
    }

    const units = ["B", "KB", "MB", "GB"];
    const index = Math.min(
        Math.floor(Math.log(bytes) / Math.log(1024)),
        units.length - 1,
    );
    return `${(bytes / (1024 ** index)).toFixed(1)} ${units[index]}`;
}


function recordingModeLabel(mode) {
    if (mode === "audio") {
        return "Se înregistrează numai sunetul";
    }

    if (mode === "video") {
        return "Se înregistrează video și sunet la 480p";
    }

    return "Înregistrarea este oprită";
}


function formatRecordingOffset(seconds) {
    const safeSeconds = Math.max(0, Math.floor(Number(seconds) || 0));
    const minutes = Math.floor(safeSeconds / 60);
    const remainingSeconds = safeSeconds % 60;
    return `${String(minutes).padStart(2, "0")}:`
        + String(remainingSeconds).padStart(2, "0");
}


function createSpeechActivity(entry, player) {
    const activity = document.createElement("div");
    activity.className = "monitor-speech-activity";

    if (["pending", "processing"].includes(entry.speech_status)) {
        activity.textContent = "Se verifică dacă se aude vorbire...";
        return activity;
    }

    if (entry.speech_status === "unavailable") {
        activity.textContent =
            "Analiza vorbirii necesită FFmpeg pe server.";
        return activity;
    }

    if (entry.speech_status === "failed") {
        activity.textContent =
            "Înregistrarea nu a putut fi analizată.";
        return activity;
    }

    const events = Array.isArray(entry.speech_events)
        ? entry.speech_events.filter(Number.isFinite)
        : [];

    if (events.length === 0) {
        activity.classList.add("is-quiet");
        activity.textContent = "Nu s-a detectat vorbire.";
        return activity;
    }

    const label = document.createElement("strong");
    label.textContent = "Vorbire probabilă: ";
    activity.append(label);

    for (const timestamp of events.slice(0, 12)) {
        const jumpButton = document.createElement("button");
        jumpButton.type = "button";
        jumpButton.className = "monitor-speech-time";
        jumpButton.textContent = formatRecordingOffset(timestamp);
        jumpButton.title = "Redă de la acest moment";
        jumpButton.addEventListener("click", () => {
            player.currentTime = timestamp;
            player.play().catch(() => {});
        });
        activity.append(jumpButton);
    }

    if (events.length > 12) {
        const remaining = document.createElement("span");
        remaining.textContent = `+${events.length - 12}`;
        activity.append(remaining);
    }

    return activity;
}


function renderRecordingControls(data) {
    const settings = data.recording ?? {
        desired_mode: "off",
        actual_mode: "off",
        retention_hours: 48,
        camera_facing: "environment",
    };

    recordingArchiveMode = settings.desired_mode;

    if (!data.armed) {
        recordingStatus.textContent =
            "Armează aplicația Android pentru a înregistra.";
        recordingModeSelect.disabled = true;
        recordingRetentionSelect.disabled = true;
        recordingCameraFacingSelect.disabled = true;
        applyRecordingButton.disabled = true;
        return;
    }

    if (!recordingSelectionInitialized) {
        recordingModeSelect.value = settings.desired_mode;
        recordingRetentionSelect.value = String(
            settings.retention_hours,
        );
        recordingCameraFacingSelect.value =
            settings.camera_facing ?? "environment";
        recordingSelectionInitialized = true;
    }

    if (data.active && settings.desired_mode !== "off") {
        recordingStatus.textContent = settings.desired_mode === "audio"
            ? "LIVE · sunetul transmis este arhivat în browser"
            : "LIVE · transmisia video și audio este arhivată în browser";
    } else if (settings.desired_mode !== settings.actual_mode) {
        recordingStatus.textContent = settings.desired_mode === "off"
            ? "Se oprește și se salvează segmentul curent..."
            : "Telefonul pregătește înregistrarea...";
    } else {
        recordingStatus.textContent = recordingModeLabel(
            settings.actual_mode,
        );
    }

    const controlsDisabled = !data.armed || data.active;
    recordingModeSelect.disabled = controlsDisabled;
    recordingRetentionSelect.disabled = controlsDisabled;
    recordingCameraFacingSelect.disabled = controlsDisabled;
    applyRecordingButton.disabled = controlsDisabled;
}


function renderRecordings(entries) {
    recordingList.replaceChildren();

    if (entries.length === 0) {
        const empty = document.createElement("p");
        empty.className = "monitor-recording-empty";
        empty.textContent = "Nu există încă înregistrări.";
        recordingList.append(empty);
        return;
    }

    for (const entry of entries) {
        const item = document.createElement("article");
        item.className = "monitor-recording-item";

        const information = document.createElement("div");
        const title = document.createElement("strong");
        const startedAt = new Date(entry.started_at);
        const endedAt = new Date(entry.ended_at);
        title.textContent = entry.mode === "audio"
            ? "Microfon"
            : "Video + microfon · 480p";

        const details = document.createElement("p");
        details.textContent = (
            `${startedAt.toLocaleString("ro-RO")} – `
            + `${endedAt.toLocaleTimeString("ro-RO")} · `
            + formatBytes(entry.size_bytes)
        );
        information.append(title, details);

        const player = document.createElement(
            entry.mode === "audio" ? "audio" : "video",
        );
        player.controls = true;
        player.preload = "none";
        player.src = entry.play_url;
        information.append(createSpeechActivity(entry, player));

        const deleteButton = document.createElement("button");
        deleteButton.type = "button";
        deleteButton.className = "danger-button";
        deleteButton.textContent = "Șterge";
        deleteButton.addEventListener("click", async () => {
            if (!window.confirm("Ștergi această înregistrare?")) {
                return;
            }

            deleteButton.disabled = true;

            try {
                const response = await fetch(entry.play_url, {
                    method: "DELETE",
                });
                await readJsonResponse(response);
                await loadRecordings();
            } catch (error) {
                showError(error.message);
                deleteButton.disabled = false;
            }
        });

        item.append(information, player, deleteButton);
        recordingList.append(item);
    }
}


async function loadRecordings() {
    const response = await fetch("/api/monitor/recordings");
    const data = await readJsonResponse(response);
    const label = data.count === 1 ? "înregistrare" : "înregistrări";
    recordingCount.textContent = `${data.count} ${label}`;
    recordingStorage.textContent = `${formatBytes(data.size_bytes)} ocupați`;
    renderRecordings(data.recordings);
}


function browserRecordingMimeType(mode) {
    const candidates = mode === "audio"
        ? ["audio/webm;codecs=opus", "audio/webm"]
        : ["video/webm;codecs=vp8,opus", "video/webm"];

    return candidates.find((candidate) => (
        MediaRecorder.isTypeSupported(candidate)
    )) ?? "";
}


async function uploadBrowserRecording(
    blob,
    mode,
    startedAt,
    endedAt,
) {
    if (!blob.size) {
        return;
    }

    const formData = new FormData();
    formData.append("mode", mode);
    formData.append("container", "webm");
    formData.append(
        "camera_facing",
        mode === "video" ? cameraFacingSelect.value : "",
    );
    formData.append("started_at_ms", String(startedAt));
    formData.append("ended_at_ms", String(endedAt));
    formData.append(
        "recording",
        blob,
        `monitor-${startedAt}.webm`,
    );

    const response = await fetch(
        "/api/monitor/recordings",
        {
            method: "POST",
            body: formData,
        },
    );
    await readJsonResponse(response);
    await loadRecordings();
}


function maybeStartBrowserRecording() {
    if (
        browserMediaRecorder
        || browserRecordingStopPromise
        || recordingArchiveMode === "off"
        || !peerConnection
        || !remoteVideo.srcObject
    ) {
        return;
    }

    if (typeof MediaRecorder === "undefined") {
        showError(
            "Browserul nu poate arhiva transmisia live. "
            + "Înregistrarea locală va continua după oprirea live-ului.",
        );
        return;
    }

    const remoteStream = remoteVideo.srcObject;
    const audioTracks = remoteStream.getAudioTracks();
    const videoTracks = remoteStream.getVideoTracks();

    if (audioTracks.length === 0) {
        return;
    }

    if (recordingArchiveMode === "video" && videoTracks.length === 0) {
        return;
    }

    const tracks = recordingArchiveMode === "audio"
        ? audioTracks
        : [...videoTracks, ...audioTracks];
    const archiveStream = new MediaStream(tracks);
    const mimeType = browserRecordingMimeType(recordingArchiveMode);
    const options = recordingArchiveMode === "video"
        ? {
            videoBitsPerSecond: 600000,
            audioBitsPerSecond: 24000,
        }
        : {audioBitsPerSecond: 24000};

    if (mimeType) {
        options.mimeType = mimeType;
    }

    try {
        browserRecordingChunks = [];
        browserRecordingStartedAt = Date.now();
        browserRecordingMode = recordingArchiveMode;
        browserMediaRecorder = new MediaRecorder(
            archiveStream,
            options,
        );
        browserMediaRecorder.addEventListener(
            "dataavailable",
            (event) => {
                if (event.data.size > 0) {
                    browserRecordingChunks.push(event.data);
                }
            },
        );
        browserMediaRecorder.start(5000);
        browserRecordingTimer = window.setTimeout(() => {
            stopBrowserRecordingSegment({restart: true}).catch((error) => {
                showError(error.message);
            });
        }, browserRecordingSegmentMilliseconds);
    } catch (error) {
        browserMediaRecorder = null;
        browserRecordingMode = "off";
        showError(`Arhivarea transmisiei nu a pornit: ${error.message}`);
    }
}


function stopBrowserRecordingSegment({restart = false} = {}) {
    if (browserRecordingStopPromise) {
        return browserRecordingStopPromise;
    }

    if (!browserMediaRecorder) {
        return Promise.resolve();
    }

    if (browserRecordingTimer) {
        window.clearTimeout(browserRecordingTimer);
        browserRecordingTimer = null;
    }

    const recorder = browserMediaRecorder;

    if (recorder.state === "inactive") {
        browserMediaRecorder = null;
        browserRecordingChunks = [];
        browserRecordingStartedAt = null;
        browserRecordingMode = "off";
        return Promise.resolve();
    }

    const chunks = browserRecordingChunks;
    const mode = browserRecordingMode;
    const startedAt = browserRecordingStartedAt;
    browserMediaRecorder = null;
    browserRecordingStartedAt = null;
    browserRecordingMode = "off";

    browserRecordingStopPromise = new Promise((resolve, reject) => {
        recorder.addEventListener("stop", async () => {
            try {
                const endedAt = Date.now();
                const blob = new Blob(chunks, {
                    type: recorder.mimeType || `${mode}/webm`,
                });
                await uploadBrowserRecording(
                    blob,
                    mode,
                    startedAt,
                    endedAt,
                );
                resolve();
            } catch (error) {
                reject(error);
            } finally {
                browserRecordingStopPromise = null;

                if (
                    restart
                    && peerConnection
                    && recordingArchiveMode === mode
                ) {
                    maybeStartBrowserRecording();
                }
            }
        }, {once: true});

        recorder.stop();
    });

    return browserRecordingStopPromise;
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
    stopBrowserRecordingSegment().catch((error) => {
        showError(error.message);
    });

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
        maybeStartBrowserRecording();
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
        const currentStream = (
            remoteVideo.srcObject
            ?? new MediaStream()
        );

        if (!currentStream.getTracks().includes(event.track)) {
            currentStream.addTrack(event.track);
        }

        remoteVideo.srcObject = currentStream;

        remoteVideo.hidden = false;
        placeholder.hidden = true;

        remoteVideo.play().catch(() => {
            connectionStatus.textContent =
                "Conectat. Apasă Play pentru a activa sunetul.";
        });
        maybeStartBrowserRecording();
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
    renderRecordingControls(data);

    if (!data.armed) {
        cameraSelectionInitialized = false;
        recordingSelectionInitialized = false;
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
        await stopBrowserRecordingSegment();
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


applyRecordingButton.addEventListener("click", async () => {
    clearError();
    applyRecordingButton.disabled = true;

    try {
        const response = await fetch(
            "/api/monitor/recordings/control",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    mode: recordingModeSelect.value,
                    retention_hours: Number(
                        recordingRetentionSelect.value,
                    ),
                    camera_facing:
                        recordingCameraFacingSelect.value,
                }),
            },
        );
        await readJsonResponse(response);
        await loadMonitorStatus();
        window.setTimeout(() => {
            loadRecordings().catch((error) => {
                showError(error.message);
            });
        }, 1500);
    } catch (error) {
        showError(error.message);
    } finally {
        loadMonitorStatus().catch((error) => {
            showError(error.message);
        });
    }
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
        await Promise.all([
            loadMonitorStatus(),
            loadRecordings(),
        ]);
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

    recordingsTimer = window.setInterval(() => {
        loadRecordings().catch((error) => {
            showError(error.message);
        });
    }, 15000);
}


window.addEventListener("pagehide", () => {
    if (refreshTimer) {
        window.clearInterval(refreshTimer);
    }

    if (recordingsTimer) {
        window.clearInterval(recordingsTimer);
    }

    if (peerConnection) {
        peerConnection.close();
    }

    stopBrowserRecordingSegment().catch(() => {});

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
