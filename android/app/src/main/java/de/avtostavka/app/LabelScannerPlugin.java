package de.avtostavka.app;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import androidx.activity.result.ActivityResult;
import com.getcapacitor.JSObject;
import com.getcapacitor.PermissionState;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.ActivityCallback;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

/**
 * Live-Scanner für Versandetiketten: öffnet die Kamera, erkennt Text mit Google ML Kit
 * direkt auf dem Gerät und liefert den erkannten Text an die Web-App zurück.
 */
@CapacitorPlugin(
    name = "LabelScanner",
    permissions = { @Permission(strings = { Manifest.permission.CAMERA }, alias = "camera") }
)
public class LabelScannerPlugin extends Plugin {

    @PluginMethod
    public void scan(PluginCall call) {
        if (getPermissionState("camera") != PermissionState.GRANTED) {
            requestPermissionForAlias("camera", call, "cameraPermsCallback");
            return;
        }
        launch(call);
    }

    @PermissionCallback
    private void cameraPermsCallback(PluginCall call) {
        if (getPermissionState("camera") == PermissionState.GRANTED) {
            launch(call);
        } else {
            call.reject("Kamera-Berechtigung verweigert", "PERMISSION_DENIED");
        }
    }

    private void launch(PluginCall call) {
        Intent intent = new Intent(getContext(), ScannerActivity.class);
        intent.putExtra(ScannerActivity.EXTRA_LANG, call.getString("lang", "de"));
        startActivityForResult(call, intent, "scanResult");
    }

    @ActivityCallback
    private void scanResult(PluginCall call, ActivityResult result) {
        if (call == null) return;
        JSObject ret = new JSObject();
        Intent data = result.getData();
        if (result.getResultCode() == Activity.RESULT_OK && data != null) {
            ret.put("text", data.getStringExtra(ScannerActivity.EXTRA_TEXT));
            ret.put("candidate", data.getStringExtra(ScannerActivity.EXTRA_CANDIDATE));
            ret.put("cancelled", false);
        } else {
            ret.put("cancelled", true);
        }
        call.resolve(ret);
    }
}
