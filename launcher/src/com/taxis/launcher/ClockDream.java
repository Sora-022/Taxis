package com.taxis.launcher;

import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.Typeface;
import android.os.Handler;
import android.service.dreams.DreamService;
import android.text.TextUtils;
import android.text.util.Linkify;
import android.util.Log;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.animation.PathInterpolator;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextClock;
import android.widget.TextView;

import java.io.File;
import java.util.Random;

/**
 * Taxis Idle screensaver: time and weather over the selected background.
 * It slowly drifts so no pixel stays lit. It never touches the Home button.
 */
public class ClockDream extends DreamService {
    private static final PathInterpolator EASE = new PathInterpolator(0.2f, 0f, 0f, 1f);
    private final Handler handler = new Handler();
    private final Random random = new Random();
    private SharedPreferences prefs;
    private FrameLayout box;
    private TextView weather, place;
    private Bitmap backgroundBitmap;

    // Converts density-independent sizes into pixels for consistent TV spacing.
    private int dp(float v) {
        return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, getResources().getDisplayMetrics());
    }

    // Creates one quiet text style shared by the weather and place labels.
    private TextView text(int sp, int color) {
        TextView t = new TextView(this);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        t.setTextColor(color);
        t.setTypeface(Typeface.create("sans-serif-light", Typeface.NORMAL));
        t.setIncludeFontPadding(false);
        return t;
    }

    // Builds the screensaver and loads the same private background used by Taxis Home.
    @Override public void onAttachedToWindow() {
        super.onAttachedToWindow();
        setInteractive(false);
        setFullscreen(true);
        setScreenBright(false);
        prefs = getSharedPreferences("taxis", MODE_PRIVATE);

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);
        File backgroundFile = new File(getFilesDir(), "bg.jpg");
        if (backgroundFile.exists()) {
            backgroundBitmap = BitmapFactory.decodeFile(backgroundFile.getPath());
            if (backgroundBitmap != null) {
                ImageView image = new ImageView(this);
                image.setImageBitmap(backgroundBitmap);
                image.setScaleType(ImageView.ScaleType.CENTER_CROP);
                root.addView(image, new FrameLayout.LayoutParams(-1, -1));
                View shade = new View(this);
                int dim = Math.max(0, Math.min(85, prefs.getInt("dim", 45)));
                shade.setBackgroundColor(Color.argb(dim * 255 / 100, 0, 0, 0));
                root.addView(shade, new FrameLayout.LayoutParams(-1, -1));
            }
        }
        box = new FrameLayout(this);
        box.setPadding(dp(96), dp(56), dp(96), dp(72));

        LinearLayout left = new LinearLayout(this);
        left.setOrientation(LinearLayout.VERTICAL);
        TextClock clock = new TextClock(this);
        clock.setFormat12Hour("h:mm");
        clock.setFormat24Hour("HH:mm");
        clock.setTextSize(TypedValue.COMPLEX_UNIT_SP, 124);
        clock.setTextColor(Color.parseColor("#DDE3E9"));
        clock.setTypeface(Typeface.create("sans-serif-light", Typeface.NORMAL));
        clock.setIncludeFontPadding(false);
        weather = text(24, Color.parseColor("#8E99A6"));
        weather.setPadding(dp(8), dp(8), 0, 0);
        TextView credit = text(11, Color.parseColor("#56616D"));
        credit.setAutoLinkMask(Linkify.WEB_URLS);
        credit.setLinkTextColor(Color.parseColor("#56616D"));
        credit.setText("Weather data: https://open-meteo.com");
        credit.setPadding(dp(8), dp(5), 0, 0);
        left.addView(clock);
        left.addView(weather);
        left.addView(credit);
        box.addView(left, new FrameLayout.LayoutParams(-2, -2, Gravity.CENTER_VERTICAL | Gravity.START));

        place = text(26, Color.parseColor("#6E7986"));
        place.setGravity(Gravity.END);
        place.setMaxWidth(dp(460));
        place.setSingleLine(true);
        place.setEllipsize(TextUtils.TruncateAt.END);
        box.addView(place, new FrameLayout.LayoutParams(-2, -2, Gravity.BOTTOM | Gravity.END));

        root.addView(box, new FrameLayout.LayoutParams(-1, -1));
        setContentView(root);
        showCached();
    }

    /** Shows whatever weather the launcher saved last, instantly. */
    private void showCached() {
        String p = prefs.getString("place", "");
        place.setText(p.length() > 0 ? p : WeatherClient.tzPlace());
        if (prefs.contains("temp")) {
            show(Double.longBitsToDouble(prefs.getLong("temp", 0)), prefs.getInt("code", 0));
        } else {
            weather.setText("");
        }
    }

    /** Formats one cached or freshly downloaded weather reading. */
    private void show(double tempC, int code) {
        boolean f = "f".equals(prefs.getString("units", "c"));
        long t = Math.round(f ? tempC * 9 / 5 + 32 : tempC);
        String c = WeatherClient.condition(code);
        weather.setText(t + "\u00B0" + (c.length() > 0 ? "   " + c : ""));
    }

    private final Runnable drift = new Runnable() {
        // Moves the content slightly once per minute to avoid static bright pixels.
        @Override public void run() {
            box.animate().translationX(random.nextInt(dp(48)) - dp(24)).translationY(random.nextInt(dp(36)) - dp(18))
                    .setDuration(3000).setInterpolator(EASE).start();
            handler.postDelayed(this, 60000);
        }
    };

    // Starts gentle movement and refreshes saved weather without blocking the Dream manager.
    @Override public void onDreamingStarted() {
        super.onDreamingStarted();
        handler.postDelayed(drift, 60000);
        new Thread() {
            @Override public void run() {
                try {
                    final WeatherClient.Result r = WeatherClient.fetch(ClockDream.this, prefs);
                    handler.post(new Runnable() {
                        @Override public void run() {
                            place.setText(r.place.length() > 0 ? r.place : WeatherClient.tzPlace());
                            show(r.tempC, r.code);
                        }
                    });
                } catch (Exception e) {
                    Log.e("taxis", "Taxis Idle weather failed", e);   // keep showing the saved values
                }
            }
        }.start();
    }

    // Stops callbacks and releases the decoded background when the screensaver closes.
    @Override public void onDreamingStopped() {
        handler.removeCallbacksAndMessages(null);
        if (backgroundBitmap != null) {
            backgroundBitmap.recycle();
            backgroundBitmap = null;
        }
        super.onDreamingStopped();
    }
}
