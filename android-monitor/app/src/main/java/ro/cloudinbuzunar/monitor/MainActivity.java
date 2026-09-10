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

    private final ExecutorService executor = Executors.newSingleThreadExecutor();

    private LinearLayout pairingPanel;
    private LinearLayout controlPanel;
    private EditText pairingCodeInput;
    private Button pairButton;
    private Button armButton;
    private Button disarmButton;
    private Spinner cameraFacingSpinner;
    private TextView statusText;
    private TextView messageText;

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
        cameraFacingSpinner = findViewById(R.id.cameraFacingSpinner);
        statusText = findViewById(R.id.deviceStatus);
        messageText = findViewById(R.id.messageText);

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

        pairButton.setOnClickListener(view -> pairDevice());
        armButton.setOnClickListener(view -> requestPermissionsAndArm());
        disarmButton.setOnClickListener(view -> disarm());

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

        updateServiceState(
            MonitorService.currentState,
            MonitorService.currentMessage
        );
    }

    @Override
    protected void onStop() {
        unregisterReceiver(statusReceiver);
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

        executor.execute(() -> {
            try {
                String token = ApiClient.pair(code, deviceName.trim());
                TokenStore.save(this, token);

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

        arm();
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
                return;
            }
        }

        arm();
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
        updateServiceState("starting", "Se pornește serviciul...");
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
