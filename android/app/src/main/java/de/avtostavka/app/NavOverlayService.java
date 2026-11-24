package de.avtostavka.app;

import android.annotation.SuppressLint;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.IBinder;
import android.provider.Settings;
import android.text.TextUtils;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.HapticFeedbackConstants;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewConfiguration;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import androidx.core.app.NotificationCompat;
import androidx.core.app.ServiceCompat;
import org.json.JSONObject;

/**
 * Mini-Fenster über der Navi-App: aktueller Stopp mit "Zugestellt" / "Nicht da".
 * Nach dem Abschließen springt es zum nächsten Stopp und startet die Navigation dorthin.
 * Läuft als Vordergrunddienst mit Benachrichtigung (dort dieselben Knöpfe – auch ohne Fenster-Erlaubnis).
 */
public class NavOverlayService extends Service {

    static final String ACTION_SHOW = "show";
    static final String ACTION_STOP = "stop";
    static final String CHANNEL = "nav_overlay";
    static final int NOTIF_ID = 4711;

    static volatile NavOverlayService instance;
    /** von der Web-App gesetzt: Bescheid geben, dass es neue Ereignisse gibt */
    static volatile Runnable onChange;

    // Farben wie in der App
    private static final int BROWN = 0xFF351C15;
    private static final int GOLD = 0xFFFFB500;
    private static final int GREEN = 0xFF2E7D32;
    private static final int RED = 0xFFC2410C;
    private static final int LIGHT = 0xFFF3EDE6;
    private static final int TEXT = 0xFF1C1C1E;
    private static final int MUTED = 0xFF6B6B70;

    private WindowManager wm;
    private FrameLayout root;
    private WindowManager.LayoutParams lp;
    private View bubble, card, actions;
    private TextView tBubble, tStep, tBadge, tTitle, tSub, tName, bUndo, bNav;
    private boolean expanded = true;

    /** Ereignis aus Fenster/Benachrichtigung: Anzeige auffrischen und die App informieren */
    static void changed(Context c) {
        NavOverlayService s = instance;
        if (s != null) s.refresh();
        Runnable r = onChange;
        if (r != null) r.run();
    }

    static void refreshIfRunning() {
        NavOverlayService s = instance;
        if (s != null) s.refresh();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void onCreate() {
        super.onCreate();
        instance = this;
        wm = (WindowManager) getSystemService(WINDOW_SERVICE);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        String a = intent != null ? intent.getAction() : null;
        if (ACTION_STOP.equals(a)) {
            NavQueue.clear(this);
            stopAll();
            return START_NOT_STICKY;
        }
        Notification n = buildNotification();
        int type = Build.VERSION.SDK_INT >= 34 ? ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE : 0;
        ServiceCompat.startForeground(this, NOTIF_ID, n, type);
        if (root == null && Settings.canDrawOverlays(this)) addOverlay();
        expanded = true;
        refresh();
        return START_NOT_STICKY;
    }

    void stopAll() {
        removeOverlay();
        ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE);
        stopSelf();
    }

    @Override
    public void onDestroy() {
        removeOverlay();
        instance = null;
        super.onDestroy();
    }

    // ---------- Aktionen ----------

    private void act(String status) {
        JSONObject next = NavQueue.act(this, status);
        changed(this);
        if (next != null) NavQueue.launch(this, next);
    }

    private void undo() {
        JSONObject cur = NavQueue.undo(this);
        changed(this);
        if (cur != null) NavQueue.launch(this, cur);
    }

