const sourceStatus = document.querySelector("#source-status");
const sourceLiveBadge = document.querySelector(
    "#source-live-badge",
);
const cameraFacingSelect = document.querySelector(
    "#camera-facing-select",
);
const localVideo = document.querySelector("#local-video");
const sourcePlaceholder = document.querySelector(
    "#source-placeholder",
);
const sourceError = document.querySelector("#source-error");
const startButton = document.querySelector(
    "#start-source-button",
);
const toggleCameraButton = document.querySelector(
    "#toggle-camera-button",
);
const toggleMicrophoneButton = document.querySelector(
    "#toggle-microphone-button",
);
const stopButton = document.querySelector(
    "#stop-source-button",
);

let localStream = null;
let peerConnection = null;
let monitorSessionId = null;
let answerTimer = null;
let heartbeatTimer = null;
let answerWasApplied = false;


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
    sourceError.textContent = message;
    sourceError.hidden = false;
}


function clearError() {
    sourceError.textContent = "";
    sourceError.hidden = true;
}


function createSessionId() {
    if (typeof crypto.randomUUID === "function") {
        return crypto.randomUUID();
    }

    const randomBytes = new Uint8Array(24);
    crypto.getRandomValues(randomBytes);

    return Array.from(
        randomBytes,
        (value) => value.toString(16).padStart(2, "0"),
    ).join("");
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


function updateCaptureBadge() {
    if (!localStream) {
        sourceLiveBadge.hidden = true;
        return;
    }

    const videoTrack = localStream.getVideoTracks()[0];
    const audioTrack = localStream.getAudioTracks()[0];
    const cameraState = videoTrack?.enabled
        ? "CAMERĂ ACTIVĂ"
        : "CAMERĂ OPRITĂ";
    const microphoneState = audioTrack?.enabled
        ? "MICROFON ACTIV"
        : "MICROFON OPRIT";

    sourceLiveBadge.textContent =
        `${cameraState} · ${microphoneState}`;
    sourceLiveBadge.hidden = false;
}


function updateButtonState() {
    const isActive = localStream !== null;

    startButton.disabled = isActive;
    cameraFacingSelect.disabled = isActive;
    toggleCameraButton.disabled = !isActive;
    toggleMicrophoneButton.disabled = !isActive;
    stopButton.disabled = !isActive;

    if (!isActive) {
        toggleCameraButton.textContent = "Oprește camera";
        toggleMicrophoneButton.textContent =
            "Oprește microfonul";
        return;
    }

    const videoTrack = localStream.getVideoTracks()[0];
    const audioTrack = localStream.getAudioTracks()[0];

    toggleCameraButton.textContent = videoTrack?.enabled
        ? "Oprește camera"
        : "Pornește camera";
    toggleMicrophoneButton.textContent = audioTrack?.enabled
        ? "Oprește microfonul"
        : "Pornește microfonul";
}


function clearTimers() {
    if (answerTimer) {
        window.clearInterval(answerTimer);
        answerTimer = null;
    }

    if (heartbeatTimer) {
        window.clearInterval(heartbeatTimer);
        heartbeatTimer = null;
    }
}


async function notifyServerToStop(sessionId) {
    if (!sessionId) {
        return;
    }

    const encodedSessionId = encodeURIComponent(sessionId);
    const response = await fetch(
        `/api/monitor/session/${encodedSessionId}`,
        {
            method: "DELETE",
            keepalive: true,
        },
    );

    await readJsonResponse(response);
}


async function stopCapture({notifyServer = true} = {}) {
    const sessionId = monitorSessionId;

    clearTimers();
    monitorSessionId = null;
    answerWasApplied = false;

    if (peerConnection) {
        peerConnection.close();
        peerConnection = null;
    }

    if (localStream) {
        for (const track of localStream.getTracks()) {
            track.stop();
        }
    }

    localStream = null;
    localVideo.srcObject = null;
    localVideo.hidden = true;
    sourcePlaceholder.hidden = false;
    sourceStatus.textContent = "Transmisia este oprită.";
    updateCaptureBadge();
    updateButtonState();

    if (notifyServer && sessionId) {
        try {
            await notifyServerToStop(sessionId);
        } catch (error) {
            showError(error.message);
        }
    }
}


function updateConnectionState() {
    if (!peerConnection) {
        return;
    }

    const state = peerConnection.connectionState;

    if (state === "connected") {
        sourceStatus.textContent =
            "Transmisie activă · administrator conectat";
        return;
    }

    if (state === "connecting") {
        sourceStatus.textContent =
            "Administratorul se conectează...";
        return;
    }

    if (state === "failed") {
        sourceStatus.textContent =
            "Conexiunea WebRTC a eșuat. Repornește transmisia.";
    }
}


async function pollForAnswer() {
    if (!monitorSessionId || answerWasApplied) {
        return;
    }

    const query = new URLSearchParams({
        session_id: monitorSessionId,
    });
    const response = await fetch(
        `/api/monitor/answer?${query.toString()}`,
    );
    const data = await readJsonResponse(response);

    if (!data.active) {
        await stopCapture({notifyServer: false});
        sourceStatus.textContent =
            "Transmisia a fost oprită de administrator.";
        return;
    }

    if (!data.answer || !peerConnection) {
        return;
    }

    await peerConnection.setRemoteDescription(data.answer);
    answerWasApplied = true;

    if (answerTimer) {
        window.clearInterval(answerTimer);
        answerTimer = null;
    }

    sourceStatus.textContent =
        "Răspuns primit. Se stabilește conexiunea...";
}


async function sendHeartbeat() {
    if (!monitorSessionId) {
        return;
    }

    const response = await fetch("/api/monitor/heartbeat", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({
            session_id: monitorSessionId,
        }),
    });
    const data = await readJsonResponse(response);

    if (!data.active) {
        await stopCapture({notifyServer: false});
        sourceStatus.textContent =
            "Transmisia a fost oprită de administrator.";
    }
}


