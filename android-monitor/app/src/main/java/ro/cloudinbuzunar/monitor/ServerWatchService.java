package ro.cloudinbuzunar.monitor;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;

public final class ServerWatchService extends Service {
    static final String ACTION_START =
        "ro.cloudinbuzunar.monitor.SERVER_WATCH_START";
    static final String ACTION_STOP =
        "ro.cloudinbuzunar.monitor.SERVER_WATCH_STOP";
    static final String STATUS_ACTION =
        "ro.cloudinbuzunar.monitor.SERVER_WATCH_STATUS";
    static final String EXTRA_STATE = "state";
    static final String EXTRA_MESSAGE = "message";

    private static final String LOG_TAG = "CloudServerWatch";
    private static final String SERVICE_CHANNEL_ID = "server_watch_service";
    private static final String ALERT_CHANNEL_ID = "server_alerts";
    private static final int SERVICE_NOTIFICATION_ID = 4201;
    private static final int SERVER_DOWN_NOTIFICATION_ID = 4202;
    private static final int SERVER_RECOVERED_NOTIFICATION_ID = 4203;
    private static final int MAX_ALERTS_PER_POLL = 25;

    static volatile String currentState = "stopped";
    static volatile String currentMessage = null;

    private final ScheduledExecutorService executor =
        Executors.newSingleThreadScheduledExecutor();
    private ScheduledFuture<?> pollingTask;
    private ServerHealthTracker healthTracker;
    private volatile String lastError;

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannels();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        String action = intent == null ? null : intent.getAction();

        if (ACTION_STOP.equals(action)) {
            ServerMonitorSettingsStore.setMonitoringEnabled(this, false);
            stopMonitoring();
            return START_NOT_STICKY;
        }

        if (
            !ACTION_START.equals(action)
            && !ServerMonitorSettingsStore.monitoringEnabled(this)
        ) {
            stopSelf();
            return START_NOT_STICKY;
        }

        ServerMonitorSettingsStore.setMonitoringEnabled(this, true);
        startAsForeground();
        schedulePolling();
        publishStatus(
            "checking",
            "Monitorizarea serverului este pornită."
        );
        return START_STICKY;
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void onDestroy() {
        if (pollingTask != null) {
            pollingTask.cancel(true);
        }

        executor.shutdownNow();
        currentState = "stopped";
        currentMessage = "Monitorizarea serverului este oprită.";
        broadcastStatus(currentState, currentMessage);
        super.onDestroy();
    }

    private void schedulePolling() {
        if (pollingTask != null) {
            pollingTask.cancel(false);
        }

        healthTracker = new ServerHealthTracker(
            ServerMonitorSettingsStore.failureThreshold(this),
            ServerMonitorSettingsStore.consecutiveFailures(this),
            ServerMonitorSettingsStore.serverOffline(this)
        );
        int interval =
            ServerMonitorSettingsStore.pollIntervalSeconds(this);
        pollingTask = executor.scheduleWithFixedDelay(
            this::pollSafely,
            0,
            interval,
            TimeUnit.SECONDS
        );
    }

    private void pollSafely() {
        PowerManager.WakeLock wakeLock = acquireShortWakeLock();

        try {
            String serverUrl =
                ServerMonitorSettingsStore.serverUrl(this);
            String token = TokenStore.read(this);
            ApiClient api = new ApiClient(token, serverUrl);
            JSONObject health = api.health();

            if (!"online".equalsIgnoreCase(health.optString("status"))) {
                throw new IllegalStateException(
                    "Răspunsul de sănătate nu confirmă starea online."
                );
            }

            ServerHealthTracker.Event event =
                healthTracker.recordSuccess();
            persistHealthState();

            if (event == ServerHealthTracker.Event.RECOVERED) {
                notifyRecovery(serverUrl);
            }

            lastError = null;
            publishStatus(
                "online",
                "Server online · verificare reușită."
            );

            if (token != null) {
                consumeAlertFeed(api);
            }
        } catch (Exception error) {
            lastError = safeMessage(error);
            ServerHealthTracker.Event event =
                healthTracker.recordFailure();
            persistHealthState();

            if (event == ServerHealthTracker.Event.DOWN) {
                notifyServerDown(lastError);
            }

            int failures = healthTracker.consecutiveFailures();
            int threshold =
                ServerMonitorSettingsStore.failureThreshold(this);
            String state = healthTracker.offline() ? "offline" : "checking";
            publishStatus(
                state,
                "Verificare eșuată "
                    + failures
                    + "/"
                    + threshold
                    + ": "
                    + lastError
            );
        } finally {
            if (wakeLock != null && wakeLock.isHeld()) {
                wakeLock.release();
            }
        }
    }

    private void consumeAlertFeed(ApiClient api) {
        try {
            JSONObject response = api.alertFeed(MAX_ALERTS_PER_POLL);
            JSONArray alerts = response.optJSONArray("alerts");

            if (alerts == null) {
                alerts = response.optJSONArray("events");
            }

            if (alerts == null || alerts.length() == 0) {
                return;
            }

            JSONArray acknowledged = new JSONArray();

            for (int index = 0; index < alerts.length(); index++) {
                JSONObject alert = alerts.optJSONObject(index);

                if (alert == null) {
                    continue;
                }

                Object id = alert.has("id")
                    ? alert.opt("id")
                    : alert.opt("event_id");

                if (id == null || JSONObject.NULL.equals(id)) {
                    continue;
                }

                notifyBackendAlert(alert, id);
                acknowledged.put(id);
            }

            if (acknowledged.length() > 0) {
                api.acknowledgeAlerts(acknowledged);
            }
        } catch (ApiClient.ApiException error) {
            if (error.status != 404) {
                Log.w(LOG_TAG, "Alert feed unavailable", error);
            }
        } catch (Exception error) {
            Log.w(LOG_TAG, "Could not consume alert feed", error);
        }
    }

