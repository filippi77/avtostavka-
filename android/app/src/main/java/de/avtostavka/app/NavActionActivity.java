package de.avtostavka.app;

import android.app.Activity;
import android.os.Bundle;
import org.json.JSONObject;

/**
 * Unsichtbare Activity für die Knöpfe in der Benachrichtigung ("Zugestellt", "Nicht da").
 * Seit Android 12 darf nur eine direkt aus der Benachrichtigung gestartete Activity die Navi-App öffnen.
 */
public class NavActionActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        String a = getIntent() != null ? getIntent().getAction() : null;
        JSONObject next = null;
        if ("done".equals(a)) next = NavQueue.act(this, "delivered");
        else if ("fail".equals(a)) next = NavQueue.act(this, "failed");
        else if ("nav".equals(a)) next = NavQueue.head(this);
        NavOverlayService.changed(this);
        if (next != null) NavQueue.launch(this, next);
        finish();
        overridePendingTransition(0, 0);
    }
}
