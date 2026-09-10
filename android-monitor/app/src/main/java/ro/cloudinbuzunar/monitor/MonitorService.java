package ro.cloudinbuzunar.monitor;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.graphics.SurfaceTexture;
import android.hardware.Camera;
import android.media.MediaRecorder;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;
import android.util.Log;

import org.json.JSONObject;
import org.webrtc.AudioSource;
import org.webrtc.AudioTrack;
import org.webrtc.Camera1Enumerator;
import org.webrtc.CameraEnumerator;
import org.webrtc.CameraVideoCapturer;
import org.webrtc.DataChannel;
import org.webrtc.DefaultVideoDecoderFactory;
import org.webrtc.DefaultVideoEncoderFactory;
import org.webrtc.EglBase;
import org.webrtc.IceCandidate;
import org.webrtc.MediaConstraints;
import org.webrtc.MediaStream;
import org.webrtc.PeerConnection;
import org.webrtc.PeerConnectionFactory;
import org.webrtc.RtpReceiver;
import org.webrtc.SdpObserver;
import org.webrtc.SessionDescription;
import org.webrtc.SurfaceTextureHelper;
import org.webrtc.VideoSource;
import org.webrtc.VideoTrack;

import java.util.Collections;
import java.io.File;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

public final class MonitorService extends Service {
    private static final String LOG_TAG = "CloudMonitor";
    static final String ACTION_ARM = "ro.cloudinbuzunar.monitor.ARM";
    static final String ACTION_DISARM = "ro.cloudinbuzunar.monitor.DISARM";
    static final String STATUS_ACTION = "ro.cloudinbuzunar.monitor.STATUS";
    static final String QUERY_ACTION = "ro.cloudinbuzunar.monitor.QUERY";
    static final String EXTRA_CAMERA_FACING = "camera_facing";
    static final String EXTRA_STATE = "state";
    static final String EXTRA_MESSAGE = "message";

    private static final String CHANNEL_ID = "cloud_monitor";
    private static final int NOTIFICATION_ID = 4102;
    private static final long RECORDING_SEGMENT_MILLIS = 10 * 60 * 1000L;

    static volatile String currentState = "stopped";
    static volatile String currentMessage = null;

    private final ScheduledExecutorService executor =
        Executors.newSingleThreadScheduledExecutor();

    private ApiClient api;
    private String sourceId;
    private String cameraFacing = "environment";
    private String recordingCameraFacing = "environment";
    private String activeRecordingCameraFacing = "environment";
    private volatile String state = "armed";
    private volatile String errorMessage;
    private volatile boolean armed;
    private volatile boolean captureStarting;
    private long lastHeartbeatAt;

    private PowerManager.WakeLock wakeLock;
    private WifiManager.WifiLock wifiLock;
    private EglBase eglBase;
    private PeerConnectionFactory peerConnectionFactory;
    private PeerConnection peerConnection;
    private CameraVideoCapturer cameraCapturer;
    private SurfaceTextureHelper surfaceTextureHelper;
    private VideoSource videoSource;
    private VideoTrack videoTrack;
    private AudioSource audioSource;
    private AudioTrack audioTrack;
    private String monitorSessionId;
    private boolean answerApplied;
    private CountDownLatch iceGatheringLatch;

    private MediaRecorder segmentRecorder;
    private Camera segmentCamera;
    private SurfaceTexture segmentPreviewTexture;
    private File segmentFile;
    private long segmentStartedAt;
    private String desiredRecordingMode = "off";
    private String actualRecordingMode = "off";
    private ScheduledFuture<?> recordingRotation;

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannel();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        String action = intent == null ? null : intent.getAction();

        if (ACTION_DISARM.equals(action)) {
            MonitorStateStore.disarm(this);
            executor.execute(this::disarmAndStop);
            return START_NOT_STICKY;
        }

        if (QUERY_ACTION.equals(action)) {
            broadcastState(currentState, currentMessage);
            return armed ? START_STICKY : START_NOT_STICKY;
        }

        if (!ACTION_ARM.equals(action)) {
            if (!armed && !MonitorStateStore.isArmed(this)) {
                stopSelf();
                return START_NOT_STICKY;
            }

            if (!armed) {
                cameraFacing = MonitorStateStore.cameraFacing(this);
                recordingCameraFacing =
                    MonitorStateStore.recordingCameraFacing(this);
                startAsForeground(
                    "Se reface legătura · camera și microfonul sunt oprite"
                );
                executor.execute(this::armOnServer);
            }

            return START_STICKY;
        }

