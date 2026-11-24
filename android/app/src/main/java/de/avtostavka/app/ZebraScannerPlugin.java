package de.avtostavka.app;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.os.Bundle;
import androidx.core.content.ContextCompat;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/**
 * Hardware-Scanner von Zebra (TC56, TC5x, TC2x …) über DataWedge.
 *
 * Beim Start wird ein DataWedge-Profil "Delivery" für diese App angelegt:
 * Barcode-Eingang mit MaxiCode/Code128/DataMatrix/QR/PDF417, Ausgabe per Broadcast-Intent,
 * Tastatur-Ausgabe aus. Jeder Scan wird als Ereignis "scan" { data, type } an die Web-App gemeldet.
 */
@CapacitorPlugin(name = "ZebraScanner")
public class ZebraScannerPlugin extends Plugin {

    static final String ACTION = "de.avtostavka.app.SCAN";
    static final String DATAWEDGE = "com.symbol.datawedge";
    static final String DW_API = "com.symbol.datawedge.api.ACTION";
    static final String PROFILE = "Delivery";

    private BroadcastReceiver receiver;

    @Override
    public void load() {
        receiver = new BroadcastReceiver() {
            @Override
            public void onReceive(Context context, Intent intent) {
                if (!ACTION.equals(intent.getAction())) return;
                JSObject o = new JSObject();
                o.put("data", intent.getStringExtra("com.symbol.datawedge.data_string"));
                o.put("type", intent.getStringExtra("com.symbol.datawedge.label_type"));
                notifyListeners("scan", o, true);
            }
        };
        IntentFilter filter = new IntentFilter(ACTION);
        filter.addCategory(Intent.CATEGORY_DEFAULT);
        // DataWedge ist eine andere App → Empfänger muss exportiert sein
        ContextCompat.registerReceiver(getContext(), receiver, filter, ContextCompat.RECEIVER_EXPORTED);
        if (isDataWedgeInstalled()) configureProfile();
    }

    @Override
    protected void handleOnDestroy() {
        try {
            getContext().unregisterReceiver(receiver);
        } catch (Exception ignored) {}
    }

    private boolean isDataWedgeInstalled() {
        try {
            getContext().getPackageManager().getPackageInfo(DATAWEDGE, 0);
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    @PluginMethod
    public void isAvailable(PluginCall call) {
        JSObject r = new JSObject();
        r.put("available", isDataWedgeInstalled());
        call.resolve(r);
    }

    @PluginMethod
    public void configure(PluginCall call) {
        if (isDataWedgeInstalled()) configureProfile();
        call.resolve();
    }

    /** Scan per Software auslösen (Taste in der App) */
    @PluginMethod
    public void trigger(PluginCall call) {
        Intent i = new Intent();
        i.setAction(DW_API);
        i.putExtra("com.symbol.datawedge.api.SOFT_SCAN_TRIGGER", "TOGGLE_SCANNING");
        getContext().sendBroadcast(i);
        call.resolve();
    }

    /** Profil anlegen/aktualisieren. Ältere DataWedge-Versionen kennen nur ein Plugin pro Aufruf → drei Aufrufe. */
    private void configureProfile() {
        // 1) Profil + App-Zuordnung + Barcode-Eingang
        Bundle barcode = new Bundle();
        barcode.putString("PLUGIN_NAME", "BARCODE");
        barcode.putString("RESET_CONFIG", "true");
        Bundle bp = new Bundle();
        bp.putString("scanner_selection", "auto");
        bp.putString("scanner_input_enabled", "true");
        bp.putString("decoder_maxicode", "true");
        bp.putString("decoder_code128", "true");
        bp.putString("decoder_datamatrix", "true");
        bp.putString("decoder_qrcode", "true");
        bp.putString("decoder_pdf417", "true");
        barcode.putBundle("PARAM_LIST", bp);
        sendConfig(barcode, true);

        // 2) Ausgabe per Broadcast-Intent an diese App
        Bundle intentOut = new Bundle();
        intentOut.putString("PLUGIN_NAME", "INTENT");
        intentOut.putString("RESET_CONFIG", "true");
        Bundle ip = new Bundle();
        ip.putString("intent_output_enabled", "true");
        ip.putString("intent_action", ACTION);
        ip.putString("intent_category", Intent.CATEGORY_DEFAULT);
        ip.putString("intent_delivery", "2"); // 2 = Broadcast
        intentOut.putBundle("PARAM_LIST", ip);
        sendConfig(intentOut, false);

        // 3) Tastatur-Ausgabe aus (sonst landet der Code zusätzlich im Textfeld)
        Bundle keys = new Bundle();
        keys.putString("PLUGIN_NAME", "KEYSTROKE");
        keys.putString("RESET_CONFIG", "true");
        Bundle kp = new Bundle();
        kp.putString("keystroke_output_enabled", "false");
        keys.putBundle("PARAM_LIST", kp);
        sendConfig(keys, false);
    }

    private void sendConfig(Bundle plugin, boolean create) {
        Bundle profile = new Bundle();
        profile.putString("PROFILE_NAME", PROFILE);
        profile.putString("PROFILE_ENABLED", "true");
        profile.putString("CONFIG_MODE", create ? "CREATE_IF_NOT_EXIST" : "UPDATE");
        if (create) {
            Bundle app = new Bundle();
            app.putString("PACKAGE_NAME", getContext().getPackageName());
            app.putStringArray("ACTIVITY_LIST", new String[] { "*" });
            profile.putParcelableArray("APP_LIST", new Bundle[] { app });
        }
        profile.putBundle("PLUGIN_CONFIG", plugin);
        Intent i = new Intent();
        i.setAction(DW_API);
        i.putExtra("com.symbol.datawedge.api.SET_CONFIG", profile);
        getContext().sendBroadcast(i);
    }
}
