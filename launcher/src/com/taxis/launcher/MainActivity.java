package com.taxis.launcher;

import android.animation.ArgbEvaluator;
import android.animation.ValueAnimator;
import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Matrix;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.BitmapDrawable;
import android.graphics.drawable.ColorDrawable;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.media.AudioManager;
import android.media.ExifInterface;
import android.media.tv.TvContract;
import android.media.tv.TvInputInfo;
import android.media.tv.TvInputManager;
import android.net.ConnectivityManager;
import android.net.NetworkInfo;
import android.net.Uri;
import android.net.wifi.WifiInfo;
import android.net.wifi.WifiManager;
import android.os.Bundle;
import android.os.Handler;
import android.provider.Settings;
import android.text.TextUtils;
import android.text.util.Linkify;
import android.text.format.DateFormat;
import android.util.Log;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.view.animation.PathInterpolator;
import android.widget.AdapterView;
import android.widget.BaseAdapter;
import android.widget.FrameLayout;
import android.widget.GridView;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.io.FileOutputStream;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.Date;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Random;
import java.util.Set;

/**
 * Taxis Launcher: a quiet, minimalist home screen for Android TV.
 *   LANDING : time and weather on the left, place on the right, three quiet links
 *   APPS    : a calm, spacious app grid
 *   QUICK   : a side panel with Wi-Fi, HDMI inputs, volume and shortcuts
 *   AMBIENT : after a while idle, only time, weather and place on black
 */
public class MainActivity extends Activity {
    private enum Mode { LANDING, APPS, AMBIENT, QUICK }

    private static final long LANDING_IDLE_MS = 45000;
    private static final long APPS_IDLE_MS = 90000;
    private static final long WEATHER_EVERY_MS = 20 * 60 * 1000;

    // one calm palette
    private static final int WHITE = Color.parseColor("#F2F5F8");
    private static final int NAV = Color.parseColor("#B4BFCB");
    private static final int MUTED = Color.parseColor("#8B97A5");
    private static final int FAINT = Color.parseColor("#5F6B79");
    private static final int GLOW_ALPHA = 28; // focus highlight = white at ~11%
    private static final PathInterpolator EASE = new PathInterpolator(0.2f, 0f, 0f, 1f);

    private static class AppItem {
        String label, pkg;
        Intent launch;
        Bitmap icon;
        Drawable iconDrawable;
    }

    private final Handler handler = new Handler();
    private final List<AppItem> apps = new ArrayList<AppItem>();
    private final Map<String, Bitmap> iconCache = new HashMap<String, Bitmap>();
    private final Map<View, ValueAnimator> glowAnims = new HashMap<View, ValueAnimator>();
    private final Random random = new Random();
    private SharedPreferences prefs;
    private Mode mode = Mode.LANDING;

    private FrameLayout root;
    private GradientDrawable bg;
    private ImageView bgImage;
    private View scrim;
    private String pendingBg;
    private boolean pendingBgClear;
    private View landing, appsLayer, ambient, quick, quickFirst;
    private TextView lClock, lDate, lPlace, lStatus, lTemp, lCond, appsCount, appsClock;
    private TextView navApps, navQuick, navSettings;
    private TextView aClock, aPlace, aWeather, wifiSub, volSub;
    private LinearLayout leftCol, placeBox, quickPanel, quickList;
    private FrameLayout ambBox;
    private GridView grid;
    private AppAdapter adapter;
    private View prevSelected;
    private String appsSignature = "";
    private volatile int loadGeneration = 0;

    private long lastWeatherFetch = 0;
    private boolean hasWeather = false;
    private boolean bgTouched = false;
    private double tempC;
    private int wmoCode;
    private String place = "";
    private String statusMsg = "";