        cameraFacing = intent.getStringExtra(EXTRA_CAMERA_FACING);

        if (!"user".equals(cameraFacing)) {
            cameraFacing = "environment";
        }

        MonitorStateStore.arm(this, cameraFacing);
        startAsForeground("Armat · camera și microfonul sunt oprite");
        executor.execute(this::armOnServer);
        return START_STICKY;
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void onDestroy() {
        armed = false;
        stopLocalRecording(false);
        cleanupCapture();
        releaseLocks();
        executor.shutdownNow();

        if ("error".equals(state)) {
            broadcastState("error", errorMessage);
        } else {
            broadcastState("stopped", "Serviciul a fost oprit.");
        }

        super.onDestroy();
    }

    private void armOnServer() {
        String token = TokenStore.read(this);

        if (token == null) {
            failAndStop("Aplicația nu mai este asociată cu serverul.");
            return;
        }

        api = new ApiClient(token);
        sourceId = UUID.randomUUID().toString();

        try {
            api.arm(sourceId, cameraFacing);
            armed = true;
            state = "armed";
            errorMessage = null;
            acquireWakeLock();
            uploadPendingRecordings();
            publishState(
                "armed",
                "Așteaptă comanda din dashboard. Ecranul poate fi stins."
            );
            executor.scheduleWithFixedDelay(
                this::pollSafely,
                0,
                1,
                TimeUnit.SECONDS
            );
        } catch (Exception error) {
            failAndStop("Armarea a eșuat: " + error.getMessage());
        }
    }

    private void pollSafely() {
        if (!armed || api == null) {
            return;
        }

        try {
            JSONObject response = api.poll(
                sourceId,
                state,
                errorMessage,
                actualRecordingMode
            );
            String desiredState = response.getString("desired_state");
            desiredRecordingMode = response.optString(
                "recording_mode",
                "off"
            );
            String requestedCameraFacing = response.optString(
                "camera_facing",
                cameraFacing
            );
            String requestedRecordingCameraFacing = response.optString(
                "recording_camera_facing",
                recordingCameraFacing
            );

            if (
                "user".equals(requestedCameraFacing)
                || "environment".equals(requestedCameraFacing)
            ) {
                if (!requestedCameraFacing.equals(cameraFacing)) {
                    cameraFacing = requestedCameraFacing;
                    MonitorStateStore.updateCameraFacing(this, cameraFacing);
                }
            }

            if (
                "user".equals(requestedRecordingCameraFacing)
                || "environment".equals(requestedRecordingCameraFacing)
            ) {
                if (!requestedRecordingCameraFacing.equals(
                    recordingCameraFacing
                )) {
                    recordingCameraFacing =
                        requestedRecordingCameraFacing;
                    MonitorStateStore.updateRecordingCameraFacing(
                        this,
                        recordingCameraFacing
                    );
                }
            }

            if ("live".equals(desiredState)) {
                if (!"off".equals(actualRecordingMode)) {
                    stopLocalRecording(true);
                }

                if ("armed".equals(state) && !captureStarting) {
                    startCapture();
                } else if ("live".equals(state)) {
                    maintainLiveSession();
                }
            } else {
                if (!"armed".equals(state)) {
                    stopCapture(true);
                }

                reconcileLocalRecording(desiredRecordingMode);
            }
        } catch (ApiClient.ApiException error) {
            if (error.status == 401 || error.status == 404) {
                failAndStop(
                    "Asocierea sau armarea a expirat. Deschide aplicația din nou."
                );
            } else {
                publishTransientError(error.getMessage());
            }
        } catch (Exception error) {
            publishTransientError(error.getMessage());
        }
    }

