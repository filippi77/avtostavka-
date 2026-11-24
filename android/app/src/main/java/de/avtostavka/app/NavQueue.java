package de.avtostavka.app;

import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * Offene Stopps für das Mini-Fenster beim Navigieren.
 * Der erste Eintrag ist der aktuelle Stopp. Erledigungen werden als Ereignisse gesammelt,
 * bis die Web-App sie abholt (takeEvents) – so geht nichts verloren, auch wenn die App im Hintergrund schläft.
 */
final class NavQueue {
    private static final String PREFS = "nav_overlay";

    private NavQueue() {}

    private static SharedPreferences prefs(Context c) {
        return c.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    private static JSONArray arr(Context c, String key) {
        try {
            return new JSONArray(prefs(c).getString(key, "[]"));
        } catch (JSONException e) {
            return new JSONArray();
        }
    }

    private static void put(Context c, String key, JSONArray a) {
        prefs(c).edit().putString(key, a.toString()).apply();
    }

    static synchronized JSONArray queue(Context c) {
        return arr(c, "queue");
    }

    static synchronized JSONObject head(Context c) {
        return queue(c).optJSONObject(0);
    }

    static synchronized boolean canUndo(Context c) {
        return arr(c, "hist").length() > 0;
    }

    static synchronized int doneCount(Context c) {
        return arr(c, "hist").length();
    }

    /** Beschriftungen in der Sprache der App */
    static String label(Context c, String key, String def) {
        try {
            String v = new JSONObject(prefs(c).getString("labels", "{}")).optString(key, "");
            return v.isEmpty() ? def : v;
        } catch (JSONException e) {
            return def;
        }
    }

    static synchronized void start(Context c, JSONArray stops, JSONObject labels) {
        prefs(c).edit()
            .putString("queue", stops.toString())
            .putString("hist", "[]")
            .putString("labels", labels.toString())
            .apply();
    }

    static synchronized void clear(Context c) {
        prefs(c).edit().putString("queue", "[]").putString("hist", "[]").apply();
    }

    /** aktuellen Stopp abschließen ("delivered" / "failed"); liefert den nächsten Stopp oder null */
    static synchronized JSONObject act(Context c, String status) {
        JSONArray q = queue(c);
        JSONObject cur = q.optJSONObject(0);
        if (cur == null) return null;
        JSONArray rest = new JSONArray();
        for (int i = 1; i < q.length(); i++) rest.put(q.opt(i));
        JSONArray hist = arr(c, "hist");
        try {
            hist.put(new JSONObject().put("stop", cur).put("status", status));
        } catch (JSONException ignored) {}
        addEvent(c, cur.optString("id"), status);
        put(c, "queue", rest);
        put(c, "hist", hist);
        return rest.optJSONObject(0);
    }

    /** letzten Schritt zurücknehmen; liefert den wieder aktuellen Stopp oder null */
    static synchronized JSONObject undo(Context c) {
        JSONArray hist = arr(c, "hist");
        if (hist.length() == 0) return null;
        JSONObject last = hist.optJSONObject(hist.length() - 1);
        hist.remove(hist.length() - 1);
        JSONObject stop = last == null ? null : last.optJSONObject("stop");
        if (stop == null) return null;
        JSONArray q = new JSONArray();
        q.put(stop);
        JSONArray old = queue(c);
        for (int i = 0; i < old.length(); i++) q.put(old.opt(i));
        addEvent(c, stop.optString("id"), "pending");
        put(c, "queue", q);
        put(c, "hist", hist);
        return stop;
    }

    private static void addEvent(Context c, String id, String status) {
        JSONArray ev = arr(c, "events");
        try {
            ev.put(new JSONObject().put("id", id).put("status", status).put("at", System.currentTimeMillis()));
        } catch (JSONException ignored) {}
        put(c, "events", ev);
    }

    static synchronized JSONArray takeEvents(Context c) {
        JSONArray ev = arr(c, "events");
        put(c, "events", new JSONArray());
        return ev;
    }

    /**
     * Liste aus der App übernehmen (z. B. nach Änderungen dort). Der aktuelle Stopp bleibt vorne;
     * Stopps mit noch nicht abgeholten Ereignissen behalten den Stand des Mini-Fensters.
     */
    static synchronized void update(Context c, JSONArray stops) {
        Map<String, String> lastEv = new HashMap<>();
        JSONArray ev = arr(c, "events");
        for (int i = 0; i < ev.length(); i++) {
            JSONObject e = ev.optJSONObject(i);
            if (e != null) lastEv.put(e.optString("id"), e.optString("status"));
        }
        JSONArray old = queue(c);
        JSONObject head = old.optJSONObject(0);
        String headId = head == null ? "" : head.optString("id");
        JSONObject newHead = null;
        JSONArray rest = new JSONArray();
        Set<String> ids = new HashSet<>();
        for (int i = 0; i < stops.length(); i++) {
            JSONObject s = stops.optJSONObject(i);
            if (s == null) continue;
            String id = s.optString("id");
            ids.add(id);
            String st = lastEv.get(id);
            if (st != null && !"pending".equals(st)) continue; // im Mini-Fenster schon erledigt
            if (id.equals(headId)) newHead = s;
            else rest.put(s);
        }
        JSONArray q = new JSONArray();
        if (newHead != null) q.put(newHead);
        // im Mini-Fenster zurückgenommen, die App weiß es noch nicht
        for (int i = 0; i < old.length(); i++) {
            JSONObject s = old.optJSONObject(i);
            if (s != null && !ids.contains(s.optString("id")) && "pending".equals(lastEv.get(s.optString("id")))) q.put(s);
        }
        for (int i = 0; i < rest.length(); i++) q.put(rest.opt(i));
        put(c, "queue", q);
    }

    /** Navigation zum Stopp starten (Navi-App des Nutzers; sonst Google-Maps-Webadresse) */
    static void launch(Context c, JSONObject stop) {
        if (stop == null) return;
        if (!open(c, stop.optString("url"))) open(c, stop.optString("web"));
    }

    private static boolean open(Context c, String url) {
        if (url == null || url.isEmpty()) return false;
        try {
            Intent i = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            c.startActivity(i);
            return true;
        } catch (Exception e) {
            return false;
        }
    }
}
