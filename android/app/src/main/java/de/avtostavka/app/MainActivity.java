package de.avtostavka.app;

import android.os.Bundle;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(LabelScannerPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