    private void openApp() {
        Intent i = new Intent(this, MainActivity.class);
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_REORDER_TO_FRONT);
        try {
            startActivity(i);
        } catch (Exception ignored) {}
    }

    // ---------- Anzeige ----------

    void refresh() {
        JSONObject h = NavQueue.head(this);
        int left = NavQueue.queue(this).length();
        int done = NavQueue.doneCount(this);
        if (root != null) {
            bubble.setVisibility(expanded ? View.GONE : View.VISIBLE);
            card.setVisibility(expanded ? View.VISIBLE : View.GONE);
            tBubble.setText(h == null ? "✓" : String.valueOf(left));
            if (h == null) {
                tStep.setText(NavQueue.label(this, "all_done_head", "FERTIG"));
                tBadge.setVisibility(View.GONE);
                tTitle.setText(NavQueue.label(this, "all_done", "Alle Stopps erledigt"));
                tSub.setText("");
                tName.setVisibility(View.GONE);
                actions.setVisibility(View.GONE);
                bNav.setVisibility(View.GONE);
            } else {
                tStep.setText(NavQueue.label(this, "step", "STOPP {i} / {n}")
                    .replace("{i}", String.valueOf(done + 1))
                    .replace("{n}", String.valueOf(done + left)));
                String badge = h.optString("badge");
                tBadge.setText(badge);
                tBadge.setVisibility(badge.isEmpty() ? View.GONE : View.VISIBLE);
                tTitle.setText(h.optString("title"));
                tSub.setText(h.optString("sub"));
                String name = h.optString("name");
                tName.setText(name);
                tName.setVisibility(name.isEmpty() ? View.GONE : View.VISIBLE);
                actions.setVisibility(View.VISIBLE);
                bNav.setVisibility(View.VISIBLE);
            }
            bUndo.setVisibility(NavQueue.canUndo(this) ? View.VISIBLE : View.GONE);
            try {
                wm.updateViewLayout(root, lp);
            } catch (Exception ignored) {}
        }
        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        try {
            nm.notify(NOTIF_ID, buildNotification());
        } catch (Exception ignored) {}
    }

    private int dp(float v) {
        return Math.round(TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, getResources().getDisplayMetrics()));
    }

    private GradientDrawable shape(int color, float r) {
        GradientDrawable g = new GradientDrawable();
        g.setColor(color);
        g.setCornerRadius(dp(r));
        return g;
    }

    private TextView text(float sp, int color, boolean bold) {
        TextView t = new TextView(this);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        t.setTextColor(color);
        if (bold) t.setTypeface(Typeface.DEFAULT_BOLD);
        return t;
    }

    private TextView button(String label, int bg, int fg, float sp) {
        TextView b = text(sp, fg, true);
        b.setText(label);
        b.setGravity(Gravity.CENTER);
        b.setBackground(shape(bg, 12));
        b.setPadding(dp(10), 0, dp(10), 0);
        b.setMinHeight(dp(sp >= 15 ? 48 : 38));
        b.setSingleLine(true);
        return b;
    }

    private LinearLayout.LayoutParams weight(int marginStartDp) {
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f);
        p.setMarginStart(dp(marginStartDp));
        return p;
    }

    @SuppressLint("ClickableViewAccessibility")
    private void addOverlay() {
        root = new FrameLayout(this);

        // eingeklappt: runder Knopf mit Anzahl offener Stopps
        tBubble = text(20, GOLD, true);
        tBubble.setGravity(Gravity.CENTER);
        GradientDrawable circle = new GradientDrawable();
        circle.setShape(GradientDrawable.OVAL);
        circle.setColor(BROWN);
        circle.setStroke(dp(3), GOLD);
        tBubble.setBackground(circle);
        tBubble.setElevation(dp(6));
        bubble = tBubble;
        root.addView(bubble, new FrameLayout.LayoutParams(dp(58), dp(58)));

        // ausgeklappt: Karte
        LinearLayout c = new LinearLayout(this);
        c.setOrientation(LinearLayout.VERTICAL);
        c.setBackground(shape(Color.WHITE, 16));
        c.setElevation(dp(8));
        c.setClipToOutline(true);

        LinearLayout head = new LinearLayout(this);
        head.setOrientation(LinearLayout.HORIZONTAL);
        head.setGravity(Gravity.CENTER_VERTICAL);
        head.setBackgroundColor(BROWN);
        head.setPadding(dp(12), dp(6), dp(4), dp(6));
        tStep = text(12, GOLD, true);
        tStep.setLetterSpacing(0.06f);
        head.addView(tStep, new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
        tBadge = text(11, BROWN, true);
        tBadge.setBackground(shape(GOLD, 6));
        tBadge.setPadding(dp(6), dp(2), dp(6), dp(2));
        head.addView(tBadge);
        TextView bMin = text(22, Color.WHITE, true);
        bMin.setText("–");
        bMin.setGravity(Gravity.CENTER);
        head.addView(bMin, new LinearLayout.LayoutParams(dp(40), dp(32)));
        c.addView(head);

        LinearLayout body = new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL);
        body.setPadding(dp(12), dp(8), dp(12), dp(12));
        tTitle = text(19, TEXT, true);
        tTitle.setMaxLines(2);
        tTitle.setEllipsize(TextUtils.TruncateAt.END);
        tSub = text(14, MUTED, false);
        tName = text(13, MUTED, false);
        tName.setSingleLine(true);
        tName.setEllipsize(TextUtils.TruncateAt.END);
        body.addView(tTitle);
        body.addView(tSub);
        body.addView(tName);

        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setPadding(0, dp(10), 0, 0);
        TextView bDone = button("✓ " + NavQueue.label(this, "done", "Zugestellt"), GREEN, Color.WHITE, 15);
        TextView bFail = button(NavQueue.label(this, "fail", "Nicht da"), RED, Color.WHITE, 15);
        row.addView(bDone, weight(0));
        row.addView(bFail, weight(8));
        actions = row;
        body.addView(row);

        LinearLayout row2 = new LinearLayout(this);
        row2.setOrientation(LinearLayout.HORIZONTAL);
        row2.setPadding(0, dp(8), 0, 0);
        bUndo = button("↶", LIGHT, BROWN, 14);
        bNav = button("➤ " + NavQueue.label(this, "nav", "Navi"), LIGHT, BROWN, 14);
        TextView bApp = button(NavQueue.label(this, "app", "App"), LIGHT, BROWN, 14);
        TextView bEnd = button(NavQueue.label(this, "end", "Beenden"), LIGHT, MUTED, 14);
        LinearLayout.LayoutParams undoLp = new LinearLayout.LayoutParams(dp(44), LinearLayout.LayoutParams.WRAP_CONTENT);
        undoLp.setMarginEnd(dp(6));
        row2.addView(bUndo, undoLp);
        row2.addView(bNav, weight(0));
        row2.addView(bApp, weight(6));
        row2.addView(bEnd, weight(6));
        body.addView(row2);
        c.addView(body);
        card = c;
        root.addView(card, new FrameLayout.LayoutParams(dp(300), FrameLayout.LayoutParams.WRAP_CONTENT));

        click(bDone, () -> act("delivered"));
        click(bFail, () -> act("failed"));
        click(bUndo, this::undo);
        click(bNav, () -> NavQueue.launch(this, NavQueue.head(this)));
        click(bApp, this::openApp);
        click(bEnd, () -> {
            NavQueue.clear(this);
            stopAll();
        });
        // Kopfzeile und Knopf: ziehen zum Verschieben, tippen zum Ein-/Ausklappen
        drag(head, () -> { expanded = false; refresh(); });
        drag(bubble, () -> { expanded = true; refresh(); });

        int type = Build.VERSION.SDK_INT >= 26
            ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            : WindowManager.LayoutParams.TYPE_PHONE;
        lp = new WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            type,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT);
        lp.gravity = Gravity.TOP | Gravity.START;
        lp.x = dp(8);
        lp.y = dp(140);
        try {
            wm.addView(root, lp);
        } catch (Exception e) {
            root = null; // keine Erlaubnis → nur Benachrichtigung
        }
    }

    private void removeOverlay() {
        if (root != null) {
            try {
                wm.removeView(root);
            } catch (Exception ignored) {}
            root = null;
        }
    }

    private void click(View v, Runnable r) {
        v.setOnClickListener((x) -> {
            x.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY);
            r.run();
        });
    }

    @SuppressLint("ClickableViewAccessibility")
    private void drag(View v, Runnable onTap) {
        final int slop = ViewConfiguration.get(this).getScaledTouchSlop();
        v.setOnTouchListener(new View.OnTouchListener() {
            float sx, sy;
            int ox, oy;
            boolean moved;

            @Override
            public boolean onTouch(View view, MotionEvent e) {
                switch (e.getActionMasked()) {
                    case MotionEvent.ACTION_DOWN:
                        sx = e.getRawX();
                        sy = e.getRawY();
                        ox = lp.x;
                        oy = lp.y;
                        moved = false;
                        return true;
                    case MotionEvent.ACTION_MOVE:
                        float dx = e.getRawX() - sx, dy = e.getRawY() - sy;
                        if (!moved && Math.hypot(dx, dy) > slop) moved = true;
                        if (moved && root != null) {
                            lp.x = Math.max(0, ox + Math.round(dx));
                            lp.y = Math.max(0, oy + Math.round(dy));
                            try {
                                wm.updateViewLayout(root, lp);
                            } catch (Exception ignored) {}
                        }
                        return true;
                    case MotionEvent.ACTION_UP:
                        if (!moved) {
                            view.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY);
                            onTap.run();
                        }
                        return true;
                    default:
                        return false;
                }
            }
        });
    }

    // ---------- Benachrichtigung ----------

    private PendingIntent actionIntent(String action, int code) {
        Intent i = new Intent(this, NavActionActivity.class).setAction(action);
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_NO_ANIMATION);
        return PendingIntent.getActivity(this, code, i, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
    }

    private Notification buildNotification() {
        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= 26 && nm.getNotificationChannel(CHANNEL) == null) {
            NotificationChannel ch = new NotificationChannel(CHANNEL, NavQueue.label(this, "channel", "Stopps beim Navigieren"), NotificationManager.IMPORTANCE_LOW);
            ch.setShowBadge(false);
            nm.createNotificationChannel(ch);
        }
        JSONObject h = NavQueue.head(this);
        int left = NavQueue.queue(this).length();
        Intent open = new Intent(this, MainActivity.class);
        open.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_REORDER_TO_FRONT);
        PendingIntent openPi = PendingIntent.getActivity(this, 10, open, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        PendingIntent stopPi = PendingIntent.getService(this, 11,
            new Intent(this, NavOverlayService.class).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);

        NotificationCompat.Builder b = new NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_nav)
            .setColor(GOLD)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setShowWhen(false)
            .setCategory(NotificationCompat.CATEGORY_NAVIGATION)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setContentIntent(openPi);
        if (h == null) {
            b.setContentTitle(NavQueue.label(this, "all_done", "Alle Stopps erledigt"));
        } else {
            String badge = h.optString("badge");
            b.setContentTitle((badge.isEmpty() ? "" : badge + " · ") + h.optString("title"));
            String sub = h.optString("sub");
            String leftTxt = NavQueue.label(this, "left", "{n} offen").replace("{n}", String.valueOf(left));
            b.setContentText(sub.isEmpty() ? leftTxt : sub + " · " + leftTxt);
            b.addAction(0, "✓ " + NavQueue.label(this, "done", "Zugestellt"), actionIntent("done", 1));
            b.addAction(0, NavQueue.label(this, "fail", "Nicht da"), actionIntent("fail", 2));
        }
        b.addAction(0, NavQueue.label(this, "end", "Beenden"), stopPi);
        return b.build();
    }
}
