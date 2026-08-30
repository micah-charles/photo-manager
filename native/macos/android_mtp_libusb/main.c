// Disposable libusb MTP transport proof of concept for macOS.
// It deliberately has no JSON daemon protocol yet: this program exists to
// isolate the USB boundary before it is allowed to replace the stable Python
// PhotoSource surface. It never sends a phone-side write/delete operation.
#include <libusb.h>
#include <ctype.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define VID 0x18d1
#define PID 0x4ee1
#define IN_EP 0x81
#define OUT_EP 0x01
#define IFACE 0
#define ROOT_QUERY 0xffffffffU
#define TIMEOUT_MS 15000
#define READ_SIZE (64 * 1024)

typedef struct { libusb_context *ctx; libusb_device_handle *dev; int claimed; int session; } Transport;
typedef struct { Transport *t; unsigned char buf[READ_SIZE]; int used; int pos; } Reader;
typedef struct { uint32_t id, parent, size; uint16_t format; char name[256]; } ObjectInfo;

static uint16_t u16(const unsigned char *p) { return (uint16_t)p[0] | ((uint16_t)p[1] << 8); }
static uint32_t u32(const unsigned char *p) { return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24); }
static void p16(unsigned char *p, uint16_t v) { p[0] = v; p[1] = v >> 8; }
static void p32(unsigned char *p, uint32_t v) { p[0] = v; p[1] = v >> 8; p[2] = v >> 16; p[3] = v >> 24; }
static int suffix(const char *name, const char *ext) { size_t a=strlen(name), b=strlen(ext); return a>=b && !strcasecmp(name+a-b, ext); }

static void close_transport(Transport *t) {
  if (!t) return;
  // This is intentionally state-gated. The OpenMTP crash showed that blindly
  // releasing an interface after a failed/poisoned lifecycle is unsafe.
  if (t->session && t->dev) {
    unsigned char close_cmd[12]; p32(close_cmd, 12); p16(close_cmd+4, 1); p16(close_cmd+6, 0x1003); p32(close_cmd+8, 0xffffffff);
    int n=0; (void)libusb_bulk_transfer(t->dev, OUT_EP, close_cmd, sizeof(close_cmd), &n, 1000);
  }
  if (t->claimed && t->dev) (void)libusb_release_interface(t->dev, IFACE);
  if (t->dev) libusb_close(t->dev);
  if (t->ctx) libusb_exit(t->ctx);
  memset(t, 0, sizeof(*t));
}

static int open_transport(Transport *t, char *why, size_t cap) {
  memset(t, 0, sizeof(*t));
  int rc=libusb_init(&t->ctx);
  if (rc) { snprintf(why,cap,"libusb_init=%s",libusb_error_name(rc)); return 0; }
  t->dev=libusb_open_device_with_vid_pid(t->ctx, VID, PID);
  if (!t->dev) { snprintf(why,cap,"Pixel MTP device %04x:%04x not found",VID,PID); close_transport(t); return 0; }
  rc=libusb_claim_interface(t->dev, IFACE);
  if (rc) { snprintf(why,cap,"libusb_claim_interface(0)=%s",libusb_error_name(rc)); close_transport(t); return 0; }
  t->claimed=1;
  return 1;
}

