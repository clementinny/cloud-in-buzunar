package ro.cloudinbuzunar.monitor;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

public final class ServerWatchBootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        String action = intent == null ? null : intent.getAction();

        if (
            !Intent.ACTION_BOOT_COMPLETED.equals(action)
            && !Intent.ACTION_MY_PACKAGE_REPLACED.equals(action)
        ) {
            return;
        }

        if (!ServerMonitorSettingsStore.monitoringEnabled(context)) {
            return;
        }

        context.startForegroundService(
            new Intent(context, ServerWatchService.class)
                .setAction(ServerWatchService.ACTION_START)
        );
    }
}