    private void startCapture() {
        if (!"off".equals(actualRecordingMode)) {
            stopLocalRecording(true);
        }

        captureStarting = true;
        state = "starting";
        errorMessage = null;
        publishState(
            "starting",
            "Comandă primită · pornesc camera și microfonul."
        );

        try {
            initializeWebRtc();
            acquireWifiLock();
            createLocalTracks();
            createPeerConnection();

            peerConnection.addTrack(
                videoTrack,
                Collections.singletonList("cloud-monitor")
            );
            peerConnection.addTrack(
                audioTrack,
                Collections.singletonList("cloud-monitor")
            );

            SessionDescription offer = createOffer();
            setLocalDescription(offer);
            waitForIceGathering();

            SessionDescription localDescription =
                peerConnection.getLocalDescription();

            if (localDescription == null) {
                throw new IllegalStateException("Oferta WebRTC lipsește");
            }

            monitorSessionId = UUID.randomUUID().toString();
            api.sendOffer(
                monitorSessionId,
                "offer",
                localDescription.description
            );
            answerApplied = false;
            lastHeartbeatAt = 0;
            state = "live";
            publishState(
                "live",
                "Camera și microfonul sunt active. Se așteaptă PC-ul."
            );
        } catch (Throwable error) {
            if (error instanceof VirtualMachineError) {
                throw (VirtualMachineError) error;
            }

            Log.e(LOG_TAG, "Monitor capture failed", error);

            try {
                cleanupCapture();
            } catch (Throwable cleanupError) {
                Log.e(LOG_TAG, "Monitor cleanup failed", cleanupError);
            }

            state = "error";
            errorMessage = safeMessage(error);
            publishState("error", "Pornirea a eșuat: " + errorMessage);
        } finally {
            captureStarting = false;
        }
    }

    private void maintainLiveSession() throws Exception {
        if (monitorSessionId == null) {
            return;
        }

        long now = System.currentTimeMillis();

        if (now - lastHeartbeatAt >= 4000) {
            lastHeartbeatAt = now;

            if (!api.heartbeat(monitorSessionId)) {
                stopCapture(false);
                return;
            }
        }

        if (answerApplied || peerConnection == null) {
            return;
        }

        JSONObject answerStatus = api.getAnswer(monitorSessionId);

        if (!answerStatus.optBoolean("active", false)) {
            stopCapture(false);
            return;
        }

        JSONObject answer = answerStatus.optJSONObject("answer");

        if (answer == null) {
            return;
        }

        SessionDescription remoteDescription = new SessionDescription(
            SessionDescription.Type.ANSWER,
            answer.getString("sdp")
        );
        setRemoteDescription(remoteDescription);
        answerApplied = true;
        publishState("live", "PC-ul s-a conectat la transmisie.");
    }

    private void stopCapture(boolean notifyServer) {
        String sessionId = monitorSessionId;
        cleanupCapture();
        state = "armed";
        errorMessage = null;
        publishState(
            "armed",
            "Camera și microfonul sunt oprite. Sursa rămâne armată."
        );

        if (notifyServer && sessionId != null && api != null) {
            try {
                api.stopSession(sessionId);
            } catch (Exception ignored) {
                // The session may already have been removed by the viewer.
            }
        }
    }

    private void reconcileLocalRecording(String requestedMode) {
        String safeMode = "audio".equals(requestedMode)
            || "video".equals(requestedMode)
            ? requestedMode
            : "off";

        boolean recordingCameraChanged = (
            "video".equals(safeMode)
            && "video".equals(actualRecordingMode)
            && !recordingCameraFacing.equals(activeRecordingCameraFacing)
        );

        if (
            safeMode.equals(actualRecordingMode)
            && !recordingCameraChanged
        ) {
            return;
        }

        if (!"off".equals(actualRecordingMode)) {
            stopLocalRecording(true);
        }

        if (!"off".equals(safeMode)) {
            startLocalRecording(safeMode);
        }
    }

