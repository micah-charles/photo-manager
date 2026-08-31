package com.photovault.companion;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.net.wifi.WifiManager;
import android.os.Handler;
import android.os.IBinder;
import android.os.PowerManager;
import android.os.SystemClock;

/** Owns a read-only local-sharing session independently of the Activity UI. */
public final class SharingService extends Service {
    static final String ACTION_START = "com.photovault.companion.START_SHARING";
    static final String ACTION_STOP = "com.photovault.companion.STOP_SHARING";
    static final String EXTRA_DURATION = "duration";
    static final long TEN_MINUTES = 10 * 60 * 1000L;
    static final long ONE_HOUR = 60 * 60 * 1000L;
    // Android 15 applies a six-hour per-24-hour budget to dataSync foreground services.
    static final long UNTIL_STOPPED = 0L;
    private static final long SYSTEM_MAXIMUM = 6 * 60 * 60 * 1000L;
    private static final int NOTIFICATION_ID = 1103;
    private static final String CHANNEL = "local_sharing";

    private static volatile Snapshot current;
    private final Handler handler = new Handler();
    private MainActivity.MediaServer server;
    private PowerManager.WakeLock cpuLock;
    private WifiManager.WifiLock wifiLock;
    private Runnable timeout;

    static final class Snapshot {
        final String token;
        final String durationLabel;
        Snapshot(String token, String durationLabel) { this.token = token; this.durationLabel = durationLabel; }
    }
    static Snapshot snapshot() { return current; }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_STOP.equals(intent.getAction())) { stopSharing(); return START_NOT_STICKY; }
        long requested = intent == null ? TEN_MINUTES : intent.getLongExtra(EXTRA_DURATION, TEN_MINUTES);
        long duration = requested == UNTIL_STOPPED ? SYSTEM_MAXIMUM : Math.min(Math.max(requested, TEN_MINUTES), SYSTEM_MAXIMUM);
        String label = requested == UNTIL_STOPPED ? "until stopped (system limit: about 6 hours)" : (duration == ONE_HOUR ? "1 hour" : "10 minutes");
        startForeground(NOTIFICATION_ID, notification(label), ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
        stopSessionResources();
        try {
            server = new MainActivity.MediaServer(getApplicationContext(), getContentResolver());
            server.start();
            acquireLocks();
            current = new Snapshot(server.token, label);
            timeout = new Runnable() { @Override public void run() { stopSharing(); } };
            handler.postAtTime(timeout, SystemClock.uptimeMillis() + duration);
            return START_NOT_STICKY;
        } catch (Exception error) {
            current = null;
            stopForeground(STOP_FOREGROUND_REMOVE);
            stopSelf();
            return START_NOT_STICKY;
        }
    }

    @Override public void onTimeout(int startId, int foregroundServiceType) { stopSharing(); }
    @Override public void onDestroy() { stopSessionResources(); current = null; super.onDestroy(); }
    @Override public IBinder onBind(Intent intent) { return null; }

    private void stopSharing() { stopSessionResources(); current = null; stopForeground(STOP_FOREGROUND_REMOVE); stopSelf(); }
    private void stopSessionResources() {
        if (timeout != null) { handler.removeCallbacks(timeout); timeout = null; }
        if (server != null) { server.close(); server = null; }
        if (wifiLock != null && wifiLock.isHeld()) wifiLock.release();
        if (cpuLock != null && cpuLock.isHeld()) cpuLock.release();
    }
    private void acquireLocks() {
        PowerManager power = (PowerManager) getSystemService(POWER_SERVICE);
        cpuLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "PhotoVault:local-sharing");
        cpuLock.acquire();
        WifiManager wifi = (WifiManager) getApplicationContext().getSystemService(Context.WIFI_SERVICE);
        wifiLock = wifi.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "PhotoVault:local-sharing");
        wifiLock.acquire();
    }
    private Notification notification(String label) {
        NotificationManager manager = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        manager.createNotificationChannel(new NotificationChannel(CHANNEL, "PhotoVault local sharing", NotificationManager.IMPORTANCE_LOW));
        PendingIntent stop = PendingIntent.getService(this, 1, new Intent(this, SharingService.class).setAction(ACTION_STOP), PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        PendingIntent open = PendingIntent.getActivity(this, 2, new Intent(this, MainActivity.class), PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(this, CHANNEL).setSmallIcon(android.R.drawable.stat_sys_upload)
            .setContentTitle("PhotoVault sharing active").setContentText(label + " — tap Stop to end")
            .setContentIntent(open).setOngoing(true).addAction(new Notification.Action.Builder(null, "Stop", stop).build()).build();
    }
}
