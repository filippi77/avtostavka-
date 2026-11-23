package de.avtostavka.app;

import android.content.Context;
import android.content.Intent;
import android.graphics.Rect;
import android.media.Image;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.util.Size;
import android.view.View;
import android.widget.Button;
import android.widget.ImageButton;
import android.widget.TextView;
import androidx.annotation.OptIn;
import androidx.appcompat.app.AppCompatActivity;
import androidx.camera.core.Camera;
import androidx.camera.core.CameraSelector;
import androidx.camera.core.ExperimentalGetImage;
import androidx.camera.core.ImageAnalysis;
import androidx.camera.core.ImageProxy;
import androidx.camera.core.Preview;
import androidx.camera.core.resolutionselector.ResolutionSelector;
import androidx.camera.core.resolutionselector.ResolutionStrategy;
import androidx.camera.lifecycle.ProcessCameraProvider;
import androidx.camera.view.PreviewView;
import androidx.core.content.ContextCompat;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowInsetsCompat;
import com.google.common.util.concurrent.ListenableFuture;
import com.google.mlkit.vision.common.InputImage;
import com.google.mlkit.vision.text.Text;
import com.google.mlkit.vision.text.TextRecognition;
import com.google.mlkit.vision.text.TextRecognizer;
import com.google.mlkit.vision.text.latin.TextRecognizerOptions;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.regex.Pattern;

/**
 * Kamera-Vorschau mit Live-Texterkennung (ML Kit, offline).
 * Sobald dieselbe Adresse in mehreren Bildern hintereinander erkannt wird,
 * wird sie automatisch übernommen (mit Vibration).
 */
public class ScannerActivity extends AppCompatActivity {

    public static final String EXTRA_LANG = "lang";
    public static final String EXTRA_TEXT = "text";
    public static final String EXTRA_CANDIDATE = "candidate";

    /** Wie viele Bilder hintereinander dieselbe Adresse zeigen müssen. */
    private static final int STABLE_FRAMES = 3;

    // PLZ + Ort: "10115 Berlin", "D-10115 Berlin", "1070 Wien"
    private static final Pattern PLZ_LINE = Pattern.compile("^(?:(?:D|DE|A|AT|CH)\\s?-\\s?)?\\d{4,5}\\s+\\p{Lu}.*");
    // Hausnummer am Zeilenende: "Hauptstraße 12a", "Weg 3-5"
    private static final Pattern STREET_LINE = Pattern.compile(".*\\p{L}{2,}.*\\s\\d{1,4}\\s?[a-zA-Z]?(\\s?[-/]\\s?\\d{1,4}[a-zA-Z]?)?$");
    private static final Pattern SENDER = Pattern.compile("(?i)^\\s*(absender|abs\\.|von\\s*:|from\\s*:|versender|return|rücksende|отправитель).*");
    private static final Pattern RECIPIENT = Pattern.compile("(?i)^\\s*(empfänger|an\\s*:|lieferadresse|lieferanschrift|ship\\s*to|deliver\\s*to|куда|получатель).*");

    private PreviewView previewView;
    private View frame;
    private TextView status;
    private TextView found;
    private Button take;
    private ImageButton torch;

    private TextRecognizer recognizer;
    private ExecutorService cameraExecutor;
    private Camera camera;
    private boolean torchOn = false;
    private volatile boolean finished = false;
    private volatile boolean busy = false;

