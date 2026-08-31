package com.photovault.companion;

import android.Manifest;
import android.app.Activity;
import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.net.Uri;
import android.os.Bundle;
import android.os.ParcelFileDescriptor;
import android.provider.MediaStore;
import android.view.Gravity;
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

/**
 * Deliberately small, no-dependency companion proof of concept.
 * It is a read-only MediaStore source, authenticated by a fresh token on every
 * app launch. It is not a production pairing or TLS implementation.
 */
public final class MainActivity extends Activity {
    private static final int PORT = 8765;
    private static final int PERMISSIONS = 42;
    private TextView status;
    private MediaServer server;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout body = new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL); body.setPadding(36, 36, 36, 36);
        status = new TextView(this); status.setTextSize(16); status.setTextIsSelectable(true);
        Button restart = new Button(this); restart.setText("Start / refresh local sharing");
        restart.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { startWhenPermitted(); }
        });
        ScrollView scroll = new ScrollView(this); scroll.addView(status);
        body.addView(restart); body.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        setContentView(body);
        startWhenPermitted();
    }
    @Override public void onDestroy() { if (server != null) server.close(); super.onDestroy(); }

    private void startWhenPermitted() {
        List<String> missing = new ArrayList<>();
        if (android.os.Build.VERSION.SDK_INT >= 33) {
            if (checkSelfPermission(Manifest.permission.READ_MEDIA_IMAGES) != PackageManager.PERMISSION_GRANTED) missing.add(Manifest.permission.READ_MEDIA_IMAGES);
            if (checkSelfPermission(Manifest.permission.READ_MEDIA_VIDEO) != PackageManager.PERMISSION_GRANTED) missing.add(Manifest.permission.READ_MEDIA_VIDEO);
        }
        if (!missing.isEmpty()) { requestPermissions(missing.toArray(new String[0]), PERMISSIONS); status.setText("Grant Photos and Videos permission, then local sharing will start."); return; }
        if (server != null) server.close();
        try {
            server = new MediaServer(getContentResolver()); server.start();
            String ip = localIpv4();
            status.setText("PhotoVault Companion — read-only POC\n\n" +
                "Desktop URL: http://" + ip + ":" + PORT + "\n" +
                "Token: " + server.token + "\n\n" +
                "Run on the Mac:\n" +
                "PYTHONPATH=src python3 -m photovault.cli android-wifi devices --url http://" + ip + ":" + PORT + " --token " + server.token + "\n\n" +
                "The token changes whenever this app restarts. Keep this screen open while testing. No phone files can be changed through this server.");
        } catch (IOException e) { status.setText("Could not start local server: " + e); }
    }
    @Override public void onRequestPermissionsResult(int request, String[] p, int[] grants) { super.onRequestPermissionsResult(request,p,grants); if(request==PERMISSIONS) startWhenPermitted(); }

    private static String localIpv4() {
        try {
            Enumeration<NetworkInterface> all = NetworkInterface.getNetworkInterfaces();
            while (all.hasMoreElements()) for (InetAddress a : Collections.list(all.nextElement().getInetAddresses()))
                if (!a.isLoopbackAddress() && a instanceof Inet4Address) return a.getHostAddress();
        } catch (Exception ignored) { }
        return "PHONE_IP";
    }

    static final class MediaServer extends Thread {
        final ContentResolver resolver; final String token; final ServerSocket socket; volatile boolean running = true;
        MediaServer(ContentResolver resolver) throws IOException { this.resolver=resolver; token=randomToken(); socket=new ServerSocket(PORT); setName("PhotoVaultMediaServer"); }
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
                else if("/api/media".equals(path)) media(out,args);
                else if(path.startsWith("/api/media/")) object(out,path.substring(11),headers.get("range"));
                else reply(out,404,"application/json",jsonError("not found").getBytes(StandardCharsets.UTF_8));
            } catch (Exception e) { e.printStackTrace(); }
        }
        private void device(BufferedOutputStream out) throws IOException {
            int count=count(MediaStore.Files.getContentUri(MediaStore.VOLUME_EXTERNAL));
            String body="{\"ok\":true,\"device\":{\"manufacturer\":\""+escape(android.os.Build.MANUFACTURER)+"\",\"model\":\""+escape(android.os.Build.MODEL)+"\",\"friendly_name\":\""+escape(android.os.Build.MODEL)+"\",\"adapter\":\"android_companion_wifi\",\"media_count\":"+count+",\"capabilities\":[\"identity\",\"media_manifest\",\"range_read\"]}}";
            reply(out,200,"application/json",body.getBytes(StandardCharsets.UTF_8));
        }
        private int count(Uri uri) { try(Cursor c=resolver.query(uri,new String[]{MediaStore.Files.FileColumns._ID},mediaSelection(),null,null)){return c==null?0:c.getCount();} }
        private void media(BufferedOutputStream out,Map<String,String> args) throws IOException {
            int limit=Math.min(500,Math.max(1,integer(args.get("limit"),100))); List<String> rows=new ArrayList<>();
            String[] cols=columns(); Uri uri=MediaStore.Files.getContentUri(MediaStore.VOLUME_EXTERNAL);
            // MediaProvider on recent Android versions validates sort-order text and
            // rejects a hand-built "... LIMIT n" suffix. Use the public query
            // arguments instead so the endpoint works across Android releases.
            Bundle query=new Bundle();
            query.putString(ContentResolver.QUERY_ARG_SQL_SELECTION,mediaSelection());
            query.putString(ContentResolver.QUERY_ARG_SQL_SORT_ORDER,MediaStore.MediaColumns.DATE_MODIFIED+" DESC");
            query.putInt(ContentResolver.QUERY_ARG_LIMIT,limit);
            try(Cursor c=resolver.query(uri,cols,query,null)){
                while(c!=null&&c.moveToNext()) rows.add(mediaJson(c));
            }
            String body="{\"ok\":true,\"items\":["+String.join(",",rows)+"]}"; reply(out,200,"application/json",body.getBytes(StandardCharsets.UTF_8));
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
        private static void skipFully(FileInputStream f,long amount)throws IOException{while(amount>0){long n=f.skip(amount);if(n<=0)throw new IOException("cannot seek media");amount-=n;}}
        private static String[] columns(){return new String[]{MediaStore.MediaColumns._ID,MediaStore.MediaColumns.DISPLAY_NAME,MediaStore.MediaColumns.RELATIVE_PATH,MediaStore.MediaColumns.MIME_TYPE,MediaStore.MediaColumns.SIZE,MediaStore.MediaColumns.DATE_TAKEN,MediaStore.MediaColumns.DATE_MODIFIED,MediaStore.MediaColumns.WIDTH,MediaStore.MediaColumns.HEIGHT,MediaStore.MediaColumns.DURATION};}
        private static String mediaSelection(){return MediaStore.Files.FileColumns.MEDIA_TYPE+" IN ("+MediaStore.Files.FileColumns.MEDIA_TYPE_IMAGE+","+MediaStore.Files.FileColumns.MEDIA_TYPE_VIDEO+")";}
        private static String mediaJson(Cursor c){return "{\"object_id\":\""+c.getLong(0)+"\",\"name\":\""+escape(c.getString(1))+"\",\"relative_path\":\""+escape(c.getString(2))+"\",\"mime_type\":\""+escape(c.getString(3))+"\",\"size_bytes\":"+c.getLong(4)+",\"date_taken\":"+c.getLong(5)+",\"modified_at\":"+c.getLong(6)+",\"width\":"+c.getInt(7)+",\"height\":"+c.getInt(8)+",\"duration\":"+c.getLong(9)+"}";}
        private static void reply(BufferedOutputStream out,int status,String type,byte[] body)throws IOException{String h="HTTP/1.1 "+status+" OK\r\nContent-Type: "+type+"\r\nContent-Length: "+body.length+"\r\nConnection: close\r\n\r\n";out.write(h.getBytes(StandardCharsets.US_ASCII));out.write(body);out.flush();}
        private static String readLine(BufferedInputStream in)throws IOException{ByteArrayOutputStream b=new ByteArrayOutputStream();int x;while((x=in.read())>=0){if(x=='\n')break;if(x!='\r')b.write(x);}return x<0&&b.size()==0?null:b.toString("UTF-8");}
        private static Map<String,String> parseQuery(String q)throws Exception{Map<String,String> r=new HashMap<>();for(String s:q.split("&")){int i=s.indexOf('=');if(i>=0)r.put(URLDecoder.decode(s.substring(0,i),"UTF-8"),URLDecoder.decode(s.substring(i+1),"UTF-8"));}return r;}
        private static int integer(String s,int fallback){try{return Integer.parseInt(s);}catch(Exception e){return fallback;}}
        private static String escape(String s){return s==null?"":s.replace("\\","\\\\").replace("\"","\\\"").replace("\n","\\n");}
        private static String jsonError(String s){return "{\"ok\":false,\"error\":\""+escape(s)+"\"}";}
    }
}
