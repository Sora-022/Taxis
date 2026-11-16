package com.taxis.launcher;

import android.Manifest;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.location.Address;
import android.location.Geocoder;
import android.location.Location;
import android.location.LocationManager;
import android.os.Build;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.util.List;
import java.util.Locale;

/** Weather and place lookup shared by Taxis Home and Taxis Idle. */
final class WeatherClient {
    private static final int MAX_RESPONSE_BYTES = 1024 * 1024;

    static final class Result {
        String place;
        double tempC;
        int code;
    }

    // Prevents construction because this class only provides shared weather helpers.
    private WeatherClient() { }

    /** Uses a chosen city, else the TV's network location, else IP location, then saves current weather. */
    static Result fetch(Context context, SharedPreferences prefs) throws Exception {
        double lat, lon;
        String city = prefs.getString("city", "");
        String name;
        String source;
        if (city.length() > 0) {
            double[] ll = new double[2];
            name = geocode(city, ll);
            lat = ll[0];
            lon = ll[1];
            source = "city";
        } else {
            Location device = lastKnownLocation(context);
            if (device != null) {
                lat = device.getLatitude();
                lon = device.getLongitude();
                name = reversePlace(context, lat, lon);
                source = "tv";
            } else {
                double[] ll = new double[2];
                name = locateByIp(ll);
                lat = ll[0];
                lon = ll[1];
                source = "ip";
            }
        }
        if (name.length() == 0) name = tzPlace();
        prefs.edit().putLong("lat", Double.doubleToLongBits(lat)).putLong("lon", Double.doubleToLongBits(lon))
                .putString("place", name).putString("location_source", source).apply();
        JSONObject j = new JSONObject(httpGet("https://api.open-meteo.com/v1/forecast?latitude=" + lat
                + "&longitude=" + lon + "&current=temperature_2m,weather_code&timezone=auto"));
        JSONObject cur = j.getJSONObject("current");
        Result r = new Result();
        r.place = name;
        r.tempC = cur.getDouble("temperature_2m");
        r.code = cur.getInt("weather_code");
        prefs.edit().putLong("temp", Double.doubleToLongBits(r.tempC)).putInt("code", r.code).apply();
        return r;
    }

    /** Returns the freshest location Android TV already knows without starting continuous tracking. */
    private static Location lastKnownLocation(Context context) {
        if (Build.VERSION.SDK_INT >= 23
                && context.checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            return null;
        }
        try {
            LocationManager manager = (LocationManager) context.getSystemService(Context.LOCATION_SERVICE);
            Location best = null;
            for (String provider : manager.getProviders(true)) {
                Location candidate = manager.getLastKnownLocation(provider);
                if (candidate != null && (best == null || candidate.getTime() > best.getTime())) best = candidate;
            }
            return best;
        } catch (RuntimeException error) {
            return null;
        }
    }

    /** Converts coordinates into a friendly locality using Android's configured network geocoder. */
    private static String reversePlace(Context context, double lat, double lon) {
        if (!Geocoder.isPresent()) return "";
        try {
            List<Address> addresses = new Geocoder(context, Locale.getDefault()).getFromLocation(lat, lon, 1);
            if (addresses == null || addresses.isEmpty()) return "";
            Address address = addresses.get(0);
            if (address.getLocality() != null) return address.getLocality();
            if (address.getSubAdminArea() != null) return address.getSubAdminArea();
            return address.getAdminArea() == null ? "" : address.getAdminArea();
        } catch (Exception error) {
            return "";
        }
    }

    /** Returns a readable place derived from the TV's time zone when no locality is available. */
    static String tzPlace() {
        String id = java.util.TimeZone.getDefault().getID();
        int i = id.indexOf('/');
        return (i >= 0 ? id.substring(i + 1) : id).replace('_', ' ');
    }

    /** Converts an Open-Meteo weather code into a short condition label. */
    static String condition(int c) {
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

    /** Resolves a user-entered city into coordinates through Open-Meteo. */
    private static String geocode(String city, double[] out) throws Exception {
        JSONObject j = new JSONObject(httpGet("https://geocoding-api.open-meteo.com/v1/search?count=1&language=en&name="
                + URLEncoder.encode(city, "UTF-8")));
        JSONArray r = j.getJSONArray("results");
        JSONObject o = r.getJSONObject(0);
        out[0] = o.getDouble("latitude");
        out[1] = o.getDouble("longitude");
        return o.optString("name", city);
    }

    /** Finds approximate coordinates from the TV's public IP when Android has no saved location. */
    private static String locateByIp(double[] out) throws Exception {
        try {
            JSONObject j = new JSONObject(httpGet("https://ipwho.is/"));
            if (j.optBoolean("success", true) && j.has("latitude")) {
                out[0] = j.getDouble("latitude");
                out[1] = j.getDouble("longitude");
                return j.optString("city", "");
            }
        } catch (Exception ignored) { }
        JSONObject j = new JSONObject(httpGet("https://ipapi.co/json/"));
        out[0] = j.getDouble("latitude");
        out[1] = j.getDouble("longitude");
        return j.optString("city", "");
    }

    /** Downloads one small JSON response with bounded connection and read timeouts. */
    private static String httpGet(String u) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(u).openConnection();
        c.setConnectTimeout(10000);
        c.setReadTimeout(10000);
        c.setRequestProperty("User-Agent", "taxis-launcher");
        try (InputStream in = c.getInputStream();
             ByteArrayOutputStream bo = new ByteArrayOutputStream()) {
            byte[] buf = new byte[4096];
            int n;
            while ((n = in.read(buf)) > 0) {
                if (bo.size() + n > MAX_RESPONSE_BYTES) throw new Exception("weather response is too large");
                bo.write(buf, 0, n);
            }
            return bo.toString("UTF-8");
        } finally {
            c.disconnect();
        }
    }
}
