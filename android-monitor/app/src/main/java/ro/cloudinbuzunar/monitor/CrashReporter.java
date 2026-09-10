package ro.cloudinbuzunar.monitor;

import android.content.Context;
import android.content.SharedPreferences;

import java.io.PrintWriter;
import java.io.StringWriter;

final class CrashReporter {
    private static final String PREFERENCES = "monitor_diagnostics";
    private static final String LAST_CRASH = "last_crash";
    private static final int MAXIMUM_LENGTH = 3000;

    private CrashReporter() {}

    static void record(Context context, Throwable error) {
        StringWriter buffer = new StringWriter();
        error.printStackTrace(new PrintWriter(buffer));
        String report = buffer.toString();

        if (report.length() > MAXIMUM_LENGTH) {
            report = report.substring(0, MAXIMUM_LENGTH);
        }

        preferences(context)
            .edit()
            .putString(LAST_CRASH, report)
            .commit();
    }

    static String consume(Context context) {
        SharedPreferences preferences = preferences(context);
        String report = preferences.getString(LAST_CRASH, null);

        if (report != null) {
            preferences.edit().remove(LAST_CRASH).apply();
        }

        return report;
    }

    private static SharedPreferences preferences(Context context) {
        return context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE);
    }
}
