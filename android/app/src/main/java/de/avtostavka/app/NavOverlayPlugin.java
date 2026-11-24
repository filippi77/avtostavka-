package de.avtostavka.app;

import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import org.json.JSONArray;

/**
 * Mini-Fenster beim Navigieren (nur Android-App).
 * start({ stops, labels, launch }) · update({ stops }) · stop() · takeEvents() → { events }
 * status() → { overlay, running, notifications } · requestOverlay() · requestNotifications()
 * Ereignis "change": im Mini-Fenster wurde etwas erledigt → takeEvents() aufrufen.
 */
@CapacitorPlugin(name = "NavOverlay")
public class NavOverlayPlugin extends Plugin {

    @Override
    public void load() {
        NavOverlayService.onChange = () -> notifyListeners("change", new JSObject(), true);
    }

    @Override
    protected void handleOnDestroy() {
        NavOverlayService.onChange = null;
    }

    private boolean notificationsAllowed() {
        return Build.VERSION.SDK_INT < 33
            || ContextCompat.checkSelfPermission(getContext(), Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED;
    }

    @PluginMethod
    public void status(PluginCall call) {
        JSObject r = new JSObject();
        r.put("overlay", Settings.canDrawOverlays(getContext()));
        r.put("running", NavOverlayService.instance != null);
        r.put("notifications", notificationsAllowed());
        call.resolve(r);
    }

    @PluginMethod
    public void requestOverlay(PluginCall call) {
        try {
            Intent i = new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:" + getContext().getPackageName()));
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            getContext().startActivity(i);
        } catch (Exception e) {
            try {
                Intent i = new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION);
                i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                getContext().startActivity(i);
            } catch (Exception ignored) {}
        }
        call.resolve();
    }

    @PluginMethod
    public void requestNotifications(PluginCall call) {
        if (Build.VERSION.SDK_INT >= 33 && !notificationsAllowed() && getActivity() != null) {
            ActivityCompat.requestPermissions(getActivity(), new String[] { Manifest.permission.POST_NOTIFICATIONS }, 4712);
        }
        call.resolve();
    }

    @PluginMethod
    public void start(PluginCall call) {
        JSArray stops = call.getArray("stops");
        JSObject labels = call.getObject("labels", new JSObject());
        NavQueue.start(getContext(), stops == null ? new JSONArray() : stops, labels == null ? new JSObject() : labels);
        Intent i = new Intent(getContext(), NavOverlayService.class).setAction(NavOverlayService.ACTION_SHOW);
        try {
            ContextCompat.startForegroundService(getContext(), i);
        } catch (Exception e) {
            call.reject("Dienst konnte nicht starten: " + e.getMessage());
            return;
        }
        if (Boolean.TRUE.equals(call.getBoolean("launch", true))) {
            NavQueue.launch(getActivity() != null ? getActivity() : getContext(), NavQueue.head(getContext()));
        }
        call.resolve();
    }

    @PluginMethod
    public void update(PluginCall call) {
        JSArray stops = call.getArray("stops");
        if (stops != null) NavQueue.update(getContext(), stops);
        NavOverlayService.refreshIfRunning();
        call.resolve();
    }

    @PluginMethod
    public void stop(PluginCall call) {
        NavQueue.clear(getContext());
        NavOverlayService s = NavOverlayService.instance;
        if (s != null) s.stopAll();
        call.resolve();
    }

    @PluginMethod
    public void takeEvents(PluginCall call) {
        JSONArray ev = NavQueue.takeEvents(getContext());
        JSObject r = new JSObject();
        try {
            r.put("events", new JSArray(ev.toString()));
        } catch (Exception e) {
            r.put("events", new JSArray());
        }
        call.resolve(r);
    }
}