    private void notifyBackendAlert(JSONObject alert, Object id) {
        String severity = alert.optString("severity", "warning");
        String title = alert.optString(
            "title",
            "critical".equalsIgnoreCase(severity)
                ? "Alertă critică CloudInBuzunar"
                : "Alertă CloudInBuzunar"
        );
        String message = alert.optString(
            "message",
            alert.optString("detail", "Serverul a raportat o problemă.")
        );
        int notificationId = 5000 + Math.floorMod(
            String.valueOf(id).hashCode(),
            1_000_000
        );
        notifyAlert(notificationId, title, message);
    }

    private void notifyServerDown(String detail) {
        notifyAlert(
            SERVER_DOWN_NOTIFICATION_ID,
            "Server CloudInBuzunar indisponibil",
            "Au eșuat verificările consecutive. Ultima eroare: " + detail
        );
    }

    private void notifyRecovery(String serverUrl) {
        getSystemService(NotificationManager.class).cancel(
            SERVER_DOWN_NOTIFICATION_ID
        );
        notifyAlert(
            SERVER_RECOVERED_NOTIFICATION_ID,
            "Server CloudInBuzunar din nou online",
            serverUrl + " răspunde din nou."
        );
    }

    private void notifyAlert(int id, String title, String message) {
        Notification notification = new Notification.Builder(
            this,
            ALERT_CHANNEL_ID
        )
            .setSmallIcon(android.R.drawable.stat_notify_error)
            .setContentTitle(title)
            .setContentText(message)
            .setStyle(new Notification.BigTextStyle().bigText(message))
            .setContentIntent(openApplicationIntent())
            .setAutoCancel(true)
            .setCategory(Notification.CATEGORY_ALARM)
            .build();
        getSystemService(NotificationManager.class).notify(id, notification);
    }

    private Notification buildServiceNotification() {
        String text = healthTracker != null && healthTracker.offline()
            ? "Server indisponibil · verificările continuă"
            : "Verific serverul periodic";
        PendingIntent stopIntent = PendingIntent.getService(
            this,
            1,
            new Intent(this, ServerWatchService.class).setAction(ACTION_STOP),
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );
        return new Notification.Builder(this, SERVICE_CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .setContentTitle("CloudInBuzunar · alerte server")
            .setContentText(text)
            .setContentIntent(openApplicationIntent())
            .setOngoing(true)
            .setCategory(Notification.CATEGORY_SERVICE)
            .addAction(
                android.R.drawable.ic_menu_close_clear_cancel,
                "Oprește alertele",
                stopIntent
            )
            .build();
    }

    private PendingIntent openApplicationIntent() {
        return PendingIntent.getActivity(
            this,
            0,
            new Intent(this, MainActivity.class),
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );
    }

    private void startAsForeground() {
        Notification notification = buildServiceNotification();

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(
                SERVICE_NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE
            );
        } else {
            startForeground(SERVICE_NOTIFICATION_ID, notification);
        }
    }

    private void stopMonitoring() {
        if (pollingTask != null) {
            pollingTask.cancel(true);
            pollingTask = null;
        }

        stopForeground(STOP_FOREGROUND_REMOVE);
        stopSelf();
        publishStatus(
            "stopped",
            "Monitorizarea serverului este oprită."
        );
    }

    private void publishStatus(String state, String message) {
        currentState = state;
        currentMessage = message;
        broadcastStatus(state, message);

        if (!"stopped".equals(state)) {
            getSystemService(NotificationManager.class).notify(
                SERVICE_NOTIFICATION_ID,
                buildServiceNotification()
            );
        }
    }

    private void broadcastStatus(String state, String message) {
        Intent intent = new Intent(STATUS_ACTION)
            .setPackage(getPackageName())
            .putExtra(EXTRA_STATE, state)
            .putExtra(EXTRA_MESSAGE, message);
        sendBroadcast(intent);
    }

    private void persistHealthState() {
        ServerMonitorSettingsStore.saveHealthState(
            this,
            healthTracker.offline(),
            healthTracker.consecutiveFailures()
        );
    }

    private PowerManager.WakeLock acquireShortWakeLock() {
        PowerManager powerManager =
            (PowerManager) getSystemService(POWER_SERVICE);
        PowerManager.WakeLock wakeLock = powerManager.newWakeLock(
            PowerManager.PARTIAL_WAKE_LOCK,
            "CloudInBuzunar:ServerHealthCheck"
        );
        wakeLock.setReferenceCounted(false);
        wakeLock.acquire(20_000L);
        return wakeLock;
    }

    private void createNotificationChannels() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return;
        }

        NotificationChannel serviceChannel = new NotificationChannel(
            SERVICE_CHANNEL_ID,
            "Monitorizare server",
            NotificationManager.IMPORTANCE_LOW
        );
        serviceChannel.setDescription(
            "Notificare permanentă pentru verificările serverului."
        );

        NotificationChannel alertChannel = new NotificationChannel(
            ALERT_CHANNEL_ID,
            "Alerte server",
            NotificationManager.IMPORTANCE_HIGH
        );
        alertChannel.setDescription(
            "Avertizează când serverul cade, revine sau raportează probleme."
        );
        alertChannel.enableVibration(true);

        NotificationManager manager =
            getSystemService(NotificationManager.class);
        manager.createNotificationChannel(serviceChannel);
        manager.createNotificationChannel(alertChannel);
    }

    private String safeMessage(Throwable error) {
        String message = error.getMessage();
        return message == null ? error.getClass().getSimpleName() : message;
    }
}