async function startCapture() {
    if (localStream) {
        return;
    }

    clearError();

    if (
        !window.isSecureContext
        || !navigator.mediaDevices?.getUserMedia
    ) {
        throw new Error(
            "Browserul nu permite accesul la cameră aici. "
            + "Deschide această pagină pe telefon folosind "
            + "http://127.0.0.1:8080/monitor/source.",
        );
    }

    startButton.disabled = true;
    sourceStatus.textContent =
        "Se solicită permisiunea pentru cameră și microfon...";

    const stream = await navigator.mediaDevices.getUserMedia({
        video: {
            facingMode: {
                ideal: cameraFacingSelect.value,
            },
            width: {
                ideal: 1280,
            },
            height: {
                ideal: 720,
            },
        },
        audio: {
            echoCancellation: false,
            noiseSuppression: false,
        },
    });

    localStream = stream;
    localVideo.srcObject = stream;
    localVideo.hidden = false;
    sourcePlaceholder.hidden = true;
    updateCaptureBadge();
    updateButtonState();

    const connection = new RTCPeerConnection({
        iceServers: [],
    });

    peerConnection = connection;
    connection.addEventListener(
        "connectionstatechange",
        updateConnectionState,
    );

    for (const track of stream.getTracks()) {
        connection.addTrack(track, stream);
    }

    const offer = await connection.createOffer();
    await connection.setLocalDescription(offer);
    await waitForIceGatheringComplete(connection);

    const sessionId = createSessionId();
    const response = await fetch("/api/monitor/offer", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({
            session_id: sessionId,
            offer: connection.localDescription,
        }),
    });

    await readJsonResponse(response);
    monitorSessionId = sessionId;
    sourceStatus.textContent =
        "Sursa este activă · așteaptă administratorul";

    answerTimer = window.setInterval(() => {
        pollForAnswer().catch((error) => {
            showError(error.message);
        });
    }, 1000);

    heartbeatTimer = window.setInterval(() => {
        sendHeartbeat().catch((error) => {
            showError(error.message);
        });
    }, 4000);
}


startButton.addEventListener("click", async () => {
    try {
        await startCapture();
    } catch (error) {
        await stopCapture({notifyServer: false});
        showError(error.message);
    }
});


toggleCameraButton.addEventListener("click", () => {
    const videoTrack = localStream?.getVideoTracks()[0];

    if (!videoTrack) {
        return;
    }

    videoTrack.enabled = !videoTrack.enabled;
    updateCaptureBadge();
    updateButtonState();
});


toggleMicrophoneButton.addEventListener("click", () => {
    const audioTrack = localStream?.getAudioTracks()[0];

    if (!audioTrack) {
        return;
    }

    audioTrack.enabled = !audioTrack.enabled;
    updateCaptureBadge();
    updateButtonState();
});


stopButton.addEventListener("click", () => {
    stopCapture();
});


window.addEventListener("pagehide", () => {
    const sessionId = monitorSessionId;

    clearTimers();

    if (sessionId) {
        const encodedSessionId = encodeURIComponent(sessionId);

        fetch(
            `/api/monitor/session/${encodedSessionId}`,
            {
                method: "DELETE",
                keepalive: true,
            },
        ).catch(() => {});
    }

    if (localStream) {
        for (const track of localStream.getTracks()) {
            track.stop();
        }
    }
});


async function initializeSourcePage() {
    localVideo.hidden = true;
    updateCaptureBadge();
    updateButtonState();

    try {
        const response = await fetch("/api/monitor/status");
        await readJsonResponse(response);
        sourceStatus.textContent =
            "Pregătit. Camera și microfonul sunt oprite.";
    } catch (error) {
        sourceStatus.textContent = "Acces indisponibil";
        startButton.disabled = true;
        showError(
            `${error.message}. Autentifică-te ca administrator.`,
        );
    }
}


initializeSourcePage();
