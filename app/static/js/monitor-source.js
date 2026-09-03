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
let sourceId = null;
let sourceIsArmed = false;
let sourceState = "armed";
let sourceStateError = null;
let answerWasApplied = false;
let answerTimer = null;
let sessionHeartbeatTimer = null;
let controlTimer = null;
let controlPollIsRunning = false;
let wakeLock = null;


async function readJsonResponse(response) {
    let data = null;

    try {
        data = await response.json();
    } catch (error) {
        data = null;
    }

    if (!response.ok) {
        const responseError = new Error(
            data?.error
            ?? `Cererea a eșuat: HTTP ${response.status}`,
        );
        responseError.status = response.status;
        throw responseError;
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
    sourceStateError = null;
}


function createIdentifier() {
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


function getMediaConstraints() {
    return {
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
    };
}


function ensureMediaSupport() {
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


async function requestScreenWakeLock() {
    if (
        !sourceIsArmed
        || document.visibilityState !== "visible"
        || !("wakeLock" in navigator)
        || wakeLock
    ) {
        return;
    }

    try {
        wakeLock = await navigator.wakeLock.request("screen");
        wakeLock.addEventListener("release", () => {
            wakeLock = null;
        });
    } catch (error) {
        showError(
            "Ecranul nu a putut fi menținut activ. "
            + "Dezactivează blocarea automată cât timp sursa "
            + "este armată.",
        );
    }
}


async function releaseScreenWakeLock() {
    if (!wakeLock) {
        return;
    }

    const currentWakeLock = wakeLock;
    wakeLock = null;

    try {
        await currentWakeLock.release();
    } catch (error) {
        // The browser may already have released it.
    }
}


function updateCaptureBadge() {
    if (!localStream) {
        if (sourceIsArmed) {
            sourceLiveBadge.textContent =
                "ARMAT · CAMERA ȘI MICROFONUL SUNT OPRITE";
            sourceLiveBadge.classList.add("is-armed");
            sourceLiveBadge.hidden = false;
        } else {
            sourceLiveBadge.hidden = true;
        }

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

    sourceLiveBadge.classList.remove("is-armed");
    sourceLiveBadge.textContent =
        `${cameraState} · ${microphoneState}`;
    sourceLiveBadge.hidden = false;
}


function updateButtonState() {
    const captureIsActive = localStream !== null;

    startButton.disabled = sourceIsArmed;
    cameraFacingSelect.disabled = sourceIsArmed;
    toggleCameraButton.disabled = !captureIsActive;
    toggleMicrophoneButton.disabled = !captureIsActive;
    stopButton.disabled = !sourceIsArmed;

    if (!captureIsActive) {
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


function clearSessionTimers() {
    if (answerTimer) {
        window.clearInterval(answerTimer);
        answerTimer = null;
    }

    if (sessionHeartbeatTimer) {
        window.clearInterval(sessionHeartbeatTimer);
        sessionHeartbeatTimer = null;
    }
}


function clearControlTimer() {
    if (controlTimer) {
        window.clearInterval(controlTimer);
        controlTimer = null;
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

    clearSessionTimers();
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
    sourceState = "armed";
    sourceStateError = null;

    if (sourceIsArmed) {
        sourceStatus.textContent =
            "Armat · așteaptă comanda de pe PC.";
    } else {
        sourceStatus.textContent = "Sursa este dezarmată.";
    }

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
        sourceStateError = "Conexiunea WebRTC a eșuat.";
        showError(
            "Conexiunea WebRTC a eșuat. Oprește și pornește "
            + "din nou camera de pe PC.",
        );
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


async function sendSessionHeartbeat() {
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
    }
}


async function startCapture() {
    if (!sourceIsArmed || localStream) {
        return;
    }

    clearError();
    ensureMediaSupport();
    sourceState = "starting";
    sourceStatus.textContent =
        "Comandă primită · se pornesc camera și microfonul...";

    try {
        const stream = await navigator.mediaDevices.getUserMedia(
            getMediaConstraints(),
        );

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

        const sessionId = createIdentifier();
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
        sourceState = "live";
        sourceStatus.textContent =
            "Camera este pornită · așteaptă conexiunea de pe PC";

        answerTimer = window.setInterval(() => {
            pollForAnswer().catch((error) => {
                showError(error.message);
            });
        }, 1000);

        sessionHeartbeatTimer = window.setInterval(() => {
            sendSessionHeartbeat().catch((error) => {
                showError(error.message);
            });
        }, 4000);
    } catch (error) {
        await stopCapture({notifyServer: true});
        sourceState = "error";
        sourceStateError = error.message;
        showError(
            `${error.message} Folosește „Oprește camera” pe PC, `
            + "apoi încearcă din nou.",
        );
        throw error;
    }
}


async function pollRemoteControl() {
    if (
        !sourceIsArmed
        || !sourceId
        || controlPollIsRunning
    ) {
        return;
    }

    controlPollIsRunning = true;

    try {
        const response = await fetch("/api/monitor/source/poll", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                source_id: sourceId,
                actual_state: sourceState,
                error: sourceStateError,
            }),
        });
        const data = await readJsonResponse(response);

        if (data.desired_state === "live") {
            if (sourceState === "armed" && !localStream) {
                await startCapture();
            }
        } else if (
            data.desired_state === "armed"
            && sourceState !== "armed"
        ) {
            await stopCapture({notifyServer: true});
        }
    } catch (error) {
        if (error.status === 404) {
            await disarmSource({notifyServer: false});
            showError(
                "Sursa a expirat sau a fost înlocuită. Armeaz-o din nou.",
            );
        } else {
            showError(error.message);
        }
    } finally {
        controlPollIsRunning = false;
    }
}


async function armSource() {
    if (sourceIsArmed) {
        return;
    }

    clearError();
    ensureMediaSupport();
    startButton.disabled = true;
    sourceStatus.textContent =
        "Se verifică permisiunile camerei și microfonului...";

    let permissionStream = null;

    try {
        permissionStream = await navigator.mediaDevices.getUserMedia(
            getMediaConstraints(),
        );

        for (const track of permissionStream.getTracks()) {
            track.stop();
        }

        permissionStream = null;
        const newSourceId = createIdentifier();
        const response = await fetch("/api/monitor/source/arm", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                source_id: newSourceId,
                camera_facing: cameraFacingSelect.value,
            }),
        });

        await readJsonResponse(response);
        sourceId = newSourceId;
        sourceIsArmed = true;
        sourceState = "armed";
        sourceStateError = null;
        sourceStatus.textContent =
            "Armat · așteaptă comanda de pe PC.";
        updateCaptureBadge();
        updateButtonState();
        await requestScreenWakeLock();

        controlTimer = window.setInterval(() => {
            pollRemoteControl();
        }, 1000);

        await pollRemoteControl();
    } catch (error) {
        if (permissionStream) {
            for (const track of permissionStream.getTracks()) {
                track.stop();
            }
        }

        sourceIsArmed = false;
        sourceId = null;
        sourceStatus.textContent = "Sursa nu a fost armată.";
        updateCaptureBadge();
        updateButtonState();
        showError(error.message);
    }
}


async function disarmSource({notifyServer = true} = {}) {
    const currentSourceId = sourceId;

    clearControlTimer();
    sourceIsArmed = false;
    sourceId = null;
    await stopCapture({notifyServer: true});
    await releaseScreenWakeLock();
    updateCaptureBadge();
    updateButtonState();
    sourceStatus.textContent = "Sursa este dezarmată.";

    if (notifyServer && currentSourceId) {
        const encodedSourceId = encodeURIComponent(currentSourceId);

        try {
            const response = await fetch(
                `/api/monitor/source/${encodedSourceId}`,
                {
                    method: "DELETE",
                    keepalive: true,
                },
            );
            await readJsonResponse(response);
        } catch (error) {
            showError(error.message);
        }
    }
}


startButton.addEventListener("click", () => {
    armSource();
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
    disarmSource();
});


document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && sourceIsArmed) {
        requestScreenWakeLock();
        pollRemoteControl();
    }
});


window.addEventListener("pagehide", () => {
    const currentSourceId = sourceId;

    clearControlTimer();
    clearSessionTimers();

    if (currentSourceId) {
        const encodedSourceId = encodeURIComponent(currentSourceId);

        fetch(
            `/api/monitor/source/${encodedSourceId}`,
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
            "Pregătit. Apasă „Armează controlul de la distanță”.";
    } catch (error) {
        sourceStatus.textContent = "Acces indisponibil";
        startButton.disabled = true;
        showError(
            `${error.message}. Autentifică-te ca administrator.`,
        );
    }
}


initializeSourcePage();
