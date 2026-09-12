package ro.cloudinbuzunar.monitor;

import android.content.Context;
import android.content.SharedPreferences;

final class ServerMonitorSettingsStore {
    private static final String PREFERENCES = "server_monitor_settings";
    private static final String SERVER_URL = "server_url";
    private static final String MONITORING_ENABLED = "monitoring_enabled";
    private static final String POLL_INTERVAL_SECONDS = "poll_interval_seconds";
    private static final String FAILURE_THRESHOLD = "failure_threshold";
    private static final String SERVER_OFFLINE = "server_offline";
    private static final String CONSECUTIVE_FAILURES = "consecutive_failures";

    static final int DEFAULT_POLL_INTERVAL_SECONDS = 60;
    static final int DEFAULT_FAILURE_THRESHOLD = 3;

    private ServerMonitorSettingsStore() {}

    static String serverUrl(Context context) {
        return preferences(context).getString(
            SERVER_URL,
            ApiClient.DEFAULT_SERVER_URL
        );
    }

    static void setServerUrl(Context context, String serverUrl) {
        preferences(context)
            .edit()
            .putString(SERVER_URL, ApiClient.normalizeServerUrl(serverUrl))
            .apply();
    }

    static boolean monitoringEnabled(Context context) {
        return preferences(context).getBoolean(MONITORING_ENABLED, false);
    }

    static void setMonitoringEnabled(Context context, boolean enabled) {
        preferences(context)
            .edit()
            .putBoolean(MONITORING_ENABLED, enabled)
            .apply();
    }

    static int pollIntervalSeconds(Context context) {
        return sanitizeInterval(
            preferences(context).getInt(
                POLL_INTERVAL_SECONDS,
                DEFAULT_POLL_INTERVAL_SECONDS
            )
        );
    }

    static void setPollIntervalSeconds(Context context, int seconds) {
        preferences(context)
            .edit()
            .putInt(POLL_INTERVAL_SECONDS, sanitizeInterval(seconds))
            .apply();
    }

    static int failureThreshold(Context context) {
        return sanitizeThreshold(
            preferences(context).getInt(
                FAILURE_THRESHOLD,
                DEFAULT_FAILURE_THRESHOLD
            )
        );
    }

    static void setFailureThreshold(Context context, int threshold) {
        preferences(context)
            .edit()
            .putInt(FAILURE_THRESHOLD, sanitizeThreshold(threshold))
            .apply();
    }

    static boolean serverOffline(Context context) {
        return preferences(context).getBoolean(SERVER_OFFLINE, false);
    }

    static int consecutiveFailures(Context context) {
        return Math.max(
            0,
            preferences(context).getInt(CONSECUTIVE_FAILURES, 0)
        );
    }

    static void saveHealthState(
        Context context,
        boolean offline,
        int failures
    ) {
        preferences(context)
            .edit()
            .putBoolean(SERVER_OFFLINE, offline)
            .putInt(CONSECUTIVE_FAILURES, Math.max(0, failures))
            .apply();
    }

    private static int sanitizeInterval(int seconds) {
        if (seconds == 30 || seconds == 60 || seconds == 120) {
            return seconds;
        }

        return DEFAULT_POLL_INTERVAL_SECONDS;
    }

    private static int sanitizeThreshold(int threshold) {
        if (threshold == 2 || threshold == 3 || threshold == 5) {
            return threshold;
        }

        return DEFAULT_FAILURE_THRESHOLD;
    }

    private static SharedPreferences preferences(Context context) {
        return context.getSharedPreferences(
            PREFERENCES,
            Context.MODE_PRIVATE
        );
    }
}
