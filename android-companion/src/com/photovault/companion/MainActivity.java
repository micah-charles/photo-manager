package com.photovault.companion;

import android.Manifest;
import android.app.Activity;
import android.content.ContentResolver;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.media.ExifInterface;
import android.media.MediaMetadataRetriever;
import android.net.Uri;
import android.os.Bundle;
import android.os.ParcelFileDescriptor;
import android.provider.MediaStore;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.ByteArrayOutputStream;
import java.io.FileInputStream;
import java.io.IOException;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Enumeration;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Deliberately small, no-dependency companion proof of concept.
 * It is a read-only MediaStore source, authenticated by a fresh token on every
 * app launch. It is not a production pairing or TLS implementation.
 */
public final class MainActivity extends Activity {
    private static final int PORT = 8765;
    private static final int PERMISSIONS = 42;
    private static final String INSTALLATION_PREFS = "photovault_companion";
    private static final String INSTALLATION_ID = "installation_id";
    private static final Pattern ISO_6709 = Pattern.compile("^([+-]\\d+(?:\\.\\d+)?)([+-]\\d+(?:\\.\\d+)?)(?:[+-].*)?/$");
    private TextView status;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout body = new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL); body.setPadding(36, 36, 36, 36);
        status = new TextView(this); status.setTextSize(16); status.setTextIsSelectable(true);
        Button tenMinutes = shareButton("Share for 10 minutes", SharingService.TEN_MINUTES);
        Button oneHour = shareButton("Share for 1 hour", SharingService.ONE_HOUR);
        Button untilStopped = shareButton("Share until stopped (up to 6 hours)", SharingService.UNTIL_STOPPED);
        Button stop = new Button(this); stop.setText("Stop local sharing");
        stop.setOnClickListener(new View.OnClickListener() { @Override public void onClick(View v) { stopSharing(); } });
        ScrollView scroll = new ScrollView(this); scroll.addView(status);
        body.addView(tenMinutes); body.addView(oneHour); body.addView(untilStopped); body.addView(stop);
        body.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        setContentView(body);
        // Reopening the UI must not shorten or rotate an already-running session.
        if (SharingService.snapshot() == null) startWhenPermitted(SharingService.TEN_MINUTES); else showStatus();
    }

    private Button shareButton(String label, final long duration) {
        Button button = new Button(this); button.setText(label);
        button.setOnClickListener(new View.OnClickListener() { @Override public void onClick(View v) { startWhenPermitted(duration); } });
        return button;
    }

    private void startWhenPermitted(long duration) {
        List<String> missing = new ArrayList<>();
        if (android.os.Build.VERSION.SDK_INT >= 33) {
            if (checkSelfPermission(Manifest.permission.READ_MEDIA_IMAGES) != PackageManager.PERMISSION_GRANTED) missing.add(Manifest.permission.READ_MEDIA_IMAGES);
            if (checkSelfPermission(Manifest.permission.READ_MEDIA_VIDEO) != PackageManager.PERMISSION_GRANTED) missing.add(Manifest.permission.READ_MEDIA_VIDEO);
            if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) missing.add(Manifest.permission.POST_NOTIFICATIONS);
        }
        if (!missing.isEmpty()) { requestPermissions(missing.toArray(new String[0]), PERMISSIONS); status.setText("Grant Photos, Videos, and Notifications permission, then local sharing will start."); return; }
        Intent intent = new Intent(this, SharingService.class).setAction(SharingService.ACTION_START).putExtra(SharingService.EXTRA_DURATION, duration);
        startForegroundService(intent);
        status.postDelayed(new Runnable() { @Override public void run() { showStatus(); } }, 150);
    }
    private void stopSharing() { startService(new Intent(this, SharingService.class).setAction(SharingService.ACTION_STOP)); status.setText("Local sharing stopped. No phone files were changed."); }
    @Override public void onResume() { super.onResume(); showStatus(); }
    @Override public void onRequestPermissionsResult(int request, String[] p, int[] grants) { super.onRequestPermissionsResult(request,p,grants); if(request==PERMISSIONS) startWhenPermitted(SharingService.TEN_MINUTES); }

    private void showStatus() {
        SharingService.Snapshot snapshot = SharingService.snapshot();
        if (snapshot == null) { status.setText("Local sharing is stopped. Choose a sharing duration above."); return; }
        String ip = localIpv4();
        status.setText("PhotoVault Companion — read-only POC\n" +
            "Build: 0.9 — embedded-location fix\n\n" +
            "Status: sharing active — " + snapshot.durationLabel + "\n" +
            "Desktop URL: http://" + ip + ":" + PORT + "\n" +
            "Token: " + snapshot.token + "\n\n" +
            "Run on the Mac:\n" +
            "PYTHONPATH=src python3 -m photovault.cli android-wifi devices --url http://" + ip + ":" + PORT + " --token " + snapshot.token + "\n\n" +
            "You can turn the screen off: sharing stays active with a persistent notification. Stop it here or from that notification. No phone files can be changed through this server.");
    }

    private static String localIpv4() {
        try {
            Enumeration<NetworkInterface> all = NetworkInterface.getNetworkInterfaces();
            while (all.hasMoreElements()) for (InetAddress a : Collections.list(all.nextElement().getInetAddresses()))
                if (!a.isLoopbackAddress() && a instanceof Inet4Address) return a.getHostAddress();
        } catch (Exception ignored) { }
        return "PHONE_IP";
    }

    /** Stable for this installation; app data clear or uninstall creates a new ID. */
    static String installationId(Context context) {
        String value = context.getSharedPreferences(INSTALLATION_PREFS, MODE_PRIVATE).getString(INSTALLATION_ID, null);
        if (value != null && !value.isEmpty()) return value;
        value = UUID.randomUUID().toString();
        context.getSharedPreferences(INSTALLATION_PREFS, MODE_PRIVATE).edit().putString(INSTALLATION_ID, value).apply();
        return value;
    }

    static final class MediaServer extends Thread {
        final ContentResolver resolver; final String token; final String deviceId; final String appVersion; final ServerSocket socket; volatile boolean running = true;
        MediaServer(Context context, ContentResolver resolver) throws IOException { this.resolver=resolver; deviceId=installationId(context); appVersion=version(context); token=randomToken(); socket=new ServerSocket(PORT); setName("PhotoVaultMediaServer"); }
        @Override public void run() { while (running) try { final Socket s=socket.accept(); new Thread(new Runnable() { @Override public void run() { serve(s); } }, "PhotoVaultRequest").start(); } catch (IOException e) { if(running) e.printStackTrace(); } }
        void close() { running=false; try { socket.close(); } catch(IOException ignored) {} }
        private static String randomToken() { byte[] b=new byte[18]; new SecureRandom().nextBytes(b); StringBuilder s=new StringBuilder(); for(byte x:b)s.append(String.format(Locale.ROOT,"%02x",x)); return s.toString(); }

        private void serve(Socket socket) {
            try (Socket ignored=socket; BufferedInputStream in=new BufferedInputStream(socket.getInputStream()); BufferedOutputStream out=new BufferedOutputStream(socket.getOutputStream())) {
                String request=readLine(in); if(request==null) return; String[] first=request.split(" "); if(first.length<2 || !"GET".equals(first[0])) { reply(out,405,"text/plain","GET only".getBytes()); return; }
                Map<String,String> headers=new HashMap<>(); String line; while((line=readLine(in))!=null&&!line.isEmpty()){int i=line.indexOf(':');if(i>0)headers.put(line.substring(0,i).toLowerCase(Locale.ROOT),line.substring(i+1).trim());}
                String path=first[1]; int query=path.indexOf('?'); Map<String,String> args=parseQuery(query<0?"":path.substring(query+1)); path=query<0?path:path.substring(0,query);
                if(!token.equals(args.get("token"))) { reply(out,401,"application/json",jsonError("token required").getBytes(StandardCharsets.UTF_8)); return; }
                if("/api/device".equals(path)) device(out);
                else if("/api/folders".equals(path)) folders(out);
                else if("/api/media/count".equals(path)) mediaCount(out,args);
                else if("/api/media".equals(path)) media(out,args);
                else if(path.startsWith("/api/media/") && path.endsWith("/metadata")) embeddedMetadata(out,path.substring(11, path.length()-9));
                else if(path.startsWith("/api/media/")) object(out,path.substring(11),headers.get("range"));
                else reply(out,404,"application/json",jsonError("not found").getBytes(StandardCharsets.UTF_8));
            } catch (Exception e) { e.printStackTrace(); }
        }
        private void device(BufferedOutputStream out) throws IOException {
            int count=count(MediaStore.Files.getContentUri(MediaStore.VOLUME_EXTERNAL), mediaSelection(), null);
            String body="{\"ok\":true,\"device\":{\"device_id\":\""+escape(deviceId)+"\",\"manufacturer\":\""+escape(android.os.Build.MANUFACTURER)+"\",\"model\":\""+escape(android.os.Build.MODEL)+"\",\"friendly_name\":\""+escape(android.os.Build.MODEL)+"\",\"app_version\":\""+escape(appVersion)+"\",\"adapter\":\"android_companion_wifi\",\"media_count\":"+count+",\"capabilities\":[\"identity\",\"media_manifest\",\"range_read\",\"embedded_metadata\"]}}";
            reply(out,200,"application/json",body.getBytes(StandardCharsets.UTF_8));
        }
        private static String version(Context context) { try { return context.getPackageManager().getPackageInfo(context.getPackageName(), 0).versionName; } catch (Exception ignored) { return "unknown"; } }
        private void mediaCount(BufferedOutputStream out, Map<String,String> args) throws IOException {
            String relativePath=normalRelativePath(args.get("relative_path"));
            if(relativePath==null) { reply(out,400,"application/json",jsonError("relative_path required").getBytes(StandardCharsets.UTF_8)); return; }
            int count=count(MediaStore.Files.getContentUri(MediaStore.VOLUME_EXTERNAL), mediaSelection()+" AND "+MediaStore.MediaColumns.RELATIVE_PATH+" = ?", new String[]{relativePath});
            String body="{\"ok\":true,\"relative_path\":\""+escape(relativePath)+"\",\"count\":"+count+"}";
            reply(out,200,"application/json",body.getBytes(StandardCharsets.UTF_8));
        }
        private int count(Uri uri, String selection, String[] selectionArgs) { try(Cursor c=resolver.query(uri,new String[]{MediaStore.Files.FileColumns._ID},selection,selectionArgs,null)){return c==null?0:c.getCount();} }
        private void media(BufferedOutputStream out,Map<String,String> args) throws IOException {
            int limit=Math.min(500,Math.max(1,integer(args.get("limit"),100))); int offset=Math.max(0,integer(args.get("offset"),0)); List<String> rows=new ArrayList<>();
            String[] cols=columns(); Uri uri=MediaStore.Files.getContentUri(MediaStore.VOLUME_EXTERNAL);
            // MediaProvider on recent Android versions validates sort-order text and
            // rejects a hand-built "... LIMIT n" suffix. Use the public query
            // arguments instead so the endpoint works across Android releases.
            Bundle query=new Bundle();
            String relativePath=normalRelativePath(args.get("relative_path"));
            String selection=mediaSelection();
            if(relativePath!=null) {
                selection += " AND " + MediaStore.MediaColumns.RELATIVE_PATH + " = ?";
                query.putStringArray(ContentResolver.QUERY_ARG_SQL_SELECTION_ARGS,new String[]{relativePath});
            }
            query.putString(ContentResolver.QUERY_ARG_SQL_SELECTION,selection);
            String sort="oldest".equals(args.get("sort"))
                ? MediaStore.MediaColumns.DATE_TAKEN+" ASC, "+MediaStore.MediaColumns.DATE_MODIFIED+" ASC"
                : MediaStore.MediaColumns.DATE_MODIFIED+" DESC";
            query.putString(ContentResolver.QUERY_ARG_SQL_SORT_ORDER,sort);
            query.putInt(ContentResolver.QUERY_ARG_LIMIT,limit);
            query.putInt(ContentResolver.QUERY_ARG_OFFSET,offset);
            try(Cursor c=resolver.query(uri,cols,query,null)){
                while(c!=null&&c.moveToNext()) rows.add(mediaJson(c));
            }
            String body="{\"ok\":true,\"items\":["+String.join(",",rows)+"]}"; reply(out,200,"application/json",body.getBytes(StandardCharsets.UTF_8));
        }
        private void folders(BufferedOutputStream out) throws IOException {
            HashMap<String,FolderStats> totals=new HashMap<>();
            Uri uri=MediaStore.Files.getContentUri(MediaStore.VOLUME_EXTERNAL);
            String[] cols=new String[]{MediaStore.MediaColumns.RELATIVE_PATH,MediaStore.MediaColumns.SIZE,MediaStore.MediaColumns.MIME_TYPE};
            try(Cursor c=resolver.query(uri,cols,mediaSelection(),null,null)) {
                while(c!=null && c.moveToNext()) {
                    String path=normalRelativePath(c.getString(0)); if(path==null) path="/";
                    FolderStats stats=totals.get(path); if(stats==null){stats=new FolderStats(path); totals.put(path,stats);}
                    stats.count++; stats.bytes+=Math.max(0,c.getLong(1));
                    String mime=c.getString(2);
                    if(mime != null && mime.startsWith("video/")) stats.videos++; else stats.images++;
                }
            }
            List<FolderStats> rows=new ArrayList<>(totals.values());
            Collections.sort(rows, new java.util.Comparator<FolderStats>() { @Override public int compare(FolderStats a,FolderStats b){return a.path.compareTo(b.path);} });
            List<String> json=new ArrayList<>(); for(FolderStats row:rows) json.add(row.json());
            String body="{\"ok\":true,\"folders\":["+String.join(",",json)+"]}";
            reply(out,200,"application/json",body.getBytes(StandardCharsets.UTF_8));
        }
        private void object(BufferedOutputStream out,String text,String range) throws IOException {
            long id; try { id=Long.parseLong(text); } catch(NumberFormatException e){reply(out,400,"application/json",jsonError("bad id").getBytes());return;}
            Uri uri=MediaStore.Files.getContentUri(MediaStore.VOLUME_EXTERNAL,id); long size=-1; String mime="application/octet-stream";
            try(Cursor c=resolver.query(uri,new String[]{MediaStore.MediaColumns.SIZE,MediaStore.MediaColumns.MIME_TYPE},null,null,null)){if(c!=null&&c.moveToFirst()){size=c.getLong(0);mime=c.getString(1);}}
            if(size<0){reply(out,404,"application/json",jsonError("media not found").getBytes());return;}
            long start=0,end=size-1; if(range!=null&&range.startsWith("bytes=")){String[] p=range.substring(6).split("-",2);start=Long.parseLong(p[0]);if(p.length>1&&!p[1].isEmpty())end=Math.min(end,Long.parseLong(p[1]));}
            if(start<0||start>=size||end<start){reply(out,416,"text/plain",new byte[0]);return;}
            long length=end-start+1; String head=(range==null?"HTTP/1.1 200 OK\r\n":"HTTP/1.1 206 Partial Content\r\n")+"Content-Type: "+mime+"\r\nAccept-Ranges: bytes\r\nContent-Length: "+length+"\r\n"+(range==null?"":"Content-Range: bytes "+start+"-"+end+"/"+size+"\r\n")+"Connection: close\r\n\r\n"; out.write(head.getBytes(StandardCharsets.US_ASCII));
            try(ParcelFileDescriptor pfd=resolver.openFileDescriptor(uri,"r"); FileInputStream file=new FileInputStream(pfd.getFileDescriptor())) { skipFully(file,start); byte[] b=new byte[64*1024]; long left=length; while(left>0){int n=file.read(b,0,(int)Math.min(b.length,left));if(n<0)break;out.write(b,0,n);left-=n;} out.flush(); }
        }
        /**
         * Reads only embedded metadata from the original media descriptor.
         * This deliberately does not consult MediaStore latitude/longitude:
         * Android 10+ guarantees those indexed values are null for privacy.
         */
        private void embeddedMetadata(BufferedOutputStream out, String text) throws IOException {
            long id; try { id=Long.parseLong(text); } catch(NumberFormatException e){reply(out,400,"application/json",jsonError("bad id").getBytes());return;}
            Uri uri=MediaStore.Files.getContentUri(MediaStore.VOLUME_EXTERNAL,id); String mime=null;
            try(Cursor c=resolver.query(uri,new String[]{MediaStore.MediaColumns.MIME_TYPE},null,null,null)){if(c!=null&&c.moveToFirst()) mime=c.getString(0);}
            if(mime==null){reply(out,404,"application/json",jsonError("media not found").getBytes());return;}
            String location=null;
            try(ParcelFileDescriptor pfd=resolver.openFileDescriptor(uri,"r")) {
                if(mime.startsWith("image/")) {
                    ExifInterface exif=new ExifInterface(pfd.getFileDescriptor()); float[] coordinates=new float[2];
                    if(validExifCoordinates(exif, coordinates)) location=locationJson(coordinates[0],coordinates[1],"embedded_exif");
                } else if(mime.startsWith("video/")) {
                    MediaMetadataRetriever retriever=new MediaMetadataRetriever();
                    try { retriever.setDataSource(pfd.getFileDescriptor()); location=iso6709Location(retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_LOCATION)); }
                    finally { retriever.release(); }
                }
            } catch (Exception ignored) { /* unreadable or non-EXIF originals simply have no embedded location */ }
            String body="{\"ok\":true,\"object_id\":\""+id+"\",\"location\":"+(location==null?"null":location)+"}";
            reply(out,200,"application/json",body.getBytes(StandardCharsets.UTF_8));
        }
        private static String iso6709Location(String value) {
            if(value==null)return null; Matcher match=ISO_6709.matcher(value); if(!match.matches())return null;
            try { double latitude=Double.parseDouble(match.group(1)); double longitude=Double.parseDouble(match.group(2)); return validCoordinates(latitude,longitude)?locationJson(latitude,longitude,"embedded_video_metadata"):null; }
            catch(NumberFormatException ignored){return null;}
        }
        // Pixel files with an empty GPS IFD can make framework ExifInterface
        // report 0,0. Require the EXIF hemisphere references as well as finite
        // coordinates, preserving legitimate 0,0 captures with real N/E refs.
        private static boolean validExifCoordinates(ExifInterface exif, float[] coordinates) {
            if(!exif.getLatLong(coordinates) || !validCoordinates(coordinates[0],coordinates[1])) return false;
            String latitudeRef=exif.getAttribute(ExifInterface.TAG_GPS_LATITUDE_REF);
            String longitudeRef=exif.getAttribute(ExifInterface.TAG_GPS_LONGITUDE_REF);
            return ("N".equals(latitudeRef)||"S".equals(latitudeRef)) && ("E".equals(longitudeRef)||"W".equals(longitudeRef));
        }
        private static boolean validCoordinates(double latitude,double longitude){return !Double.isNaN(latitude)&&!Double.isInfinite(latitude)&&!Double.isNaN(longitude)&&!Double.isInfinite(longitude)&&latitude>=-90&&latitude<=90&&longitude>=-180&&longitude<=180;}
        private static String locationJson(double latitude,double longitude,String source){return "{\"latitude\":"+Double.toString(latitude)+",\"longitude\":"+Double.toString(longitude)+",\"source\":\""+source+"\"}";}
        private static void skipFully(FileInputStream f,long amount)throws IOException{while(amount>0){long n=f.skip(amount);if(n<=0)throw new IOException("cannot seek media");amount-=n;}}
        // Android 10+ deliberately returns null for MediaStore LATITUDE and
        // LONGITUDE. Embedded location is read from the source file on demand,
        // never inferred from this manifest endpoint.
        private static String[] columns(){return new String[]{MediaStore.MediaColumns._ID,MediaStore.MediaColumns.DISPLAY_NAME,MediaStore.MediaColumns.RELATIVE_PATH,MediaStore.MediaColumns.MIME_TYPE,MediaStore.MediaColumns.SIZE,MediaStore.MediaColumns.DATE_TAKEN,MediaStore.MediaColumns.DATE_MODIFIED,MediaStore.MediaColumns.WIDTH,MediaStore.MediaColumns.HEIGHT,MediaStore.MediaColumns.DURATION};}
        private static String normalRelativePath(String path){if(path==null)return null;path=path.trim();if(path.isEmpty())return null;return path.endsWith("/")?path:path+"/";}
        private static String mediaSelection(){return MediaStore.Files.FileColumns.MEDIA_TYPE+" IN ("+MediaStore.Files.FileColumns.MEDIA_TYPE_IMAGE+","+MediaStore.Files.FileColumns.MEDIA_TYPE_VIDEO+")";}
        private static String mediaJson(Cursor c){return "{\"object_id\":\""+c.getLong(0)+"\",\"name\":\""+escape(c.getString(1))+"\",\"relative_path\":\""+escape(c.getString(2))+"\",\"mime_type\":\""+escape(c.getString(3))+"\",\"size_bytes\":"+c.getLong(4)+",\"date_taken\":"+c.getLong(5)+",\"modified_at\":"+c.getLong(6)+",\"width\":"+c.getInt(7)+",\"height\":"+c.getInt(8)+",\"duration\":"+c.getLong(9)+"}";}
        private static void reply(BufferedOutputStream out,int status,String type,byte[] body)throws IOException{String h="HTTP/1.1 "+status+" OK\r\nContent-Type: "+type+"\r\nContent-Length: "+body.length+"\r\nConnection: close\r\n\r\n";out.write(h.getBytes(StandardCharsets.US_ASCII));out.write(body);out.flush();}
        private static String readLine(BufferedInputStream in)throws IOException{ByteArrayOutputStream b=new ByteArrayOutputStream();int x;while((x=in.read())>=0){if(x=='\n')break;if(x!='\r')b.write(x);}return x<0&&b.size()==0?null:b.toString("UTF-8");}
        private static Map<String,String> parseQuery(String q)throws Exception{Map<String,String> r=new HashMap<>();for(String s:q.split("&")){int i=s.indexOf('=');if(i>=0)r.put(URLDecoder.decode(s.substring(0,i),"UTF-8"),URLDecoder.decode(s.substring(i+1),"UTF-8"));}return r;}
        private static int integer(String s,int fallback){try{return Integer.parseInt(s);}catch(Exception e){return fallback;}}
        private static String escape(String s){return s==null?"":s.replace("\\","\\\\").replace("\"","\\\"").replace("\n","\\n");}
        private static String jsonError(String s){return "{\"ok\":false,\"error\":\""+escape(s)+"\"}";}
        private static final class FolderStats {
            final String path; int count; int images; int videos; long bytes;
            FolderStats(String path){this.path=path;}
            String json(){return "{\"relative_path\":\""+escape(path)+"\",\"count\":"+count+",\"images\":"+images+",\"videos\":"+videos+",\"size_bytes\":"+bytes+"}";}
        }
    }
}
