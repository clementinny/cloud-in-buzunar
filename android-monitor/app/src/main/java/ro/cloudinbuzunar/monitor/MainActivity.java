package ro.cloudinbuzunar.monitor;

import android.Manifest;
import android.app.Activity;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.view.View;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.Spinner;
import android.widget.TextView;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity {
    private static final int PERMISSION_REQUEST = 200;
    private static final int PERMISSION_ACTION_NONE = 0;
    private static final int PERMISSION_ACTION_ARM = 1;
    private static final int PERMISSION_ACTION_SERVER_WATCH = 2;

    private final ExecutorService executor = Executors.newSingleThreadExecutor();

    private LinearLayout pairingPanel;
    private LinearLayout controlPanel;
    private EditText pairingCodeInput;
    private Button pairButton;
    private Button armButton;
    private Button disarmButton;
    private Button serverWatchStartButton;
    private Button serverWatchStopButton;
    private Spinner cameraFacingSpinner;
    private Spinner serverPollIntervalSpinner;
    private Spinner serverFailureThresholdSpinner;
    private EditText serverUrlInput;
    private TextView statusText;
    private TextView messageText;
    private TextView serverWatchStatus;
    private int pendingPermissionAction = PERMISSION_ACTION_NONE;

    private final BroadcastReceiver statusReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            if (!MonitorService.STATUS_ACTION.equals(intent.getAction())) {
                return;
            }

            String state = intent.getStringExtra(MonitorService.EXTRA_STATE);
            String message = intent.getStringExtra(MonitorService.EXTRA_MESSAGE);
            updateServiceState(state == null ? "stopped" : state, message);
        }
    };

    private final BroadcastReceiver serverWatchStatusReceiver =
        new BroadcastReceiver() {
            @Override
            public void onReceive(Context context, Intent intent) {
                if (
                    !ServerWatchService.STATUS_ACTION.equals(
                        intent.getAction()
                    )
                ) {
                    return;
                }

                updateServerWatchState(
                    intent.getStringExtra(ServerWatchService.EXTRA_STATE),
                    intent.getStringExtra(ServerWatchService.EXTRA_MESSAGE)
                );
            }
        };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        pairingPanel = findViewById(R.id.pairingPanel);
        controlPanel = findViewById(R.id.controlPanel);
        pairingCodeInput = findViewById(R.id.pairingCodeInput);
        pairButton = findViewById(R.id.pairButton);
        armButton = findViewById(R.id.armButton);
        disarmButton = findViewById(R.id.disarmButton);
        serverWatchStartButton = findViewById(
            R.id.serverWatchStartButton
        );
        serverWatchStopButton = findViewById(
            R.id.serverWatchStopButton
        );
        cameraFacingSpinner = findViewById(R.id.cameraFacingSpinner);
        serverPollIntervalSpinner = findViewById(
            R.id.serverPollIntervalSpinner
        );
        serverFailureThresholdSpinner = findViewById(
            R.id.serverFailureThresholdSpinner
        );
        serverUrlInput = findViewById(R.id.serverUrlInput);
        statusText = findViewById(R.id.deviceStatus);
        messageText = findViewById(R.id.messageText);
        serverWatchStatus = findViewById(R.id.serverWatchStatus);

        String previousCrash = CrashReporter.consume(this);

        if (previousCrash != null) {
            messageText.setText(
                "Aplicația s-a oprit anterior: " + previousCrash
            );
        }

        ArrayAdapter<String> cameraAdapter = new ArrayAdapter<>(
            this,
            android.R.layout.simple_spinner_dropdown_item,
            new String[]{"Camera principală", "Camera frontală"}
        );
        cameraFacingSpinner.setAdapter(cameraAdapter);
        cameraFacingSpinner.setSelection(
            "user".equals(MonitorStateStore.cameraFacing(this)) ? 1 : 0
        );
        configureServerWatchControls();

        pairButton.setOnClickListener(view -> pairDevice());
        armButton.setOnClickListener(view -> requestPermissionsAndArm());
        disarmButton.setOnClickListener(view -> disarm());
        serverWatchStartButton.setOnClickListener(
            view -> requestNotificationAndStartServerWatch()
        );
        serverWatchStopButton.setOnClickListener(
            view -> stopServerWatch()
        );

        showPairingState();
    }

    @Override
    protected void onStart() {
        super.onStart();
        IntentFilter filter = new IntentFilter(MonitorService.STATUS_ACTION);

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(statusReceiver, filter, Context.RECEIVER_NOT_EXPORTED);
        } else {
            registerReceiver(statusReceiver, filter);
        }

        IntentFilter serverFilter = new IntentFilter(
            ServerWatchService.STATUS_ACTION
        );

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(
                serverWatchStatusReceiver,
                serverFilter,
                Context.RECEIVER_NOT_EXPORTED
            );
        } else {
            registerReceiver(serverWatchStatusReceiver, serverFilter);
        }

        updateServiceState(
            MonitorService.currentState,
            MonitorService.currentMessage
        );
        updateServerWatchState(
            ServerWatchService.currentState,
            ServerWatchService.currentMessage
        );

        if (ServerMonitorSettingsStore.monitoringEnabled(this)) {
            startForegroundService(
                new Intent(this, ServerWatchService.class)
                    .setAction(ServerWatchService.ACTION_START)
            );
        }
    }

    @Override
    protected void onStop() {
        unregisterReceiver(statusReceiver);
        unregisterReceiver(serverWatchStatusReceiver);
        super.onStop();
    }

    @Override
    protected void onDestroy() {
        executor.shutdownNow();
        super.onDestroy();
    }

    private void showPairingState() {
        boolean paired = TokenStore.read(this) != null;
        pairingPanel.setVisibility(paired ? View.GONE : View.VISIBLE);
        controlPanel.setVisibility(paired ? View.VISIBLE : View.GONE);

        if (paired) {
            statusText.setText("Aplicație asociată · sursa este dezarmată");
        }
    }

    private void pairDevice() {
        String code = pairingCodeInput.getText().toString().trim();

        if (code.isEmpty()) {
            messageText.setText("Introdu codul generat în dashboard.");
            return;
        }

        pairButton.setEnabled(false);
        messageText.setText("Se asociază aplicația...");
        String deviceName = Build.MANUFACTURER + " " + Build.MODEL;
        final String serverUrl;

        try {
            serverUrl = ApiClient.normalizeServerUrl(
                serverUrlInput.getText().toString()
            );
        } catch (IllegalArgumentException error) {
            pairButton.setEnabled(true);
            messageText.setText(error.getMessage());
            return;
        }

        executor.execute(() -> {
            try {
                String token = ApiClient.pair(
                    serverUrl,
                    code,
                    deviceName.trim()
                );
                TokenStore.save(this, token);
                ServerMonitorSettingsStore.setServerUrl(this, serverUrl);

                runOnUiThread(() -> {
                    pairingCodeInput.setText("");
                    pairButton.setEnabled(true);
                    messageText.setText(
                        "Asociere reușită. Acum poți arma monitorul."
                    );
                    showPairingState();
                });
            } catch (Exception error) {
                runOnUiThread(() -> {
                    pairButton.setEnabled(true);
                    messageText.setText(
                        "Asocierea a eșuat: " + error.getMessage()
                    );
                });
            }
        });
    }

    private void requestPermissionsAndArm() {
        pendingPermissionAction = PERMISSION_ACTION_ARM;
        List<String> missing = new ArrayList<>();

        if (checkSelfPermission(Manifest.permission.CAMERA)
            != PackageManager.PERMISSION_GRANTED) {
            missing.add(Manifest.permission.CAMERA);
        }

        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED) {
            missing.add(Manifest.permission.RECORD_AUDIO);
        }

        if (
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
            && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED
        ) {
            missing.add(Manifest.permission.POST_NOTIFICATIONS);
        }

        if (!missing.isEmpty()) {
            requestPermissions(
                missing.toArray(new String[0]),
                PERMISSION_REQUEST
            );
            return;
        }

        pendingPermissionAction = PERMISSION_ACTION_NONE;
        arm();
    }

    private void requestNotificationAndStartServerWatch() {
        pendingPermissionAction = PERMISSION_ACTION_SERVER_WATCH;

        if (
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
            && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(
                new String[]{Manifest.permission.POST_NOTIFICATIONS},
                PERMISSION_REQUEST
            );
            return;
        }

        pendingPermissionAction = PERMISSION_ACTION_NONE;
        startServerWatch();
    }

    @Override
    public void onRequestPermissionsResult(
        int requestCode,
        String[] permissions,
        int[] grantResults
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);

        if (requestCode != PERMISSION_REQUEST) {
            return;
        }

        for (int result : grantResults) {
            if (result != PackageManager.PERMISSION_GRANTED) {
                messageText.setText(
                    "Camera, microfonul și notificările trebuie permise."
                );
                pendingPermissionAction = PERMISSION_ACTION_NONE;
                return;
            }
        }

        int action = pendingPermissionAction;
        pendingPermissionAction = PERMISSION_ACTION_NONE;

        if (action == PERMISSION_ACTION_SERVER_WATCH) {
            startServerWatch();
        } else if (action == PERMISSION_ACTION_ARM) {
            arm();
        }
    }

    private void arm() {
        String token = TokenStore.read(this);

        if (token == null) {
            showPairingState();
            return;
        }

        String facing = cameraFacingSpinner.getSelectedItemPosition() == 0
            ? "environment"
            : "user";
        Intent serviceIntent = new Intent(this, MonitorService.class)
            .setAction(MonitorService.ACTION_ARM)
            .putExtra(MonitorService.EXTRA_CAMERA_FACING, facing);
        startForegroundService(serviceIntent);
        startServerWatch();
        updateServiceState("starting", "Se pornește serviciul...");
    }

    private void configureServerWatchControls() {
        serverUrlInput.setText(
            ServerMonitorSettingsStore.serverUrl(this)
        );
        ArrayAdapter<String> intervalAdapter = new ArrayAdapter<>(
            this,
            android.R.layout.simple_spinner_dropdown_item,
            new String[]{"30 secunde", "60 secunde", "2 minute"}
        );
        serverPollIntervalSpinner.setAdapter(intervalAdapter);
        int interval =
            ServerMonitorSettingsStore.pollIntervalSeconds(this);
        serverPollIntervalSpinner.setSelection(
            interval == 30 ? 0 : interval == 120 ? 2 : 1
        );

        ArrayAdapter<String> thresholdAdapter = new ArrayAdapter<>(
            this,
            android.R.layout.simple_spinner_dropdown_item,
            new String[]{"2 verificări", "3 verificări", "5 verificări"}
        );
        serverFailureThresholdSpinner.setAdapter(thresholdAdapter);
        int threshold =
            ServerMonitorSettingsStore.failureThreshold(this);
        serverFailureThresholdSpinner.setSelection(
            threshold == 2 ? 0 : threshold == 5 ? 2 : 1
        );
    }

    private void startServerWatch() {
        final String serverUrl;

        try {
            serverUrl = ApiClient.normalizeServerUrl(
                serverUrlInput.getText().toString()
            );
        } catch (IllegalArgumentException error) {
            messageText.setText(error.getMessage());
            return;
        }

        int intervalPosition =
            serverPollIntervalSpinner.getSelectedItemPosition();
        int interval = intervalPosition == 0
            ? 30
            : intervalPosition == 2 ? 120 : 60;
        int thresholdPosition =
            serverFailureThresholdSpinner.getSelectedItemPosition();
        int threshold = thresholdPosition == 0
            ? 2
            : thresholdPosition == 2 ? 5 : 3;
        ServerMonitorSettingsStore.setServerUrl(this, serverUrl);
        ServerMonitorSettingsStore.setPollIntervalSeconds(this, interval);
        ServerMonitorSettingsStore.setFailureThreshold(this, threshold);
        ServerMonitorSettingsStore.setMonitoringEnabled(this, true);
        startForegroundService(
            new Intent(this, ServerWatchService.class)
                .setAction(ServerWatchService.ACTION_START)
        );
        updateServerWatchState(
            "checking",
            "Se verifică serverul " + serverUrl
        );
    }

    private void stopServerWatch() {
        ServerMonitorSettingsStore.setMonitoringEnabled(this, false);
        startService(
            new Intent(this, ServerWatchService.class)
                .setAction(ServerWatchService.ACTION_STOP)
        );
        updateServerWatchState(
            "stopped",
            "Monitorizarea serverului este oprită."
        );
    }

    private void updateServerWatchState(String state, String message) {
        boolean enabled =
            ServerMonitorSettingsStore.monitoringEnabled(this);
        serverWatchStartButton.setEnabled(!enabled);
        serverWatchStopButton.setEnabled(enabled);
        serverUrlInput.setEnabled(!enabled);
        serverPollIntervalSpinner.setEnabled(!enabled);
        serverFailureThresholdSpinner.setEnabled(!enabled);

        String label;

        if ("online".equals(state)) {
            label = "Server online · alertele sunt active";
        } else if ("offline".equals(state)) {
            label = "SERVER INDISPONIBIL · verificările continuă";
        } else if ("checking".equals(state) || enabled) {
            label = "Se verifică serverul...";
        } else {
            label = "Alertele pentru server sunt oprite";
        }

        serverWatchStatus.setText(label);

        if (message != null && !message.isEmpty()) {
            messageText.setText(message);
        }
    }

    private void disarm() {
        Intent serviceIntent = new Intent(this, MonitorService.class)
            .setAction(MonitorService.ACTION_DISARM);
        startService(serviceIntent);
        updateServiceState("stopped", "Sursa a fost dezarmată.");
    }

    private void updateServiceState(String state, String message) {
        boolean running = !"stopped".equals(state);
        armButton.setEnabled(!running);
        disarmButton.setEnabled(running);
        cameraFacingSpinner.setEnabled(!running);

        String label;

        switch (state) {
            case "armed":
                label = "ARMAT · camera și microfonul sunt oprite";
                break;
            case "starting":
                label = "Camera și microfonul pornesc...";
                break;
            case "live":
                label = "LIVE · camera și microfonul sunt active";
                break;
            case "error":
                label = "Eroare de monitorizare";
                break;
            default:
                label = "Aplicație asociată · sursa este dezarmată";
                break;
        }

        statusText.setText(label);

        if (message != null && !message.isEmpty()) {
            messageText.setText(message);
        }
    }
}