    private void startLocalRecording(String mode) {
        try {
            File queueDirectory = recordingQueueDirectory();
            discardInterruptedSegments(queueDirectory);
            segmentStartedAt = System.currentTimeMillis();
            activeRecordingCameraFacing = recordingCameraFacing;
            segmentFile = new File(
                queueDirectory,
                "current-" + mode + ".part"
            );
            segmentFile.delete();
            segmentRecorder = createMediaRecorder();

            if ("video".equals(mode)) {
                configureVideoRecorder(segmentRecorder);
            } else {
                configureAudioRecorder(segmentRecorder);
            }

            segmentRecorder.setOutputFile(segmentFile.getAbsolutePath());
            segmentRecorder.prepare();
            segmentRecorder.start();
            actualRecordingMode = mode;
            MonitorStateStore.updateRecordingMode(this, mode);
            scheduleRecordingRotation();
            publishState(
                "armed",
                "audio".equals(mode)
                    ? "REC · se înregistrează numai sunetul"
                    : "REC · se înregistrează video și sunet la 480p"
            );
        } catch (Exception error) {
            Log.e(LOG_TAG, "Local recording could not start", error);
            releaseSegmentRecorder();
            releaseSegmentCamera();

            if (segmentFile != null) {
                segmentFile.delete();
            }

            segmentFile = null;
            actualRecordingMode = "off";
            MonitorStateStore.updateRecordingMode(this, "off");
            publishTransientError(
                "Înregistrarea nu a pornit: " + safeMessage(error)
            );
        }
    }

