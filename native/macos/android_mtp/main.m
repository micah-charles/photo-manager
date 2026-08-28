#import <Foundation/Foundation.h>
#import <IOKit/IOKitLib.h>
#import <IOUSBHost/IOUSBHost.h>
#import <CommonCrypto/CommonDigest.h>
#import <string.h>

static const NSUInteger kMax = 1024 * 1024;
static const uint32_t kRootQuery = 0xffffffff;
static const NSTimeInterval kTimeout = 5.0;
static uint32_t gTx = 1;
static IOUSBHostInterface *gInterface;
static IOUSBHostPipe *gIn;
static IOUSBHostPipe *gOut;
static BOOL gOpen = NO;

static uint16_t U16(const uint8_t *p) { return p[0] | ((uint16_t)p[1] << 8); }
static uint32_t U32(const uint8_t *p) { return p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24); }
static uint64_t U64(const uint8_t *p) { uint64_t v=0; for (int i=0;i<8;i++) v |= (uint64_t)p[i] << (8*i); return v; }
static void P32(NSMutableData *d, uint32_t v) { uint8_t p[4]={v,v>>8,v>>16,v>>24}; [d appendBytes:p length:4]; }
static BOOL Bytes(NSData *d, NSUInteger *o, NSUInteger n, const uint8_t **p) {
    if (*o > d.length || n > d.length - *o) return NO; *p=d.bytes+*o; *o+=n; return YES;
}
static NSString *MTPString(NSData *d, NSUInteger *o) {
    const uint8_t *p; if (!Bytes(d,o,1,&p)) return nil; uint8_t n=p[0];
    if (n > 255 || !Bytes(d,o,(NSUInteger)n*2,&p)) return nil;
    NSMutableString *s=[NSMutableString string];
    for (NSUInteger i=0;i+1<n;i++) { uint16_t c=U16(p+i*2); if (!c) break; [s appendFormat:@"%C",(unichar)c]; }
    return s;
}
static NSDictionary *Error(NSString *s) { return @{@"ok":@NO,@"error":s}; }
static void Reply(NSDictionary *obj) {
    NSData *data=[NSJSONSerialization dataWithJSONObject:obj options:0 error:nil];
    fwrite(data.bytes,1,data.length,stdout); fputc('\n',stdout); fflush(stdout);
}
static io_service_t FindInterface(void) {
    CFMutableDictionaryRef m=[IOUSBHostInterface createMatchingDictionaryWithVendorID:@0x18d1 productID:@0x4ee1 bcdDevice:nil interfaceNumber:@0 configurationValue:@1 interfaceClass:@0x06 interfaceSubclass:@0x01 interfaceProtocol:@0x01 speed:nil productIDArray:nil];
    return m ? IOServiceGetMatchingService(kIOMainPortDefault,m) : IO_OBJECT_NULL;
}
static BOOL Receive(NSData **result, NSError **error) {
    NSMutableData *buffer=[NSMutableData dataWithLength:kMax]; NSUInteger n=0; NSError *e=nil;
    if (![gIn sendIORequestWithData:buffer bytesTransferred:&n completionTimeout:kTimeout error:&e]) { if(error)*error=e; return NO; }
    [buffer setLength:n]; *result=buffer; return YES;
}
static BOOL Parse(NSData *d, uint16_t *type, uint16_t *code, uint32_t *tx, NSData **payload, NSError **error) {
    if (d.length<12) { if(error)*error=[NSError errorWithDomain:@"MTP" code:1 userInfo:@{NSLocalizedDescriptionKey:@"short container"}]; return NO; }
    const uint8_t *p=d.bytes; uint32_t len=U32(p);
    if (len<12 || len>kMax || len>d.length) { if(error)*error=[NSError errorWithDomain:@"MTP" code:2 userInfo:@{NSLocalizedDescriptionKey:@"invalid container length"}]; return NO; }
    *type=U16(p+4); *code=U16(p+6); *tx=U32(p+8); *payload=len>12?[d subdataWithRange:NSMakeRange(12,len-12)]:[NSData data]; return YES;
}
static BOOL Command(uint16_t op, uint32_t tx, NSArray<NSNumber *> *params, NSData **dataPayload, NSError **error) {
    NSMutableData *cmd=[NSMutableData data]; P32(cmd,12+(uint32_t)params.count*4); uint8_t commandType[2]={1,0}; [cmd appendBytes:commandType length:2]; uint8_t c[2]={op,op>>8}; [cmd appendBytes:c length:2]; P32(cmd,tx);
    for(NSNumber *n in params) P32(cmd,n.unsignedIntValue);
    NSMutableData *out=[cmd mutableCopy]; NSUInteger sent=0; NSError *e=nil;
    if (![gOut sendIORequestWithData:out bytesTransferred:&sent completionTimeout:kTimeout error:&e]) { if(error)*error=e; return NO; }
    NSData *raw; if(!Receive(&raw,error)) return NO; uint16_t ctype,code; uint32_t rtx; NSData *payload;
    if(!Parse(raw,&ctype,&code,&rtx,&payload,error) || rtx!=tx) return NO;
    if(ctype==2) {
        if (code!=op) { if(error)*error=[NSError errorWithDomain:@"MTP" code:3 userInfo:@{NSLocalizedDescriptionKey:@"unexpected data code"}]; return NO; }
        *dataPayload=payload; if(!Receive(&raw,error)) return NO; if(!Parse(raw,&ctype,&code,&rtx,&payload,error)) return NO;
    } else *dataPayload=nil;
    if(ctype!=3 || code!=0x2001 || rtx!=tx) { if(error)*error=[NSError errorWithDomain:@"MTP" code:4 userInfo:@{NSLocalizedDescriptionKey:[NSString stringWithFormat:@"MTP response 0x%04x",code]}]; return NO; }
    return YES;
}
static BOOL Open(NSError **error) {
    io_service_t service=FindInterface(); if(!service){if(error)*error=[NSError errorWithDomain:@"MTP" code:5 userInfo:@{NSLocalizedDescriptionKey:@"Pixel MTP interface not found"}];return NO;}
    NSError *e=nil; gInterface=[[IOUSBHostInterface alloc] initWithIOService:service options:IOUSBHostObjectInitOptionsNone queue:nil error:&e interestHandler:nil]; IOObjectRelease(service);
    if(!gInterface){if(error)*error=e;return NO;} gIn=[gInterface copyPipeWithAddress:0x81 error:&e]; gOut=[gInterface copyPipeWithAddress:0x01 error:&e]; if(!gIn||!gOut){if(error)*error=e;return NO;}
    NSMutableData *session=[NSMutableData data]; P32(session,1);
    NSMutableData *cmd=[NSMutableData data]; P32(cmd,16); uint8_t t[2]={1,0};[cmd appendBytes:t length:2];uint8_t c[2]={2,0x10};[cmd appendBytes:c length:2];P32(cmd,0);[cmd appendData:session];
    NSUInteger sent=0; if(![gOut sendIORequestWithData:cmd bytesTransferred:&sent completionTimeout:kTimeout error:&e]){if(error)*error=e;return NO;}
    NSData *raw; if(!Receive(&raw,&e)){if(error)*error=e;return NO;} uint16_t ty,co;uint32_t rt;NSData *pl;if(!Parse(raw,&ty,&co,&rt,&pl,&e)||ty!=3||co!=0x2001){if(error)*error=e;return NO;} gOpen=YES; return YES;
}
static void Close(void) {
    if(!gOpen)return; NSError *e=nil; Command(0x1003,gTx++,@[],NULL,&e); [gInterface destroy]; gInterface=nil;gIn=nil;gOut=nil;gOpen=NO;
}
static NSDictionary *DeviceInfo(void) {
    NSError *e=nil; NSData *d=nil; if(!Command(0x1001,gTx++,@[],&d,&e))return Error(e.localizedDescription);
    NSUInteger o=0;const uint8_t*p;if(!Bytes(d,&o,8,&p))return Error(@"DeviceInfo truncated"); NSString *ext=MTPString(d,&o);if(!ext||!Bytes(d,&o,2,&p))return Error(@"DeviceInfo header truncated");
    for(int i=0;i<5;i++){if(!Bytes(d,&o,4,&p))return Error(@"DeviceInfo array truncated");uint32_t n=U32(p);if(n>4096||!Bytes(d,&o,n*2,&p))return Error(@"DeviceInfo array invalid");}
    NSString *manufacturer=MTPString(d,&o),*model=MTPString(d,&o),*version=MTPString(d,&o),*serial=MTPString(d,&o);if(!manufacturer||!model||!version||!serial)return Error(@"DeviceInfo strings truncated");
    unsigned char digest[CC_SHA256_DIGEST_LENGTH];CC_SHA256(serial.UTF8String,(CC_LONG)strlen(serial.UTF8String),digest);NSMutableString *fp=[NSMutableString string];for(int i=0;i<12;i++)[fp appendFormat:@"%02x",digest[i]];
    return @{@"ok":@YES,@"device":@{@"manufacturer":manufacturer,@"model":model,@"friendly_name":model,@"vid":@0x18d1,@"pid":@0x4ee1,@"serial_fingerprint":fp}};
}
static NSDictionary *Storages(void) {
    NSError *e=nil;NSData*d=nil;if(!Command(0x1004,gTx++,@[],&d,&e))return Error(e.localizedDescription);if(d.length<4)return Error(@"StorageIDs truncated");const uint8_t*p=d.bytes;uint32_t n=U32(p);if(n>1024||d.length<4+n*4)return Error(@"StorageIDs invalid");NSMutableArray*a=[NSMutableArray array];for(uint32_t i=0;i<n;i++){uint32_t sid=U32((const uint8_t*)d.bytes+4+i*4);NSData*si=nil;if(!Command(0x1005,gTx++,@[@(sid)],&si,&e))return Error(e.localizedDescription);if(si.length<26)return Error(@"StorageInfo truncated");const uint8_t*q=si.bytes;[a addObject:@{@"storage_id":@(sid),@"name":@"Internal storage",@"capacity_bytes":@(U64(q+6)),@"free_bytes":@(U64(q+14))}];}return @{@"ok":@YES,@"storages":a};
}
static NSDictionary *ObjectInfo(uint32_t handle) {
    NSError*e=nil;NSData*d=nil;if(!Command(0x1008,gTx++,@[@(handle)],&d,&e))return Error(e.localizedDescription);if(d.length<52)return Error(@"ObjectInfo truncated");const uint8_t*p=d.bytes;uint32_t parent=U32(p+38);uint16_t format=U16(p+4);uint32_t size=U32(p+8);NSUInteger o=52;NSString*n=MTPString(d,&o),*created=MTPString(d,&o),*modified=MTPString(d,&o),*keywords=MTPString(d,&o);if(!n||!created||!modified||!keywords)return Error(@"ObjectInfo strings truncated");return @{@"ok":@YES,@"item":@{@"object_id":@(handle),@"parent_id":@(parent),@"name":n,@"format":@(format),@"size_bytes":@(size),@"created_at":created,@"modified_at":modified}};
}
static NSDictionary *Children(NSNumber *parent) {
    uint32_t query=parent ? parent.unsignedIntValue : kRootQuery;NSError*e=nil;NSData*d=nil;if(!Command(0x1007,gTx++,@[@65537,@0,@(query)],&d,&e))return Error(e.localizedDescription);if(d.length<4)return Error(@"ObjectHandles truncated");const uint8_t*p=d.bytes;uint32_t n=U32(p);if(n>10000||d.length<4+n*4)return Error(@"ObjectHandles invalid");NSMutableArray*a=[NSMutableArray array];for(uint32_t i=0;i<n;i++){uint32_t h=U32((const uint8_t*)d.bytes+4+i*4);NSDictionary*info=ObjectInfo(h);if(!info[@"ok"])return info;[a addObject:info[@"item"]];}return @{@"ok":@YES,@"items":a};
}
int main(void){@autoreleasepool{char line[65536];while(fgets(line,sizeof(line),stdin)){NSData*d=[[NSString stringWithUTF8String:line] dataUsingEncoding:NSUTF8StringEncoding];NSDictionary*r=[NSJSONSerialization JSONObjectWithData:d options:0 error:nil];NSString*op=r[@"operation"];if([op isEqual:@"open_device"]){NSError*e=nil;if(gOpen)Close();if(Open(&e))Reply(DeviceInfo());else Reply(Error(e.localizedDescription));}else if([op isEqual:@"list_storages"])Reply(Storages());else if([op isEqual:@"list_children"]){id value=r[@"parent_id"];Reply(Children(value==[NSNull null]?nil:value));}else if([op isEqual:@"object_info"])Reply(ObjectInfo([r[@"object_id"] unsignedIntValue]));else if([op isEqual:@"close_device"]){Close();Reply(@{@"ok":@YES});}else Reply(Error(@"unknown operation"));}Close();}return 0;}
