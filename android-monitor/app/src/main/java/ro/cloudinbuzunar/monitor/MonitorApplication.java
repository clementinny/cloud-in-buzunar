package ro.cloudinbuzunar.monitor;

import android.app.Application;

public final class MonitorApplication extends Application {
    @Override
    public void onCreate() {
        super.onCreate();
        Thread.UncaughtExceptionHandler previousHandler =
            Thread.getDefaultUncaughtExceptionHandler();

        Thread.setDefaultUncaughtExceptionHandler((thread, error) -> {
            CrashReporter.record(this, error);

            if (previousHandler != null) {
                previousHandler.uncaughtException(thread, error);
            }
        });
    }
}