    private MediaRecorder createMediaRecorder() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            return new MediaRecorder(this);
        }

        return new MediaRecorder();
    }

    private void configureAudioRecorder(MediaRecorder recorder) {
        recorder.setAudioSource(MediaRecorder.AudioSource.MIC);
        recorder.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4);
        recorder.setAudioEncoder(MediaRecorder.AudioEncoder.AAC);
        recorder.setAudioChannels(1);
        recorder.setAudioSamplingRate(16000);
        recorder.setAudioEncodingBitRate(24000);
    }

    private void configureVideoRecorder(MediaRecorder recorder)
        throws Exception {
        int cameraId = findRecordingCameraId(activeRecordingCameraFacing);
        Camera.CameraInfo cameraInfo = new Camera.CameraInfo();
        Camera.getCameraInfo(cameraId, cameraInfo);
        segmentCamera = Camera.open(cameraId);
        segmentPreviewTexture = new SurfaceTexture(4102);
        segmentCamera.setPreviewTexture(segmentPreviewTexture);
        segmentCamera.startPreview();
        segmentCamera.unlock();

        recorder.setCamera(segmentCamera);
        recorder.setAudioSource(MediaRecorder.AudioSource.MIC);
        recorder.setVideoSource(MediaRecorder.VideoSource.CAMERA);
        recorder.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4);
        recorder.setAudioEncoder(MediaRecorder.AudioEncoder.AAC);
        recorder.setVideoEncoder(MediaRecorder.VideoEncoder.H264);
        recorder.setAudioChannels(1);
        recorder.setAudioSamplingRate(16000);
        recorder.setAudioEncodingBitRate(24000);
        recorder.setVideoSize(640, 480);
        recorder.setVideoFrameRate(15);
        recorder.setVideoEncodingBitRate(600000);
        recorder.setOrientationHint(
            cameraInfo.facing == Camera.CameraInfo.CAMERA_FACING_FRONT
                ? 270
                : 90
        );
    }

    private int findRecordingCameraId(String requestedFacing) {
        int requested = "user".equals(requestedFacing)
            ? Camera.CameraInfo.CAMERA_FACING_FRONT
            : Camera.CameraInfo.CAMERA_FACING_BACK;
        Camera.CameraInfo info = new Camera.CameraInfo();

        for (int cameraId = 0; cameraId < Camera.getNumberOfCameras(); cameraId++) {
            Camera.getCameraInfo(cameraId, info);

            if (info.facing == requested) {
                return cameraId;
            }
        }

        if (Camera.getNumberOfCameras() == 0) {
            throw new IllegalStateException("Telefonul nu are cameră disponibilă");
        }

        return 0;
    }

    private void scheduleRecordingRotation() {
        if (recordingRotation != null) {
            recordingRotation.cancel(false);
        }

        recordingRotation = executor.schedule(
            this::rotateLocalRecording,
            RECORDING_SEGMENT_MILLIS,
            TimeUnit.MILLISECONDS
        );
    }

    private void rotateLocalRecording() {
        String mode = actualRecordingMode;
        stopLocalRecording(true);

        if (
            armed
            && "armed".equals(state)
            && mode.equals(desiredRecordingMode)
        ) {
            startLocalRecording(mode);
        }
    }

    private void stopLocalRecording(boolean uploadCompletedSegment) {
        if (recordingRotation != null) {
            recordingRotation.cancel(false);
            recordingRotation = null;
        }

        String completedMode = actualRecordingMode;
        long endedAt = System.currentTimeMillis();
        boolean completed = false;

        if (segmentRecorder != null) {
            try {
                segmentRecorder.stop();
                completed = true;
            } catch (RuntimeException error) {
                Log.w(LOG_TAG, "Recording segment was too short", error);
            }
        }

        releaseSegmentRecorder();
        releaseSegmentCamera();
        actualRecordingMode = "off";
        MonitorStateStore.updateRecordingMode(this, "off");

        File completedFile = null;

        if (segmentFile != null && completed && segmentFile.length() > 0) {
            String extension = "audio".equals(completedMode) ? ".m4a" : ".mp4";
            String modeToken = "video".equals(completedMode)
                ? "video-" + activeRecordingCameraFacing
                : "audio";
            completedFile = new File(
                segmentFile.getParentFile(),
                modeToken + "_" + segmentStartedAt + "_" + endedAt
                    + extension
            );

            if (!segmentFile.renameTo(completedFile)) {
                Log.e(LOG_TAG, "Could not finalize recording segment");
                completedFile = null;
            }
        }

        if (segmentFile != null && segmentFile.exists()) {
            segmentFile.delete();
        }

        segmentFile = null;

        if (uploadCompletedSegment && completedFile != null) {
            uploadRecordingFile(completedFile);
        }

        if (armed && "armed".equals(state)) {
            publishState(
                "armed",
                "Camera și microfonul sunt oprite. Sursa rămâne armată."
            );
        }
    }

    private void releaseSegmentRecorder() {
        if (segmentRecorder == null) {
            return;
        }

        try {
            segmentRecorder.reset();
        } catch (RuntimeException ignored) {
            // Release still needs to run after an incomplete recording.
        }

        segmentRecorder.release();
        segmentRecorder = null;
    }

    private void releaseSegmentCamera() {
        if (segmentCamera != null) {
            try {
                segmentCamera.lock();
            } catch (RuntimeException ignored) {
                // The recorder may already have returned camera ownership.
            }

            segmentCamera.release();
            segmentCamera = null;
        }

        if (segmentPreviewTexture != null) {
            segmentPreviewTexture.release();
            segmentPreviewTexture = null;
        }
    }

    private File recordingQueueDirectory() {
        File directory = new File(getFilesDir(), "recording-queue");

        if (!directory.isDirectory() && !directory.mkdirs()) {
            throw new IllegalStateException(
                "Spațiul temporar pentru înregistrări nu poate fi creat"
            );
        }

        return directory;
    }

    private void discardInterruptedSegments(File directory) {
        File[] files = directory.listFiles(
            (ignored, name) -> name.endsWith(".part")
        );

        if (files == null) {
            return;
        }

        for (File file : files) {
            file.delete();
        }
    }

    private void uploadPendingRecordings() {
        File directory;

        try {
            directory = recordingQueueDirectory();
        } catch (RuntimeException error) {
            Log.e(LOG_TAG, "Recording queue is unavailable", error);
            return;
        }

        discardInterruptedSegments(directory);
        File[] files = directory.listFiles(
            (ignored, name) -> name.endsWith(".m4a") || name.endsWith(".mp4")
        );

        if (files == null) {
            return;
        }

        for (File file : files) {
            uploadRecordingFile(file);
        }
    }

    private void uploadRecordingFile(File file) {
        String[] parts = file.getName().split("[_\\.]");

        if (parts.length != 4) {
            file.delete();
            return;
        }

        try {
            String modeToken = parts[0];
            String mode = modeToken.startsWith("video-")
                ? "video"
                : "audio";
            String recordedCameraFacing = modeToken.endsWith("-user")
                ? "user"
                : "environment";
            long startedAt = Long.parseLong(parts[1]);
            long endedAt = Long.parseLong(parts[2]);
            api.uploadRecording(
                file,
                mode,
                "video".equals(mode) ? recordedCameraFacing : null,
                startedAt,
                endedAt
            );
            file.delete();
        } catch (Exception error) {
            Log.e(LOG_TAG, "Recording upload will be retried", error);
        }
    }

    private void disarmAndStop() {
        MonitorStateStore.disarm(this);
        armed = false;
        desiredRecordingMode = "off";
        stopLocalRecording(true);
        cleanupCapture();

        if (api != null && sourceId != null) {
            try {
                api.disarm(sourceId);
            } catch (Exception ignored) {
                // Local stop remains authoritative for the device.
            }
        }

        releaseLocks();
        publishState("stopped", "Sursa a fost dezarmată.");
        stopForeground(STOP_FOREGROUND_REMOVE);
        stopSelf();
    }

    private void initializeWebRtc() {
        if (peerConnectionFactory != null) {
            return;
        }

        PeerConnectionFactory.initialize(
            PeerConnectionFactory.InitializationOptions
                .builder(getApplicationContext())
                .createInitializationOptions()
        );
        eglBase = EglBase.create();

        PeerConnectionFactory.Options options =
            new PeerConnectionFactory.Options();

        // The WebRTC network monitor aborts inside native code on this
        // Android/Termux host. Signalling already travels through our HTTPS
        // API, so disable continuous network-change monitoring while keeping
        // the initial ICE interface discovery used by the peer connection.
        options.disableNetworkMonitor = true;

        peerConnectionFactory = PeerConnectionFactory.builder()
            .setOptions(options)
            .setVideoEncoderFactory(
                new DefaultVideoEncoderFactory(
                    eglBase.getEglBaseContext(),
                    true,
                    true
                )
            )
            .setVideoDecoderFactory(
                new DefaultVideoDecoderFactory(
                    eglBase.getEglBaseContext()
                )
            )
            .createPeerConnectionFactory();
    }

    private void createLocalTracks() throws Exception {
        // Camera1 is intentionally used for stability on older Samsung devices.
        // Some vendor Camera2 implementations can terminate the capture thread.
        CameraEnumerator enumerator = new Camera1Enumerator(true);
        String selectedDevice = selectCamera(enumerator, cameraFacing);

        if (selectedDevice == null) {
            throw new IllegalStateException("Nu a fost găsită camera solicitată");
        }

        cameraCapturer = enumerator.createCapturer(selectedDevice, null);

        if (cameraCapturer == null) {
            throw new IllegalStateException("Camera nu poate fi deschisă");
        }

        surfaceTextureHelper = SurfaceTextureHelper.create(
            "CloudMonitorCapture",
            eglBase.getEglBaseContext()
        );
        videoSource = peerConnectionFactory.createVideoSource(false);
        cameraCapturer.initialize(
            surfaceTextureHelper,
            this,
            videoSource.getCapturerObserver()
        );
        cameraCapturer.startCapture(640, 480, 15);
        videoTrack = peerConnectionFactory.createVideoTrack(
            "cloud-monitor-video",
            videoSource
        );

        audioSource = peerConnectionFactory.createAudioSource(
            new MediaConstraints()
        );
        audioTrack = peerConnectionFactory.createAudioTrack(
            "cloud-monitor-audio",
            audioSource
        );
    }

    private String selectCamera(
        CameraEnumerator enumerator,
        String requestedFacing
    ) {
        for (String deviceName : enumerator.getDeviceNames()) {
            boolean matches = "user".equals(requestedFacing)
                ? enumerator.isFrontFacing(deviceName)
                : enumerator.isBackFacing(deviceName);

            if (matches) {
                return deviceName;
            }
        }

        String[] devices = enumerator.getDeviceNames();
        return devices.length == 0 ? null : devices[0];
    }

    private void createPeerConnection() {
        PeerConnection.RTCConfiguration configuration =
            new PeerConnection.RTCConfiguration(Collections.emptyList());
        configuration.sdpSemantics = PeerConnection.SdpSemantics.UNIFIED_PLAN;
        iceGatheringLatch = new CountDownLatch(1);
        peerConnection = peerConnectionFactory.createPeerConnection(
            configuration,
            new PeerConnection.Observer() {
                @Override
                public void onSignalingChange(
                    PeerConnection.SignalingState signalingState
                ) {}

                @Override
                public void onIceConnectionChange(
                    PeerConnection.IceConnectionState iceConnectionState
                ) {}

                @Override
                public void onIceConnectionReceivingChange(boolean receiving) {}

                @Override
                public void onIceGatheringChange(
                    PeerConnection.IceGatheringState gatheringState
                ) {
                    if (
                        gatheringState
                            == PeerConnection.IceGatheringState.COMPLETE
                        && iceGatheringLatch != null
                    ) {
                        iceGatheringLatch.countDown();
                    }
                }

                @Override
                public void onIceCandidate(IceCandidate iceCandidate) {}

                @Override
                public void onIceCandidatesRemoved(IceCandidate[] candidates) {}

                @Override
                public void onAddStream(MediaStream mediaStream) {}

                @Override
                public void onRemoveStream(MediaStream mediaStream) {}

                @Override
                public void onDataChannel(DataChannel dataChannel) {}

                @Override
                public void onRenegotiationNeeded() {}

                @Override
                public void onAddTrack(
                    RtpReceiver receiver,
                    MediaStream[] mediaStreams
                ) {}
            }
        );

        if (peerConnection == null) {
            throw new IllegalStateException("Conexiunea WebRTC nu poate fi creată");
        }
    }

    private SessionDescription createOffer() throws Exception {
        AtomicReference<SessionDescription> result = new AtomicReference<>();
        AtomicReference<String> failure = new AtomicReference<>();
        CountDownLatch latch = new CountDownLatch(1);
        peerConnection.createOffer(
            new SimpleSdpObserver() {
                @Override
                public void onCreateSuccess(SessionDescription description) {
                    result.set(description);
                    latch.countDown();
                }

                @Override
                public void onCreateFailure(String error) {
                    failure.set(error);
                    latch.countDown();
                }
            },
            new MediaConstraints()
        );
        await(latch, "Crearea ofertei WebRTC a expirat");

        if (result.get() == null) {
            throw new IllegalStateException(
                failure.get() == null ? "Oferta WebRTC a eșuat" : failure.get()
            );
        }

        return result.get();
    }

    private void setLocalDescription(SessionDescription description)
        throws Exception {
        CountDownLatch latch = new CountDownLatch(1);
        AtomicReference<String> failure = new AtomicReference<>();
        peerConnection.setLocalDescription(
            new SetSdpObserver(latch, failure),
            description
        );
        await(latch, "Setarea ofertei WebRTC a expirat");

        if (failure.get() != null) {
            throw new IllegalStateException(failure.get());
        }
    }

    private void setRemoteDescription(SessionDescription description)
        throws Exception {
        CountDownLatch latch = new CountDownLatch(1);
        AtomicReference<String> failure = new AtomicReference<>();
        peerConnection.setRemoteDescription(
            new SetSdpObserver(latch, failure),
            description
        );
        await(latch, "Aplicarea răspunsului WebRTC a expirat");

        if (failure.get() != null) {
            throw new IllegalStateException(failure.get());
        }
    }

    private void waitForIceGathering() throws InterruptedException {
        iceGatheringLatch.await(8, TimeUnit.SECONDS);
    }

    private void await(CountDownLatch latch, String timeoutMessage)
        throws Exception {
        if (!latch.await(10, TimeUnit.SECONDS)) {
            throw new IllegalStateException(timeoutMessage);
        }
    }

    private void cleanupCapture() {
        monitorSessionId = null;
        answerApplied = false;
        iceGatheringLatch = null;

        if (peerConnection != null) {
            peerConnection.close();
            peerConnection.dispose();
            peerConnection = null;
        }

        if (cameraCapturer != null) {
            try {
                cameraCapturer.stopCapture();
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
            }
            cameraCapturer.dispose();
            cameraCapturer = null;
        }

        if (videoTrack != null) {
            videoTrack.dispose();
            videoTrack = null;
        }

        if (audioTrack != null) {
            audioTrack.dispose();
            audioTrack = null;
        }

        if (videoSource != null) {
            videoSource.dispose();
            videoSource = null;
        }

        if (audioSource != null) {
            audioSource.dispose();
            audioSource = null;
        }

        if (surfaceTextureHelper != null) {
            surfaceTextureHelper.dispose();
            surfaceTextureHelper = null;
        }

        releaseWifiLock();
    }

    private void acquireWakeLock() {
        PowerManager powerManager =
            (PowerManager) getSystemService(POWER_SERVICE);
        wakeLock = powerManager.newWakeLock(
            PowerManager.PARTIAL_WAKE_LOCK,
            "CloudInBuzunar:Monitor"
        );
        wakeLock.setReferenceCounted(false);
        wakeLock.acquire();
    }

    private void acquireWifiLock() {
        WifiManager wifiManager =
            (WifiManager) getApplicationContext().getSystemService(WIFI_SERVICE);
        wifiLock = wifiManager.createWifiLock(
            WifiManager.WIFI_MODE_FULL_HIGH_PERF,
            "CloudInBuzunar:LiveMonitor"
        );
        wifiLock.setReferenceCounted(false);
        wifiLock.acquire();
    }

    private void releaseLocks() {
        releaseWifiLock();

        if (wakeLock != null && wakeLock.isHeld()) {
            wakeLock.release();
        }

        wakeLock = null;
    }

    private void releaseWifiLock() {
        if (wifiLock != null && wifiLock.isHeld()) {
            wifiLock.release();
        }

        wifiLock = null;
    }

    private void publishTransientError(String detail) {
        currentMessage = "Server indisponibil temporar: " + detail;
        broadcastState(state, currentMessage);
    }

    private void failAndStop(String message) {
        Log.e(LOG_TAG, message);
        MonitorStateStore.disarm(this);
        state = "error";
        errorMessage = message;
        publishState("error", message);
        armed = false;
        desiredRecordingMode = "off";
        stopLocalRecording(false);
        cleanupCapture();
        releaseLocks();
        stopForeground(STOP_FOREGROUND_REMOVE);
        stopSelf();
    }

    private String safeMessage(Throwable error) {
        String message = error.getMessage();
        return message == null ? error.getClass().getSimpleName() : message;
    }

    private void publishState(String newState, String message) {
        currentState = newState;
        currentMessage = message;
        updateNotification(newState, message);
        broadcastState(newState, message);
    }

    private void broadcastState(String newState, String message) {
        Intent statusIntent = new Intent(STATUS_ACTION)
            .setPackage(getPackageName())
            .putExtra(EXTRA_STATE, newState)
            .putExtra(EXTRA_MESSAGE, message);
        sendBroadcast(statusIntent);
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return;
        }

        NotificationChannel channel = new NotificationChannel(
            CHANNEL_ID,
            "Monitor cameră și microfon",
            NotificationManager.IMPORTANCE_LOW
        );
        channel.setDescription(
            "Arată când monitorul este armat sau transmite live."
        );
        getSystemService(NotificationManager.class)
            .createNotificationChannel(channel);
    }

    private Notification buildNotification(String text) {
        PendingIntent openIntent = PendingIntent.getActivity(
            this,
            0,
            new Intent(this, MainActivity.class),
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );
        PendingIntent stopIntent = PendingIntent.getService(
            this,
            1,
            new Intent(this, MonitorService.class).setAction(ACTION_DISARM),
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );

        return new Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.presence_video_online)
            .setContentTitle("CloudInBuzunar Monitor")
            .setContentText(text)
            .setContentIntent(openIntent)
            .setOngoing(true)
            .setCategory(Notification.CATEGORY_SERVICE)
            .addAction(
                android.R.drawable.ic_menu_close_clear_cancel,
                "Dezarmează",
                stopIntent
            )
            .build();
    }

    private void startAsForeground(String text) {
        Notification notification = buildNotification(text);

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA
                    | ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
            );
        } else {
            startForeground(NOTIFICATION_ID, notification);
        }
    }

    private void updateNotification(String newState, String message) {
        if ("stopped".equals(newState)) {
            return;
        }

        String text = "live".equals(newState)
            ? "LIVE · camera și microfonul sunt active"
            : message;
        getSystemService(NotificationManager.class).notify(
            NOTIFICATION_ID,
            buildNotification(text)
        );
    }

    private abstract static class SimpleSdpObserver implements SdpObserver {
        @Override
        public void onSetSuccess() {}

        @Override
        public void onCreateFailure(String error) {}

        @Override
        public void onSetFailure(String error) {}
    }

    private static final class SetSdpObserver extends SimpleSdpObserver {
        private final CountDownLatch latch;
        private final AtomicReference<String> failure;

        SetSdpObserver(
            CountDownLatch latch,
            AtomicReference<String> failure
        ) {
            this.latch = latch;
            this.failure = failure;
        }

        @Override
        public void onCreateSuccess(SessionDescription description) {}

        @Override
        public void onSetSuccess() {
            latch.countDown();
        }

        @Override
        public void onSetFailure(String error) {
            failure.set(error);
            latch.countDown();
        }
    }
}