static int reader_fill(Reader *r, char *why, size_t cap) {
  int n=0, rc=libusb_bulk_transfer(r->t->dev, IN_EP, r->buf, sizeof(r->buf), &n, TIMEOUT_MS);
  if (rc || n<=0) { snprintf(why,cap,"bulk-in endpoint=0x81 rc=%s actual=%d",libusb_error_name(rc),n); return 0; }
  r->used=n; r->pos=0; return 1;
}
static int reader_read(Reader *r, void *out, size_t want, char *why, size_t cap) {
  unsigned char *dst=out;
  while (want) {
    if (r->pos==r->used && !reader_fill(r,why,cap)) return 0;
    size_t have=(size_t)(r->used-r->pos), take=have<want?have:want;
    memcpy(dst,r->buf+r->pos,take); r->pos+=(int)take; dst+=take; want-=take;
  }
  return 1;
}
static int send_command(Transport *t, uint16_t op, uint32_t tx, const uint32_t *params, size_t count, char *why, size_t cap) {
  unsigned char cmd[32]; size_t len=12+count*4; int sent=0;
  if (len>sizeof(cmd)) { snprintf(why,cap,"too many MTP parameters"); return 0; }
  p32(cmd,(uint32_t)len); p16(cmd+4,1); p16(cmd+6,op); p32(cmd+8,tx);
  for(size_t i=0;i<count;i++) p32(cmd+12+i*4,params[i]);
  int rc=libusb_bulk_transfer(t->dev,OUT_EP,cmd,(int)len,&sent,TIMEOUT_MS);
  if(rc || sent!=(int)len) { snprintf(why,cap,"bulk-out op=0x%04x rc=%s actual=%d",op,libusb_error_name(rc),sent); return 0; }
  return 1;
}
static int response(Reader *r, uint32_t tx, char *why, size_t cap) {
  unsigned char h[12];
  if(!reader_read(r,h,sizeof(h),why,cap)) return 0;
  uint32_t len=u32(h); uint16_t type=u16(h+4), code=u16(h+6); uint32_t got=u32(h+8);
  if(len<12) { snprintf(why,cap,"short response container"); return 0; }
  if(len>12) { unsigned char *discard=malloc(len-12); if(!discard) { snprintf(why,cap,"out of memory"); return 0; } int ok=reader_read(r,discard,len-12,why,cap); free(discard); if(!ok)return 0; }
  if(type!=3 || code!=0x2001 || got!=tx) { snprintf(why,cap,"MTP response type=%u code=0x%04x tx=%u expected=%u",type,code,got,tx); return 0; }
  return 1;
}
static int command_data(Transport *t, uint16_t op, uint32_t tx, const uint32_t *params, size_t count, unsigned char **payload, uint32_t *payload_len, char *why, size_t cap) {
  Reader r={.t=t}; unsigned char h[12]; *payload=NULL; *payload_len=0;
  if(!send_command(t,op,tx,params,count,why,cap) || !reader_read(&r,h,sizeof(h),why,cap)) return 0;
  uint32_t len=u32(h); uint16_t type=u16(h+4), code=u16(h+6), got=u32(h+8);
  if(type==3) { if(len>12){unsigned char *d=malloc(len-12);if(!d||!reader_read(&r,d,len-12,why,cap)){free(d);return 0;}free(d);} snprintf(why,cap,"MTP response 0x%04x",code); return 0; }
  if(len<12 || type!=2 || code!=op || got!=tx) { snprintf(why,cap,"invalid data container op=0x%04x type=%u code=0x%04x",op,type,code); return 0; }
  *payload_len=len-12; *payload=malloc(*payload_len ? *payload_len : 1);
  if(!*payload || !reader_read(&r,*payload,*payload_len,why,cap)) { free(*payload); *payload=NULL; return 0; }
  return response(&r,tx,why,cap);
}
static int open_session(Transport *t, char *why, size_t cap) {
  uint32_t sid=1; Reader r={.t=t};
  if(!send_command(t,0x1002,0,&sid,1,why,cap) || !response(&r,0,why,cap))return 0;
  t->session=1; return 1;
}
static int parse_name(const unsigned char *p, uint32_t n, char out[256]) {
  if(!n) { out[0]=0; return 1; } uint32_t chars=p[0]; if(chars==0 || 1+chars*2>n)return 0;
  uint32_t o=0; for(uint32_t i=0;i+1<chars && o<255;i++){ uint16_t c=u16(p+1+i*2); out[o++]=(c<128)?(char)c:'?'; } out[o]=0; return 1;
}
static int object_info(Transport *t, uint32_t tx, uint32_t id, ObjectInfo *info, char *why, size_t cap) {
  uint32_t p=id,n=0; unsigned char *d=NULL;
  if(!command_data(t,0x1008,tx,&p,1,&d,&n,why,cap))return 0;
  if(n<53){free(d);snprintf(why,cap,"ObjectInfo truncated");return 0;}
  memset(info,0,sizeof(*info)); info->id=id; info->format=u16(d+4); info->size=u32(d+8); info->parent=u32(d+38);
  int ok=parse_name(d+52,n-52,info->name); free(d); if(!ok)snprintf(why,cap,"ObjectInfo name malformed"); return ok;
}
static int handles(Transport *t,uint32_t tx,uint32_t storage,uint32_t parent,uint32_t **out,uint32_t *count,char *why,size_t cap){
  uint32_t p[3]={storage,0,parent},n=0;unsigned char*d=NULL;*out=NULL;*count=0;
  if(!command_data(t,0x1007,tx,p,3,&d,&n,why,cap))return 0;
  if(n<4 || (uint64_t)u32(d)*4+4>n){free(d);snprintf(why,cap,"GetObjectHandles malformed");return 0;}
  *count=u32(d);*out=malloc((size_t)*count*4);if(!*out){free(d);snprintf(why,cap,"out of memory");return 0;}memcpy(*out,d+4,(size_t)*count*4);free(d);return 1;
}
static int storage_id(Transport*t,uint32_t tx,uint32_t*out,char*why,size_t cap){unsigned char*d=NULL;uint32_t n=0;if(!command_data(t,0x1004,tx,NULL,0,&d,&n,why,cap))return 0;if(n<8||u32(d)<1){free(d);snprintf(why,cap,"no MTP storage");return 0;}*out=u32(d+4);free(d);return 1;}
static int child(Transport*t,uint32_t*tx,uint32_t storage,uint32_t parent,const char*name,ObjectInfo*out,char*why,size_t cap){uint32_t *ids=NULL,n=0;if(!handles(t,(*tx)++,storage,parent,&ids,&n,why,cap))return 0;for(uint32_t i=0;i<n;i++){ObjectInfo x;if(!object_info(t,(*tx)++,ids[i],&x,why,cap)){free(ids);return 0;}if(x.format==0x3001&&!strcasecmp(x.name,name)){*out=x;free(ids);return 1;}}free(ids);snprintf(why,cap,"folder not found: %s",name);return 0;}
static int stream_object(Transport*t,uint32_t tx,uint32_t id,uint64_t *written,char*why,size_t cap){Reader r={.t=t};unsigned char h[12];*written=0;uint32_t p=id;if(!send_command(t,0x1009,tx,&p,1,why,cap)||!reader_read(&r,h,12,why,cap))return 0;uint32_t len=u32(h);if(len<12||u16(h+4)!=2||u16(h+6)!=0x1009||u32(h+8)!=tx){snprintf(why,cap,"invalid GetObject data header");return 0;}uint64_t remaining=(uint64_t)len-12;unsigned char chunk[READ_SIZE];while(remaining){size_t take=remaining<sizeof(chunk)?(size_t)remaining:sizeof(chunk);if(!reader_read(&r,chunk,take,why,cap))return 0;if(fwrite(chunk,1,take,stdout)!=take){snprintf(why,cap,"stdout write failed");return 0;}remaining-=take;*written+=take;}return response(&r,tx,why,cap);}
static int find_media(Transport*t,uint32_t*tx,uint32_t storage,uint32_t parent,ObjectInfo*out,char*why,size_t cap){uint32_t*ids=NULL,n=0;if(!handles(t,(*tx)++,storage,parent,&ids,&n,why,cap))return 0;for(uint32_t i=0;i<n;i++){ObjectInfo x;if(!object_info(t,(*tx)++,ids[i],&x,why,cap)){free(ids);return 0;}if(suffix(x.name,".jpg")||suffix(x.name,".jpeg")){*out=x;free(ids);return 1;}}free(ids);snprintf(why,cap,"no JPEG found");return 0;}