    private String lastText = "";
    private String lastCandidate = "";
    private int stableCount = 0;
    private String lang = "de";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_scanner);
        lang = "ru".equals(getIntent().getStringExtra(EXTRA_LANG)) ? "ru" : "de";

        previewView = findViewById(R.id.preview);
        frame = findViewById(R.id.frame);
        status = findViewById(R.id.status);
        found = findViewById(R.id.found);
        take = findViewById(R.id.take);
        torch = findViewById(R.id.torch);
        TextView title = findViewById(R.id.title);

        title.setText(tr("Adresse scannen", "Сканирование адреса"));
        status.setText(tr("Kamera auf das Adressfeld richten", "Наведите камеру на адрес"));
        take.setText(tr("Text übernehmen", "Взять текст"));
        take.setEnabled(false);

        findViewById(R.id.close).setOnClickListener(v -> {
            setResult(RESULT_CANCELED);
            finish();
        });
        take.setOnClickListener(v -> deliver(lastText, lastCandidate));
        torch.setOnClickListener(v -> toggleTorch());

        // Edge-to-Edge: Bedienelemente nicht unter Statusleiste / Gestenleiste legen
        View root = findViewById(R.id.root);
        View topBar = findViewById(R.id.topBar);
        View bottom = findViewById(R.id.bottomCard);
        ViewCompat.setOnApplyWindowInsetsListener(root, (v, insets) -> {
            Insets bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() | WindowInsetsCompat.Type.displayCutout());
            topBar.setPadding(topBar.getPaddingLeft(), bars.top + dp(8), topBar.getPaddingRight(), topBar.getPaddingBottom());
            ((android.view.ViewGroup.MarginLayoutParams) bottom.getLayoutParams()).bottomMargin = bars.bottom + dp(12);
            bottom.requestLayout();
            return insets;
        });

        recognizer = TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS);
        cameraExecutor = Executors.newSingleThreadExecutor();
        startCamera();
    }

    private String tr(String de, String ru) {
        return "ru".equals(lang) ? ru : de;
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    private void startCamera() {
        ListenableFuture<ProcessCameraProvider> future = ProcessCameraProvider.getInstance(this);
        future.addListener(() -> {
            try {
                ProcessCameraProvider provider = future.get();
                Preview preview = new Preview.Builder().build();
                preview.setSurfaceProvider(previewView.getSurfaceProvider());

                ResolutionSelector selector = new ResolutionSelector.Builder()
                    .setResolutionStrategy(new ResolutionStrategy(new Size(1920, 1080), ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER))
                    .build();
                ImageAnalysis analysis = new ImageAnalysis.Builder()
                    .setResolutionSelector(selector)
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .build();
                analysis.setAnalyzer(cameraExecutor, this::analyze);

                provider.unbindAll();
                camera = provider.bindToLifecycle(this, CameraSelector.DEFAULT_BACK_CAMERA, preview, analysis);
                if (!camera.getCameraInfo().hasFlashUnit()) torch.setVisibility(View.GONE);
            } catch (Exception e) {
                status.setText(tr("Kamera nicht verfügbar: ", "Камера недоступна: ") + e.getMessage());
            }
        }, ContextCompat.getMainExecutor(this));
    }

    @OptIn(markerClass = ExperimentalGetImage.class)
    private void analyze(ImageProxy proxy) {
        Image media = proxy.getImage();
        if (media == null || finished || busy) {
            proxy.close();
            return;
        }
        busy = true;
        InputImage image = InputImage.fromMediaImage(media, proxy.getImageInfo().getRotationDegrees());
        recognizer
            .process(image)
            .addOnSuccessListener(this::onText)
            .addOnCompleteListener(t -> {
                busy = false;
                proxy.close();
            });
    }

    private void onText(Text result) {
        if (finished) return;
        String text = toLines(result);
        String candidate = findCandidate(text);
        if (!text.trim().isEmpty()) lastText = text;

        if (candidate != null && candidate.equals(lastCandidate)) {
            stableCount++;
        } else {
            stableCount = candidate != null ? 1 : 0;
        }
        if (candidate != null) lastCandidate = candidate;

        take.setEnabled(!lastText.trim().isEmpty());
        if (candidate != null) {
            found.setText(candidate.replace(", ", "\n"));
            found.setVisibility(View.VISIBLE);
            status.setText(tr("Adresse erkannt – Kamera ruhig halten…", "Адрес найден — держите камеру ровно…"));
            frame.setBackgroundResource(R.drawable.scan_frame_found);
            if (stableCount >= STABLE_FRAMES) deliver(text, candidate);
        } else {
            frame.setBackgroundResource(R.drawable.scan_frame);
            status.setText(lastText.trim().isEmpty()
                ? tr("Kamera auf das Adressfeld richten", "Наведите камеру на адрес")
                : tr("Text erkannt, aber noch keine Adresse (PLZ + Ort)…", "Текст виден, но адрес ещё не найден…"));
        }
    }

    /** Text in Lesereihenfolge (oben → unten, links → rechts), eine Zeile pro Textzeile. */
    private static String toLines(Text result) {
        List<Text.Line> lines = new ArrayList<>();
        for (Text.TextBlock block : result.getTextBlocks()) lines.addAll(block.getLines());
        Collections.sort(lines, (a, b) -> {
            Rect ra = a.getBoundingBox();
            Rect rb = b.getBoundingBox();
            if (ra == null || rb == null) return 0;
            int tol = Math.max(8, Math.min(ra.height(), rb.height()) / 2);
            if (Math.abs(ra.centerY() - rb.centerY()) > tol) return Integer.compare(ra.top, rb.top);
            return Integer.compare(ra.left, rb.left);
        });
        StringBuilder sb = new StringBuilder();
        for (Text.Line l : lines) sb.append(l.getText()).append('\n');
        return sb.toString();
    }

    /** Einfache Vorerkennung: Straße + PLZ/Ort, nicht im Absender-Block. Die genaue Analyse macht die Web-App. */
    static String findCandidate(String text) {
        String[] lines = text.split("\n");
        String best = null;
        boolean inSender = false;
        int senderLeft = 0;
        for (int i = 0; i < lines.length; i++) {
            String l = lines[i].trim();
            if (SENDER.matcher(l).matches()) {
                inSender = true;
                senderLeft = 5;
            } else if (RECIPIENT.matcher(l).matches()) {
                inSender = false;
            }
            boolean plz = PLZ_LINE.matcher(l).matches();
            if (plz && !inSender && i > 0) {
                String street = lines[i - 1].trim();
                if (STREET_LINE.matcher(street).matches() || street.toLowerCase().startsWith("packstation")) {
                    best = street + ", " + l;
                }
            }
            if (inSender && (plz || --senderLeft <= 0)) inSender = false;
        }
        return best;
    }

    private void deliver(String text, String candidate) {
        if (finished || text == null || text.trim().isEmpty()) return;
        finished = true;
        vibrate();
        Intent data = new Intent();
        data.putExtra(EXTRA_TEXT, text);
        data.putExtra(EXTRA_CANDIDATE, candidate == null ? "" : candidate);
        setResult(RESULT_OK, data);
        new Handler(Looper.getMainLooper()).postDelayed(this::finish, 150);
    }

    private void vibrate() {
        try {
            Vibrator v = (Vibrator) getSystemService(Context.VIBRATOR_SERVICE);
            if (v == null) return;
            if (Build.VERSION.SDK_INT >= 26) v.vibrate(VibrationEffect.createOneShot(60, VibrationEffect.DEFAULT_AMPLITUDE));
            else v.vibrate(60);
        } catch (Exception ignored) {}
    }

    private void toggleTorch() {
        if (camera == null) return;
        torchOn = !torchOn;
        camera.getCameraControl().enableTorch(torchOn);
        torch.setImageResource(torchOn ? R.drawable.ic_flash_on : R.drawable.ic_flash_off);
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        if (cameraExecutor != null) cameraExecutor.shutdown();
        if (recognizer != null) recognizer.close();
    }
}
