package com.taxis.launcher;

import android.accessibilityservice.AccessibilityService;
import android.content.Intent;
import android.os.SystemClock;
import android.util.Log;
import android.view.accessibility.AccessibilityEvent;

/**
 * Returns to Taxis when TCL's reserved Home button opens Google TV's launcher.
 */
public class HomeRedirectService extends AccessibilityService {
    private static final String TAG = "taxis";
    private static final String STOCK_HOME = "com.google.android.apps.tv.launcherx";
    private static final long REDIRECT_DEBOUNCE_MS = 650;

    private long lastRedirectAt;

    // Reopens Taxis whenever Google TV's launcher becomes the active window.
    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        if (event == null || event.getPackageName() == null
                || !STOCK_HOME.contentEquals(event.getPackageName())) {
            return;
        }
        openTaxis();
    }

    // Starts the single Taxis task once and coalesces duplicate window events from the same Home press.
    private void openTaxis() {
        long now = SystemClock.elapsedRealtime();
        if (now - lastRedirectAt < REDIRECT_DEBOUNCE_MS) return;
        lastRedirectAt = now;
        Intent launcher = new Intent(this, MainActivity.class);
        launcher.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        try {
            startActivity(launcher);
        } catch (RuntimeException error) {
            Log.w(TAG, "The TV blocked the Taxis Home redirect.", error);
        }
    }

    // Handles Android temporarily interrupting Accessibility feedback; no cleanup is required.
    @Override
    public void onInterrupt() {
        Log.i(TAG, "Taxis Home redirect interrupted by Android.");
    }
}