int main(int argc,char **argv){
  int stream=argc>1&&!strcmp(argv[1],"--stream-test"); int probe=argc>1&&!strcmp(argv[1],"--probe");
  if(!stream&&!probe){fprintf(stderr,"usage: %s --probe | --stream-test [DCIM/Camera]\n",argv[0]);return 64;}
  Transport t;char why[512]={0};uint32_t tx=1,storage=0;int rc=3;
  if(!open_transport(&t,why,sizeof(why))){fprintf(stderr,"LIBUSB_MTP_FAIL\tstage=open\t%s\n",why);return rc;}
  if(!open_session(&t,why,sizeof(why))){fprintf(stderr,"LIBUSB_MTP_FAIL\tstage=open_session\t%s\n",why);goto done;}
  if(!storage_id(&t,tx++,&storage,why,sizeof(why))){fprintf(stderr,"LIBUSB_MTP_FAIL\tstage=storage\t%s\n",why);goto done;}
  if(probe){fprintf(stderr,"LIBUSB_MTP_PROBE_PASS\tstorage=%u\n",storage);rc=0;goto done;}
  ObjectInfo dcim,camera,media;
  if(!child(&t,&tx,storage,ROOT_QUERY,"DCIM",&dcim,why,sizeof(why))||!child(&t,&tx,storage,dcim.id,"Camera",&camera,why,sizeof(why))||!find_media(&t,&tx,storage,camera.id,&media,why,sizeof(why))){fprintf(stderr,"LIBUSB_MTP_FAIL\tstage=resolve\t%s\n",why);goto done;}
  uint64_t bytes=0;clock_t started=clock();
  if(!stream_object(&t,tx++,media.id,&bytes,why,sizeof(why))){fprintf(stderr,"LIBUSB_MTP_FAIL\tstage=stream\t%s\n",why);goto done;}
  fprintf(stderr,"LIBUSB_MTP_STREAM_PASS\tobject=%u\tname=%s\texpected=%u\treceived=%llu\telapsed=%.3f\n",media.id,media.name,media.size,(unsigned long long)bytes,(double)(clock()-started)/CLOCKS_PER_SEC);
  rc=(bytes==media.size)?0:4;
done: close_transport(&t); return rc;
}
