package ro.cloudinbuzunar.monitor;

import android.content.Context;
import android.content.SharedPreferences;

final class MonitorStateStore {
    private static final String PREFERENCES = "monitor_state";
    private static final String ARMED = "armed";
    private static final String CAMERA_FACING = "camera_facing";
    private static final String RECORDING_MODE = "recording_mode";

    private MonitorStateStore() {}

    static boolean isArmed(Context context) {
        return preferences(context).getBoolean(ARMED, false);
    }

    static String cameraFacing(Context context) {
        String facing = preferences(context).getString(
            CAMERA_FACING,
            "environment"
        );
        return "user".equals(facing) ? "user" : "environment";
    }

    static void arm(Context context, String cameraFacing) {
        preferences(context)
            .edit()
            .putBoolean(ARMED, true)
            .putString(
                CAMERA_FACING,
                "user".equals(cameraFacing) ? "user" : "environment"
            )
            .apply();
    }

    static void updateCameraFacing(Context context, String cameraFacing) {
        preferences(context)
            .edit()
            .putString(
                CAMERA_FACING,
                "user".equals(cameraFacing) ? "user" : "environment"
            )
            .apply();
    }

    static String recordingMode(Context context) {
        String mode = preferences(context).getString(RECORDING_MODE, "off");

        if ("audio".equals(mode) || "video".equals(mode)) {
            return mode;
        }

        return "off";
    }

    static void updateRecordingMode(Context context, String mode) {
        String safeMode = "audio".equals(mode) || "video".equals(mode)
            ? mode
            : "off";
        preferences(context)
            .edit()
            .putString(RECORDING_MODE, safeMode)
            .apply();
    }

    static void disarm(Context context) {
        preferences(context)
            .edit()
            .putBoolean(ARMED, false)
            .putString(RECORDING_MODE, "off")
            .apply();
    }

    private static SharedPreferences preferences(Context context) {
        return context.getSharedPreferences(
            PREFERENCES,
            Context.MODE_PRIVATE
        );
    }
}