    // ------------------------------------------------------------------ helpers
    private int dp(float v) {
        return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, getResources().getDisplayMetrics());
    }

    /** style: 0 = light, 1 = regular, 2 = medium */
    private TextView text(int sp, int color, int style) {
        TextView t = new TextView(this);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        t.setTextColor(color);
        t.setTypeface(Typeface.create(style == 0 ? "sans-serif-light" : style == 2 ? "sans-serif-medium" : "sans-serif", Typeface.NORMAL));
        t.setIncludeFontPadding(false);
        t.setShadowLayer(dp(8), 0, dp(1), Color.parseColor("#59000000"));
        return t;
    }

    private boolean useFahrenheit() { return "f".equals(prefs.getString("units", "c")); }

    private String tempText() {
        if (!hasWeather) return "--";
        double v = useFahrenheit() ? tempC * 9 / 5 + 32 : tempC;
        return Math.round(v) + "\u00B0";
    }

    private static String condition(int c) {
        if (c == 0) return "Clear";
        if (c == 1) return "Mostly clear";
        if (c == 2) return "Partly cloudy";
        if (c == 3) return "Overcast";
        if (c == 45 || c == 48) return "Fog";
        if (c >= 51 && c <= 57) return "Drizzle";
        if (c >= 61 && c <= 67) return "Rain";
        if (c >= 71 && c <= 77) return "Snow";
        if (c >= 80 && c <= 82) return "Rain showers";
        if (c == 85 || c == 86) return "Snow showers";
        if (c == 95) return "Thunderstorm";
        if (c == 96 || c == 99) return "Thunderstorm, hail";
        return "";
    }

    private String weatherLine() {
        if (!hasWeather) return "Weather unavailable";
        String c = condition(wmoCode);
        return tempText() + (c.length() > 0 ? "   " + c : "");
    }

    /** Shown until a real place is found: the city part of the TV's time zone, e.g. "Asia/Manila" -> "Manila". */
    private static String tzPlace() {
        String id = java.util.TimeZone.getDefault().getID();
        int i = id.indexOf('/');
        return (i >= 0 ? id.substring(i + 1) : id).replace('_', ' ');
    }

    private String placeLabel() { return place.length() > 0 ? place : tzPlace(); }

    private void setStatus(final String msg) {
        statusMsg = msg;
        runOnUiThread(new Runnable() {
            @Override public void run() { if (lStatus != null) lStatus.setText(statusMsg); }
        });
    }

    /** Fades a soft white highlight behind a view (and optionally its text colour) in or out. */
    private void glow(final View v, final GradientDrawable hl, final TextView label, final int off, final int on, boolean focused) {
        ValueAnimator prev = glowAnims.get(v);
        if (prev != null) prev.cancel();
        float from = hl.getAlpha() / (float) GLOW_ALPHA;
        ValueAnimator a = ValueAnimator.ofFloat(from, focused ? 1f : 0f);
        a.setDuration(240);
        a.setInterpolator(EASE);
        final ArgbEvaluator ev = new ArgbEvaluator();
        a.addUpdateListener(new ValueAnimator.AnimatorUpdateListener() {
            @Override public void onAnimationUpdate(ValueAnimator an) {
                float f = (Float) an.getAnimatedValue();
                hl.setAlpha((int) (f * GLOW_ALPHA));
                if (label != null) label.setTextColor((Integer) ev.evaluate(f, off, on));
            }
        });
        glowAnims.put(v, a);
        a.start();
    }

    private GradientDrawable highlight(float radiusDp) {
        GradientDrawable g = new GradientDrawable();
        g.setCornerRadius(dp(radiusDp));
        g.setColor(Color.WHITE);
        g.setAlpha(0);
        return g;
    }

    // ------------------------------------------------------------------ lifecycle
    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        prefs = getSharedPreferences("taxis", MODE_PRIVATE);
        final Thread.UncaughtExceptionHandler oldHandler = Thread.getDefaultUncaughtExceptionHandler();
        Thread.setDefaultUncaughtExceptionHandler(new Thread.UncaughtExceptionHandler() {
            @Override public void uncaughtException(Thread t, Throwable e) {
                try { prefs.edit().putString("crash", Log.getStackTraceString(e)).commit(); } catch (Throwable ignored) { }
                if (oldHandler != null) oldHandler.uncaughtException(t, e);
            }
        });
        String crash = prefs.getString("crash", null);
        if (crash != null) {
            statusMsg = "Recovered from a crash: " + crash.split("\n")[0];
            prefs.edit().remove("crash").apply();
        }
        place = prefs.getString("place", "");
        if (prefs.contains("temp")) {
            hasWeather = true;
            tempC = Double.longBitsToDouble(prefs.getLong("temp", 0));
            wmoCode = prefs.getInt("code", 0);
        }
        handleConfig(getIntent());

        bg = new GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM, new int[]{Color.BLACK, Color.BLACK});
        root = new FrameLayout(this);
        root.setBackgroundDrawable(bg);
        bgImage = new ImageView(this);
        bgImage.setScaleType(ImageView.ScaleType.CENTER_CROP);
        bgImage.setAlpha(0f);
        scrim = new View(this);
        root.addView(bgImage, new FrameLayout.LayoutParams(-1, -1));
        root.addView(scrim, new FrameLayout.LayoutParams(-1, -1));
        landing = buildLanding();
        appsLayer = buildApps();
        ambient = buildAmbient();
        quick = buildQuick();
        root.addView(landing, new FrameLayout.LayoutParams(-1, -1));
        root.addView(appsLayer, new FrameLayout.LayoutParams(-1, -1));
        root.addView(ambient, new FrameLayout.LayoutParams(-1, -1));
        root.addView(quick, new FrameLayout.LayoutParams(-1, -1));
        appsLayer.setVisibility(View.GONE);
        ambient.setVisibility(View.GONE);
        quick.setVisibility(View.GONE);
        setContentView(root);
        updateClock();
        updatePalette();
        navApps.requestFocus();
        applyBackground();
        bgTouched = false;
    }

    @Override protected void onResume() {
        super.onResume();
        handler.removeCallbacks(tick);
        handler.post(tick);
        loadApps();
        refreshWeather(false);
        if (mode == Mode.AMBIENT) getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        bump();
    }

    @Override protected void onPause() {
        super.onPause();
        handler.removeCallbacks(tick);
        handler.removeCallbacks(idleRun);
        getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
    }

    @Override protected void onNewIntent(Intent i) {
        super.onNewIntent(i);
        boolean changed = handleConfig(i);
        if (changed) { lastWeatherFetch = 0; refreshWeather(true); updatePalette(); }
        if (bgTouched) { bgTouched = false; applyBackground(); }
        show(Mode.LANDING); // Home pressed: always come back to the landing page
        bump();
    }

    @Override public void onBackPressed() {
        if (mode != Mode.LANDING) show(Mode.LANDING);
        bump();
    }

    /** `adb shell am start -n com.taxis.launcher/.MainActivity --es city "Manila" --es units c` */
    private boolean handleConfig(Intent i) {
        if (i == null) return false;
        boolean changed = false;
        SharedPreferences.Editor e = prefs.edit();
        String city = i.getStringExtra("city");
        if (city != null && city.trim().length() > 0) {
            e.putString("city", city.trim()).remove("lat").remove("lon").remove("place").remove("location_source");
            changed = true;
        }
        if (i.getBooleanExtra("auto_location", false)) {
            e.remove("city").remove("lat").remove("lon").remove("place").remove("location_source");
            changed = true;
        }
        String units = i.getStringExtra("units");
        if (units != null && (units.equals("c") || units.equals("f"))) {
            e.putString("units", units);
            changed = true;
        }
        if (i.hasExtra("dim")) { e.putInt("dim", Math.max(0, Math.min(85, i.getIntExtra("dim", 45)))); changed = true; bgTouched = true; }
        String preset = i.getStringExtra("preset");
        if (preset != null) { e.putString("preset", preset.toLowerCase()); changed = true; lastPaletteHour = -1; }
        if (i.getBooleanExtra("bg_clear", false)) { pendingBgClear = true; changed = true; bgTouched = true; }
        String bgPath = i.getStringExtra("bg");
        if (bgPath != null && bgPath.length() > 0) { pendingBg = bgPath; changed = true; bgTouched = true; }
        e.apply();
        return changed;
    }

    // ------------------------------------------------------------------ clock + background
    private final Runnable tick = new Runnable() {
        @Override public void run() {
            updateClock();
            updatePalette();
            if (System.currentTimeMillis() - lastWeatherFetch > WEATHER_EVERY_MS) refreshWeather(false);
            handler.postDelayed(this, 5000);
        }
    };

    private String lastMinute = "";

    private void updateClock() {
        Date now = new Date();
        String t = DateFormat.getTimeFormat(this).format(now);
        if (t.equals(lastMinute)) return;
        boolean first = lastMinute.length() == 0;
        lastMinute = t;
        lDate.setText(DateFormat.format("EEEE, d MMMM", now));
        appsClock.setText(t);
        if (first) {
            lClock.setText(t);
            aClock.setText(t);
        } else if (mode == Mode.AMBIENT) {
            swapText(aClock, t);
            lClock.setText(t);
            drift();
        } else {
            swapText(lClock, t);
            aClock.setText(t);
        }
    }

    /** Fade the old digits out and the new ones in, so the clock never snaps. */
    private void swapText(final TextView v, final String t) {
        v.animate().alpha(0f).setDuration(160).withLayer().withEndAction(new Runnable() {
            @Override public void run() { v.setText(t); v.animate().alpha(1f).setDuration(320).withLayer().start(); }
        }).start();
    }

    private int lastPaletteHour = -1;

    /** Very low-saturation blue-greys; they shift a little through the day. */
    private void updatePalette() {
        int h = java.util.Calendar.getInstance().get(java.util.Calendar.HOUR_OF_DAY);
        if (h == lastPaletteHour) return;
        lastPaletteHour = h;
        int top, bottom;
        String preset = prefs.getString("preset", "auto");
        if (preset.equals("midnight"))      { top = Color.parseColor("#05080d"); bottom = Color.parseColor("#0e1622"); }
        else if (preset.equals("ocean"))    { top = Color.parseColor("#0b1a2a"); bottom = Color.parseColor("#1a3a58"); }
        else if (preset.equals("forest"))   { top = Color.parseColor("#0e1912"); bottom = Color.parseColor("#1d3328"); }
        else if (preset.equals("dusk"))     { top = Color.parseColor("#171222"); bottom = Color.parseColor("#3a2a47"); }
        else if (preset.equals("graphite")) { top = Color.parseColor("#0f1011"); bottom = Color.parseColor("#1e2023"); }
        else if (h >= 6 && h < 11)       { top = Color.parseColor("#141c26"); bottom = Color.parseColor("#223142"); }
        else if (h >= 11 && h < 17) { top = Color.parseColor("#131b25"); bottom = Color.parseColor("#1e2b3a"); }
        else if (h >= 17 && h < 21) { top = Color.parseColor("#14161f"); bottom = Color.parseColor("#252a3b"); }
        else                        { top = Color.parseColor("#0a0d12"); bottom = Color.parseColor("#11171f"); }
        bg.setColors(new int[]{top, bottom});
    }

    // ------------------------------------------------------------------ background image
    /** Imports a newly pushed image (if any), then shows whatever background is saved. All off the main thread. */
    private void applyBackground() {
        final String imp = pendingBg;
        final boolean clr = pendingBgClear;
        pendingBg = null;
        pendingBgClear = false;
        final int dim = prefs.getInt("dim", 45);
        new Thread() {
            @Override public void run() {
                File priv = new File(getFilesDir(), "bg.jpg");
                try {
                    if (clr) priv.delete();
                    if (imp != null) importBackground(imp, priv);
                } catch (Throwable e) {
                    Log.e("taxis", "background", e);
                    setStatus("Background: " + e.getMessage());
                }
                Bitmap b = null;
                if (priv.exists()) {
                    BitmapFactory.Options o = new BitmapFactory.Options();
                    o.inPreferredConfig = Bitmap.Config.RGB_565;
                    b = BitmapFactory.decodeFile(priv.getPath(), o);
                }
                final Bitmap fb = b;
                runOnUiThread(new Runnable() {
                    @Override public void run() { showBackground(fb, dim); }
                });
            }
        }.start();
    }

    private void showBackground(Bitmap b, int dim) {
        if (b == null) {
            bgImage.setImageDrawable(null);
            bgImage.setAlpha(0f);
            scrim.setBackgroundColor(Color.TRANSPARENT);
            return;
        }
        bgImage.setImageBitmap(b);
        bgImage.setAlpha(0f);
        bgImage.animate().alpha(1f).setDuration(800).start();
        scrim.setBackgroundColor(Color.argb(dim * 255 / 100, 0, 0, 0)); // darkens the photo so text stays readable
    }

    /** Reads the pushed picture, fixes its rotation, centre-crops it to 1920x1080 and keeps a private copy. */
    private void importBackground(String path, File dest) throws Exception {
        BitmapFactory.Options o = new BitmapFactory.Options();
        o.inJustDecodeBounds = true;
        BitmapFactory.decodeFile(path, o);
        if (o.outWidth <= 0) throw new Exception("could not read the image (allow storage for this app in Settings > Apps)");
        int sample = 1;
        while (o.outWidth / (sample * 2) >= 1920 && o.outHeight / (sample * 2) >= 1080) sample *= 2;
        BitmapFactory.Options d = new BitmapFactory.Options();
        d.inSampleSize = sample;
        d.inPreferredConfig = Bitmap.Config.RGB_565;
        Bitmap src = BitmapFactory.decodeFile(path, d);
        if (src == null) throw new Exception("this image format is not supported");
        int rot = 0;
        try {
            int ori = new ExifInterface(path).getAttributeInt(ExifInterface.TAG_ORIENTATION, 1);
            rot = ori == 6 ? 90 : ori == 3 ? 180 : ori == 8 ? 270 : 0;
        } catch (Exception ignored) { }
        if (rot != 0) {
            Matrix mx = new Matrix();
            mx.postRotate(rot);
            Bitmap r = Bitmap.createBitmap(src, 0, 0, src.getWidth(), src.getHeight(), mx, true);
            src.recycle();
            src = r;
        }
        int tw = 1920, th = 1080;
        float scale = Math.max(tw / (float) src.getWidth(), th / (float) src.getHeight());
        int cw = Math.min(src.getWidth(), Math.round(tw / scale)), ch = Math.min(src.getHeight(), Math.round(th / scale));
        int cx = (src.getWidth() - cw) / 2, cy = (src.getHeight() - ch) / 2;
        Bitmap out = Bitmap.createBitmap(tw, th, Bitmap.Config.RGB_565);
        new Canvas(out).drawBitmap(src, new Rect(cx, cy, cx + cw, cy + ch), new Rect(0, 0, tw, th), new Paint(Paint.FILTER_BITMAP_FLAG));
        FileOutputStream fo = new FileOutputStream(dest);
        try { out.compress(Bitmap.CompressFormat.JPEG, 88, fo); } finally { fo.close(); }
        src.recycle();
        out.recycle();
        setStatus("");
    }

    // ------------------------------------------------------------------ landing
    private TextView navItem(String label, View.OnClickListener l) {
        final TextView t = text(20, NAV, 1);
        t.setText(label);
        t.setPadding(dp(22), dp(12), dp(22), dp(12));
        t.setFocusable(true);
        t.setClickable(true);
        t.setOnClickListener(l);
        final GradientDrawable hl = highlight(16);
        t.setBackgroundDrawable(hl);
        t.setOnFocusChangeListener(new View.OnFocusChangeListener() {
            @Override public void onFocusChange(View v, boolean has) { glow(v, hl, t, NAV, WHITE, has); }
        });
        return t;
    }

    /** Creates the required Open-Meteo credit beside every weather display. */
    private TextView weatherCredit() {
        TextView credit = text(11, FAINT, 1);
        credit.setAutoLinkMask(Linkify.WEB_URLS);
        credit.setLinkTextColor(FAINT);
        credit.setText("Weather data: https://open-meteo.com");
        credit.setPadding(dp(8), dp(5), 0, 0);
        return credit;
    }

    /** Builds the main clock, weather, place and navigation screen. */
    private View buildLanding() {
        FrameLayout f = new FrameLayout(this);
        f.setPadding(dp(88), dp(48), dp(88), dp(48));

        leftCol = new LinearLayout(this);
        leftCol.setOrientation(LinearLayout.VERTICAL);
        lClock = text(104, WHITE, 0);
        lDate = text(20, MUTED, 1);
        lDate.setPadding(dp(6), dp(8), 0, dp(30));
        LinearLayout w = new LinearLayout(this);
        w.setOrientation(LinearLayout.HORIZONTAL);
        w.setGravity(Gravity.BOTTOM);
        w.setPadding(dp(6), 0, 0, 0);
        lTemp = text(44, WHITE, 0);
        lTemp.setText(tempText());
        lCond = text(18, MUTED, 1);
        lCond.setText(hasWeather ? condition(wmoCode) : "Weather unavailable");
        lCond.setPadding(dp(16), 0, 0, dp(7));
        w.addView(lTemp);
        w.addView(lCond);
        LinearLayout nav = new LinearLayout(this);
        nav.setOrientation(LinearLayout.HORIZONTAL);
        nav.setPadding(0, dp(52), 0, 0);
        navApps = navItem("Apps", new View.OnClickListener() { @Override public void onClick(View v) { show(Mode.APPS); } });
        navQuick = navItem("Quick settings", new View.OnClickListener() { @Override public void onClick(View v) { openQuick(); } });
        navSettings = navItem("Settings", new View.OnClickListener() { @Override public void onClick(View v) { openSettings(); } });
        nav.addView(navApps);
        nav.addView(navQuick);
        nav.addView(navSettings);
        leftCol.addView(lClock);
        leftCol.addView(lDate);
        leftCol.addView(w);
        leftCol.addView(weatherCredit());
        leftCol.addView(nav);
        f.addView(leftCol, new FrameLayout.LayoutParams(-2, -2, Gravity.CENTER_VERTICAL | Gravity.START));

        placeBox = new LinearLayout(this);
        placeBox.setOrientation(LinearLayout.VERTICAL);
        placeBox.setGravity(Gravity.END);
        lPlace = text(30, WHITE, 0);
        lPlace.setGravity(Gravity.END);
        lPlace.setMaxWidth(dp(460));
        lPlace.setSingleLine(true);
        lPlace.setEllipsize(TextUtils.TruncateAt.END);
        lPlace.setText(placeLabel());
        lStatus = text(12, FAINT, 1);
        lStatus.setGravity(Gravity.END);
        lStatus.setMaxWidth(dp(460));
        lStatus.setPadding(0, dp(8), 0, 0);
        lStatus.setText(statusMsg);
        placeBox.addView(lPlace);
        placeBox.addView(lStatus);
        f.addView(placeBox, new FrameLayout.LayoutParams(-2, -2, Gravity.CENTER_VERTICAL | Gravity.END));
        return f;
    }

    // ------------------------------------------------------------------ idle screen
    /** Builds the in-launcher idle view over the currently selected background. */
    private View buildAmbient() {
        FrameLayout f = new FrameLayout(this);
        f.setBackgroundColor(Color.TRANSPARENT);
        ambBox = new FrameLayout(this);
        ambBox.setPadding(dp(96), dp(56), dp(96), dp(72));
        LinearLayout left = new LinearLayout(this);
        left.setOrientation(LinearLayout.VERTICAL);
        aClock = text(124, Color.parseColor("#DDE3E9"), 0);
        aWeather = text(24, Color.parseColor("#8E99A6"), 1);
        aWeather.setPadding(dp(8), dp(8), 0, 0);
        left.addView(aClock);
        left.addView(aWeather);
        left.addView(weatherCredit());
        ambBox.addView(left, new FrameLayout.LayoutParams(-2, -2, Gravity.CENTER_VERTICAL | Gravity.START));
        aPlace = text(34, Color.parseColor("#6E7986"), 0);
        aPlace.setGravity(Gravity.END);
        aPlace.setMaxWidth(dp(460));
        aPlace.setSingleLine(true);
        aPlace.setEllipsize(TextUtils.TruncateAt.END);
        aPlace.setText(placeLabel());
        aWeather.setText(weatherLine());
        aPlace.setTextSize(TypedValue.COMPLEX_UNIT_SP, 26);
        ambBox.addView(aPlace, new FrameLayout.LayoutParams(-2, -2, Gravity.BOTTOM | Gravity.END));
        f.addView(ambBox, new FrameLayout.LayoutParams(-1, -1));
        return f;
    }

    /** Nudge the idle layout a little every minute so no pixel stays lit (OLED / burn-in friendly). */
    private void drift() {
        ambBox.animate().translationX(random.nextInt(dp(48)) - dp(24)).translationY(random.nextInt(dp(36)) - dp(18))
                .setDuration(3000).setInterpolator(EASE).start();
    }

    // ------------------------------------------------------------------ apps
    private View buildApps() {
        FrameLayout f = new FrameLayout(this);
        f.setBackgroundColor(Color.parseColor("#33000000")); // a barely-there veil
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setPadding(dp(96), dp(56), dp(96), dp(20));

        LinearLayout head = new LinearLayout(this);
        head.setOrientation(LinearLayout.HORIZONTAL);
        head.setGravity(Gravity.BOTTOM);
        TextView title = text(30, WHITE, 0);
        title.setText("Apps");
        appsCount = text(15, FAINT, 1);
        appsCount.setPadding(dp(14), 0, 0, dp(5));
        head.addView(title);
        head.addView(appsCount);
        View spacer = new View(this);
        head.addView(spacer, new LinearLayout.LayoutParams(0, 1, 1f));
        appsClock = text(20, MUTED, 0);
        head.addView(appsClock);
        col.addView(head, new LinearLayout.LayoutParams(-1, -2));

        grid = new GridView(this);
        grid.setNumColumns(GridView.AUTO_FIT);
        grid.setColumnWidth(dp(168));
        grid.setStretchMode(GridView.STRETCH_COLUMN_WIDTH);
        grid.setVerticalSpacing(dp(14));
        grid.setHorizontalSpacing(dp(10));
        grid.setPadding(0, dp(40), 0, dp(24));
        grid.setClipToPadding(false);
        grid.setClipChildren(false);
        grid.setSelector(new ColorDrawable(Color.TRANSPARENT));
        grid.setSmoothScrollbarEnabled(true);
        grid.setScrollingCacheEnabled(true);
        grid.setOverScrollMode(View.OVER_SCROLL_NEVER);
        grid.setVerticalScrollBarEnabled(false);
        grid.setFocusable(true);
        grid.setFocusableInTouchMode(true);
        adapter = new AppAdapter();
        grid.setAdapter(adapter);
        grid.setOnItemClickListener(new AdapterView.OnItemClickListener() {
            @Override public void onItemClick(AdapterView<?> p, View v, int pos, long id) { launch(apps.get(pos)); }
        });
        grid.setOnItemLongClickListener(new AdapterView.OnItemLongClickListener() {
            @Override public boolean onItemLongClick(AdapterView<?> p, View v, int pos, long id) {
                appInfo(apps.get(pos));
                return true;
            }
        });
        grid.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(AdapterView<?> p, View v, int pos, long id) {
                if (prevSelected != null && prevSelected != v) focusCell(prevSelected, false);
                if (v != null) focusCell(v, true);
                prevSelected = v;
            }
            @Override public void onNothingSelected(AdapterView<?> p) {
                if (prevSelected != null) focusCell(prevSelected, false);
                prevSelected = null;
            }
        });
        col.addView(grid, new LinearLayout.LayoutParams(-1, 0, 1f));

        TextView hint = text(12, FAINT, 1);
        hint.setText("Back to return   \u00B7   hold OK for app info");
        hint.setGravity(Gravity.CENTER);
        col.addView(hint, new LinearLayout.LayoutParams(-1, -2));
        f.addView(col, new FrameLayout.LayoutParams(-1, -1));
        return f;
    }

    /** Quiet focus: a soft highlight fades in, the label brightens and the icon grows a little. No bounce. */
    private void focusCell(View cell, boolean on) {
        Object[] h = (Object[]) cell.getTag();
        if (h == null) return;
        glow(cell, (GradientDrawable) h[2], (TextView) h[1], MUTED, WHITE, on);
        ((View) h[0]).animate().scaleX(on ? 1.1f : 1f).scaleY(on ? 1.1f : 1f).setDuration(240).setInterpolator(EASE).withLayer().start();
    }

    private class AppAdapter extends BaseAdapter {
        @Override public int getCount() { return apps.size(); }
        @Override public Object getItem(int i) { return apps.get(i); }
        @Override public long getItemId(int i) { return i; }

        @Override public View getView(int i, View v, ViewGroup parent) {
            LinearLayout cell;
            if (v == null) {
                cell = new LinearLayout(MainActivity.this);
                cell.setOrientation(LinearLayout.VERTICAL);
                cell.setGravity(Gravity.CENTER_HORIZONTAL);
                cell.setPadding(dp(8), dp(18), dp(8), dp(14));
                GradientDrawable hl = highlight(22);
                cell.setBackgroundDrawable(hl);
                ImageView icon = new ImageView(MainActivity.this);
                icon.setScaleType(ImageView.ScaleType.FIT_CENTER);
                cell.addView(icon, new LinearLayout.LayoutParams(dp(64), dp(64)));
                TextView label = text(14, MUTED, 1);
                label.setGravity(Gravity.CENTER);
                label.setSingleLine(true);
                label.setEllipsize(TextUtils.TruncateAt.END);
                label.setPadding(0, dp(12), 0, 0);
                cell.addView(label, new LinearLayout.LayoutParams(-1, -2));
                cell.setTag(new Object[]{icon, label, hl});
            } else {
                cell = (LinearLayout) v;
            }
            Object[] h = (Object[]) cell.getTag();
            AppItem it = apps.get(i);
            if (it.iconDrawable == null) it.iconDrawable = new BitmapDrawable(getResources(), it.icon);
            ((ImageView) h[0]).setImageDrawable(it.iconDrawable);
            ((TextView) h[1]).setText(it.label);
            if (cell != prevSelected) {
                ValueAnimator a = glowAnims.get(cell);
                if (a != null) a.cancel();
                ((GradientDrawable) h[2]).setAlpha(0);
                ((TextView) h[1]).setTextColor(MUTED);
                ((View) h[0]).setScaleX(1f);
                ((View) h[0]).setScaleY(1f);
            }
            return cell;
        }
    }

    private void loadApps() {
        final int gen = ++loadGeneration;
        new Thread() {
            @Override public void run() {
                PackageManager pm = getPackageManager();
                Set<String> seen = new HashSet<String>();
                final List<AppItem> out = new ArrayList<AppItem>();
                String[] cats = {Intent.CATEGORY_LEANBACK_LAUNCHER, Intent.CATEGORY_LAUNCHER};
                int px = dp(64);
                for (String cat : cats) {
                    Intent q = new Intent(Intent.ACTION_MAIN).addCategory(cat);
                    for (ResolveInfo ri : pm.queryIntentActivities(q, 0)) {
                        String pkg = ri.activityInfo.packageName;
                        if (pkg.equals(getPackageName()) || !seen.add(pkg)) continue;
                        AppItem it = new AppItem();
                        it.pkg = pkg;
                        it.label = String.valueOf(ri.loadLabel(pm));
                        Bitmap bmp;
                        synchronized (iconCache) { bmp = iconCache.get(pkg); }
                        if (bmp == null) {
                            bmp = toBitmap(ri.loadIcon(pm), px);
                            synchronized (iconCache) { iconCache.put(pkg, bmp); }
                        }
                        it.icon = bmp;
                        it.launch = new Intent(Intent.ACTION_MAIN).addCategory(cat)
                                .setClassName(pkg, ri.activityInfo.name)
                                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED);
                        out.add(it);
                    }
                }
                Collections.sort(out, new Comparator<AppItem>() {
                    @Override public int compare(AppItem a, AppItem b) { return a.label.compareToIgnoreCase(b.label); }
                });
                StringBuilder sig = new StringBuilder();
                for (AppItem it : out) sig.append(it.pkg).append(';');
                final String signature = sig.toString();
                runOnUiThread(new Runnable() {
                    @Override public void run() {
                        if (gen != loadGeneration || signature.equals(appsSignature)) return; // nothing changed: no redraw
                        appsSignature = signature;
                        apps.clear();
                        apps.addAll(out);
                        adapter.notifyDataSetChanged();
                        appsCount.setText(String.valueOf(apps.size()));
                    }
                });
            }
        }.start();
    }

    private static Bitmap toBitmap(Drawable d, int px) {
        Bitmap b = Bitmap.createBitmap(px, px, Bitmap.Config.ARGB_8888);
        Canvas c = new Canvas(b);
        d.setBounds(0, 0, px, px);
        d.draw(c);
        return b;
    }

    private void launch(AppItem it) {
        try {
            startActivity(it.launch);
        } catch (ActivityNotFoundException e) {
            Toast.makeText(this, "Cannot open " + it.label, Toast.LENGTH_SHORT).show();
        }
    }

    private void appInfo(AppItem it) {
        startSafe(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:" + it.pkg)), "App info is not available");
    }

    private void openSettings() {
        startSafe(new Intent(Settings.ACTION_SETTINGS), "Settings are not available");
    }

    private void startSafe(Intent i, String failMsg) {
        try {
            startActivity(i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        } catch (Exception e) {
            Toast.makeText(this, failMsg, Toast.LENGTH_SHORT).show();
        }
    }

    // ------------------------------------------------------------------ modes + idle
    private View layer(Mode m) { return m == Mode.LANDING ? landing : m == Mode.APPS ? appsLayer : m == Mode.QUICK ? quick : ambient; }

    private void show(Mode m) {
        if (mode == Mode.QUICK) {            // leave the side panel first, then carry on from the landing page
            hideQuick();
            mode = Mode.LANDING;
            if (m == Mode.LANDING) { navQuick.requestFocus(); bump(); return; }
        }
        if (m == mode) return;
        final Mode old = mode;
        mode = m;
        final View from = layer(old), to = layer(m);
        long dur = m == Mode.AMBIENT ? 1400 : 380;
        to.setVisibility(View.VISIBLE);
        to.setAlpha(0f);
        to.setTranslationY(m == Mode.APPS ? dp(16) : 0);
        to.animate().alpha(1f).translationY(0).setDuration(dur).setInterpolator(EASE).withLayer().start();
        if (old == Mode.LANDING && m == Mode.APPS) {            // the landing page eases aside a little as the grid arrives
            leftCol.animate().translationX(-dp(24)).setDuration(dur).setInterpolator(EASE).start();
            placeBox.animate().translationX(dp(24)).setDuration(dur).setInterpolator(EASE).start();
        }
        from.animate().alpha(0f).setDuration(dur).setInterpolator(EASE).withLayer().withEndAction(new Runnable() {
            @Override public void run() { if (layer(mode) != from) from.setVisibility(View.GONE); }
        }).start();
        if (m == Mode.LANDING) playLandingIntro();
        if (m == Mode.AMBIENT) {
            getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            aPlace.setText(placeLabel());
            aWeather.setText(weatherLine());
            drift();
        } else {
            getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        }
        if (m == Mode.LANDING) navApps.requestFocus();
        if (m == Mode.APPS) { grid.requestFocus(); grid.setSelection(0); }
        bump();
    }

    /** The two sides slide in a short way from their edges while fading in. */
    private void playLandingIntro() {
        leftCol.setTranslationX(-dp(24));
        leftCol.setAlpha(0f);
        placeBox.setTranslationX(dp(24));
        placeBox.setAlpha(0f);
        leftCol.animate().translationX(0).alpha(1f).setDuration(560).setInterpolator(EASE).withLayer().start();
        placeBox.animate().translationX(0).alpha(1f).setStartDelay(100).setDuration(560).setInterpolator(EASE).withLayer().start();
    }

    private final Runnable idleRun = new Runnable() {
        @Override public void run() {
            if (mode == Mode.APPS || mode == Mode.QUICK) show(Mode.LANDING);
            else if (mode == Mode.LANDING) show(Mode.AMBIENT);
        }
    };

    private void bump() {
        handler.removeCallbacks(idleRun);
        if (mode == Mode.LANDING) handler.postDelayed(idleRun, LANDING_IDLE_MS);
        else if (mode == Mode.APPS || mode == Mode.QUICK) handler.postDelayed(idleRun, APPS_IDLE_MS);
    }

    @Override public boolean dispatchKeyEvent(KeyEvent e) {
        if (mode == Mode.AMBIENT) {
            if (e.getAction() == KeyEvent.ACTION_DOWN) show(Mode.LANDING);
            return true; // the first press only wakes the screen
        }
        if (e.getAction() == KeyEvent.ACTION_DOWN) bump();
        return super.dispatchKeyEvent(e);
    }

    @Override public boolean dispatchTouchEvent(MotionEvent e) {
        if (mode == Mode.AMBIENT) {
            if (e.getAction() == MotionEvent.ACTION_DOWN) show(Mode.LANDING);
            return true;
        }
        bump();
        return super.dispatchTouchEvent(e);
    }

    @Override public boolean dispatchGenericMotionEvent(MotionEvent e) {
        if (mode == Mode.AMBIENT) { show(Mode.LANDING); return true; }
        bump();
        return super.dispatchGenericMotionEvent(e);
    }

    // ------------------------------------------------------------------ quick settings panel
    private View buildQuick() {
        FrameLayout wrap = new FrameLayout(this);
        quickPanel = new LinearLayout(this);
        quickPanel.setOrientation(LinearLayout.VERTICAL);
        GradientDrawable pbg = new GradientDrawable();
        pbg.setColor(Color.parseColor("#F0111821"));
        pbg.setCornerRadii(new float[]{dp(24), dp(24), 0, 0, 0, 0, dp(24), dp(24)});
        quickPanel.setBackgroundDrawable(pbg);
        quickPanel.setPadding(dp(36), dp(44), dp(36), dp(20));
        TextView title = text(28, WHITE, 0);
        title.setText("Quick settings");
        title.setPadding(dp(4), 0, 0, dp(10));
        quickPanel.addView(title);
        ScrollView sv = new ScrollView(this);
        sv.setVerticalScrollBarEnabled(false);
        quickList = new LinearLayout(this);
        quickList.setOrientation(LinearLayout.VERTICAL);
        sv.addView(quickList, new ViewGroup.LayoutParams(-1, -2));
        quickPanel.addView(sv, new LinearLayout.LayoutParams(-1, 0, 1f));
        wrap.addView(quickPanel, new FrameLayout.LayoutParams(dp(500), -1, Gravity.END));
        return wrap;
    }

    private void openQuick() {
        if (mode != Mode.LANDING) return;
        mode = Mode.QUICK;
        ((ViewGroup) landing).setDescendantFocusability(ViewGroup.FOCUS_BLOCK_DESCENDANTS); // keep the D-pad inside the panel
        refreshQuick();
        quick.setVisibility(View.VISIBLE);
        quickPanel.setTranslationX(dp(500));
        quickPanel.animate().translationX(0).setDuration(420).setInterpolator(EASE).withLayer().start();
        landing.animate().alpha(0.3f).setDuration(380).start();
        if (quickFirst != null) quickFirst.requestFocus();
        bump();
    }

    private void hideQuick() {
        ((ViewGroup) landing).setDescendantFocusability(ViewGroup.FOCUS_AFTER_DESCENDANTS);
        quickPanel.animate().translationX(dp(500)).setDuration(320).setInterpolator(EASE).withLayer().withEndAction(new Runnable() {
            @Override public void run() { if (mode != Mode.QUICK) quick.setVisibility(View.GONE); }
        }).start();
        landing.animate().alpha(1f).setDuration(320).start();
    }

    private TextView section(String name) {
        TextView t = text(12, FAINT, 2);
        t.setText(name.toUpperCase());
        t.setLetterSpacing(0.18f);
        t.setPadding(dp(6), dp(22), 0, dp(8));
        quickList.addView(t);
        return t;
    }

    /** A plain row: title, small status line. Focus = the same soft white highlight as everywhere else. */
    private LinearLayout tileView(String title, String sub, View.OnClickListener l, TextView[] out) {
        final LinearLayout t = new LinearLayout(this);
        t.setOrientation(LinearLayout.VERTICAL);
        t.setPadding(dp(20), dp(14), dp(20), dp(14));
        TextView a = text(18, WHITE, 1);
        a.setText(title);
        TextView b = text(13, MUTED, 1);
        b.setText(sub);
        b.setPadding(0, dp(3), 0, 0);
        t.addView(a);
        t.addView(b);
        t.setFocusable(true);
        t.setClickable(true);
        t.setOnClickListener(l);
        final GradientDrawable hl = highlight(16);
        t.setBackgroundDrawable(hl);
        t.setOnFocusChangeListener(new View.OnFocusChangeListener() {
            @Override public void onFocusChange(View v, boolean has) { glow(v, hl, null, 0, 0, has); }
        });
        if (out != null) out[0] = b;
        return t;
    }

    private TextView addTile(String title, String sub, View.OnClickListener l) {
        TextView[] sref = new TextView[1];
        LinearLayout t = tileView(title, sub, l, sref);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.bottomMargin = dp(4);
        quickList.addView(t, lp);
        if (quickFirst == null) quickFirst = t;
        return sref[0];
    }

    private void shortcut(String title, String sub, final String action) {
        addTile(title, sub, new View.OnClickListener() {
            @Override public void onClick(View v) { startSafe(new Intent(action), "Not available on this TV"); }
        });
    }

    private void refreshQuick() {
        quickList.removeAllViews();
        quickFirst = null;

        section("Network");
        wifiSub = addTile("Wi-Fi", wifiStatus(), new View.OnClickListener() {
            @Override public void onClick(View v) { toggleWifi(); }
        });
        addTile("Connection", networkStatus(), new View.OnClickListener() {
            @Override public void onClick(View v) { startSafe(new Intent(Settings.ACTION_WIRELESS_SETTINGS), "Not available on this TV"); }
        });
        shortcut("Choose a Wi-Fi network", "Opens the network list", Settings.ACTION_WIFI_SETTINGS);

        section("Inputs");
        boolean any = false;
        try {
            TvInputManager tim = (TvInputManager) getSystemService(Context.TV_INPUT_SERVICE);
            List<TvInputInfo> inputs = new ArrayList<TvInputInfo>();
            for (TvInputInfo info : tim.getTvInputList()) if (info.isPassthroughInput()) inputs.add(info);
            for (final TvInputInfo info : inputs) {
                String label = String.valueOf(info.loadLabel(this));
                final String id = info.getId();
                addTile(label, "Switch to this input", new View.OnClickListener() {
                    @Override public void onClick(View v) {
                        startSafe(new Intent(Intent.ACTION_VIEW, TvContract.buildChannelUriForPassthroughInput(id)), "Could not switch input");
                    }
                });
                any = true;
            }
        } catch (Throwable e) {
            Log.e("taxis", "inputs", e);
        }
        if (!any) {
            TextView n = text(14, MUTED, 1);
            n.setText("This TV does not report any HDMI inputs to apps.\nUse the INPUT or SOURCE button on your remote.");
            n.setPadding(dp(8), dp(4), 0, dp(8));
            quickList.addView(n);
        }

        section("Sound");
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        TextView[] ref = new TextView[1];
        LinearLayout down = tileView("Volume \u2212", volumeText(), new View.OnClickListener() {
            @Override public void onClick(View v) { changeVolume(AudioManager.ADJUST_LOWER); }
        }, ref);
        volSub = ref[0];
        LinearLayout up = tileView("Volume +", "louder", new View.OnClickListener() {
            @Override public void onClick(View v) { changeVolume(AudioManager.ADJUST_RAISE); }
        }, null);
        LinearLayout.LayoutParams h1 = new LinearLayout.LayoutParams(0, -2, 1f);
        h1.rightMargin = dp(4);
        LinearLayout.LayoutParams h2 = new LinearLayout.LayoutParams(0, -2, 1f);
        h2.leftMargin = dp(4);
        row.addView(down, h1);
        row.addView(up, h2);
        quickList.addView(row, new LinearLayout.LayoutParams(-1, -2));

        section("Shortcuts");
        shortcut("Bluetooth", "Pair remotes and headphones", Settings.ACTION_BLUETOOTH_SETTINGS);
        shortcut("Display", "Resolution, HDR and picture", Settings.ACTION_DISPLAY_SETTINGS);
        shortcut("Sound settings", "Audio output and surround", Settings.ACTION_SOUND_SETTINGS);
        shortcut("Date and time", "Clock and time zone", Settings.ACTION_DATE_SETTINGS);
    }

    private WifiManager wifi() { return (WifiManager) getApplicationContext().getSystemService(Context.WIFI_SERVICE); }

    private String wifiStatus() {
        try {
            WifiManager wm = wifi();
            if (!wm.isWifiEnabled()) return "Off   \u00B7   press OK to turn on";
            WifiInfo wi = wm.getConnectionInfo();
            String ssid = wi == null ? null : wi.getSSID();
            if (ssid != null && ssid.length() > 1 && !ssid.contains("unknown")) {
                ssid = ssid.replace("\"", "");
                String[] q = {"Weak", "Fair", "Good", "Excellent"};
                int lvl = WifiManager.calculateSignalLevel(wi.getRssi(), 4);
                return ssid + "   \u00B7   " + q[Math.max(0, Math.min(3, lvl))] + " signal   \u00B7   OK turns off";
            }
            return "On, not connected   \u00B7   OK turns off";
        } catch (Exception e) {
            return "Wi-Fi status unavailable";
        }
    }

    private String networkStatus() {
        try {
            ConnectivityManager cm = (ConnectivityManager) getSystemService(Context.CONNECTIVITY_SERVICE);
            NetworkInfo ni = cm.getActiveNetworkInfo();
            if (ni == null || !ni.isConnected()) return "Offline";
            if (ni.getType() == ConnectivityManager.TYPE_ETHERNET) return "Connected by Ethernet cable";
            if (ni.getType() == ConnectivityManager.TYPE_WIFI) return "Connected by Wi-Fi";
            return "Connected (" + ni.getTypeName() + ")";
        } catch (Exception e) {
            return "Status unavailable";
        }
    }

    private void toggleWifi() {
        boolean ok;
        try {
            WifiManager wm = wifi();
            boolean target = !wm.isWifiEnabled();
            ok = wm.setWifiEnabled(target);
            if (ok) wifiSub.setText(target ? "Turning on\u2026" : "Turning off\u2026");
        } catch (Exception e) {
            ok = false;
        }
        if (!ok) {
            Toast.makeText(this, "This TV does not let apps switch Wi-Fi. Opening Wi-Fi settings.", Toast.LENGTH_LONG).show();
            startSafe(new Intent(Settings.ACTION_WIFI_SETTINGS), "Not available on this TV");
            return;
        }
        handler.postDelayed(new Runnable() {
            @Override public void run() { if (mode == Mode.QUICK && wifiSub != null) wifiSub.setText(wifiStatus()); }
        }, 2500);
    }

    private String volumeText() {
        AudioManager am = (AudioManager) getSystemService(Context.AUDIO_SERVICE);
        return am.getStreamVolume(AudioManager.STREAM_MUSIC) + " / " + am.getStreamMaxVolume(AudioManager.STREAM_MUSIC);
    }

    private void changeVolume(int dir) {
        AudioManager am = (AudioManager) getSystemService(Context.AUDIO_SERVICE);
        am.adjustStreamVolume(AudioManager.STREAM_MUSIC, dir, AudioManager.FLAG_SHOW_UI);
        if (volSub != null) volSub.setText(volumeText());
    }

    // ------------------------------------------------------------------ weather
    /** Refreshes place and weather off the UI thread using the shared TV-location client. */
    private void refreshWeather(boolean force) {
        long now = System.currentTimeMillis();
        if (!force && now - lastWeatherFetch < 60000) return;
        lastWeatherFetch = now;
        new Thread() {
            @Override public void run() {
                try {
                    final WeatherClient.Result result = WeatherClient.fetch(MainActivity.this, prefs);
                    runOnUiThread(new Runnable() {
                        @Override public void run() {
                            setPlace(result.place);
                            applyWeather(result.tempC, result.code);
                        }
                    });
                    setStatus("Updated " + DateFormat.getTimeFormat(MainActivity.this).format(new Date()));
                } catch (Exception e) {
                    Log.e("taxis", "weather update failed", e);
                    setStatus(e instanceof java.io.IOException ? "No internet (weather)" : "Weather or location unavailable");
                    lastWeatherFetch = System.currentTimeMillis() - WEATHER_EVERY_MS + 5 * 60 * 1000; // retry in ~5 min
                }
            }
        }.start();
    }

    private void setPlace(String nm) {
        place = nm == null ? "" : nm;
        lPlace.setText(placeLabel());
        aPlace.setText(placeLabel());
    }

    private void applyWeather(double t, int code) {
        tempC = t;
        wmoCode = code;
        hasWeather = true;
        lTemp.setText(tempText());
        lCond.setText(condition(code));
        aWeather.setText(weatherLine());
    }

}
