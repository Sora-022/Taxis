package com.taxis.launcher;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.util.Log;

/**
 * Opens Taxis Launcher after Android finishes a full device boot.
 */
public class BootReceiver extends BroadcastReceiver {
    private static final String TAG = "taxis";

    // Opens the launcher when Android reports that a full boot has completed.
    @Override
    public void onReceive(Context context, Intent intent) {
        if (!Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction())) {
            return;
        }

        Intent launcher = new Intent(context, MainActivity.class);
        launcher.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        try {
            context.startActivity(launcher);
        } catch (RuntimeException error) {
            Log.w(TAG, "The TV blocked Taxis Launcher from opening after boot.", error);
        }
    }
}
