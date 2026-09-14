#import <Foundation/Foundation.h>
#import <IOKit/IOKitLib.h>
#import <IOUSBHost/IOUSBHost.h>
#import <CommonCrypto/CommonDigest.h>
#import <string.h>
#import <stdlib.h>
#import "optional_payload.h"

static const NSUInteger kMax = 1024 * 1024;
static const NSUInteger kDefaultStreamChunk = 16 * 1024;
static const uint32_t kRootQuery = 0xffffffff;
// The proven Pixel Camera handle query took 4.874s for 6,674 objects. A 5s
// transport timeout leaves no practical scheduling margin on a loaded Mac.
static const NSTimeInterval kTimeout = 15.0;
static uint32_t gTx = 1;
static IOUSBHostInterface *gInterface;
static IOUSBHostPipe *gIn;
static IOUSBHostPipe *gOut;
static BOOL gOpen = NO;
static NSArray *gStorageCache;
static BOOL gSupportsPartialObject = NO;
static BOOL gSupportsPartialObject64 = NO;

@interface PBAsyncReadState : NSObject {
@public
    dispatch_semaphore_t done;
    IOReturn status;
    NSUInteger actual;
    NSUInteger requested;
    NSMutableData *buffer;
}
@end
@implementation PBAsyncReadState
- (instancetype)init { if((self=[super init]))done=dispatch_semaphore_create(0);return self; }
@end

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
static NSError *StageError(NSString *stage, NSError *underlying) {
    NSString *detail=underlying.localizedDescription ?: @"unknown error";
    return [NSError errorWithDomain:@"MTP" code:50 userInfo:@{NSLocalizedDescriptionKey:[NSString stringWithFormat:@"%@: %@",stage,detail]}];
}
static NSError *CommandStageError(uint16_t operation, uint32_t transaction, NSString *stage, NSError *underlying) {
    return StageError([NSString stringWithFormat:@"command 0x%04x tx=%u %@",operation,transaction,stage],underlying);
}
static void Reply(NSDictionary *obj) {
    NSData *data=[NSJSONSerialization dataWithJSONObject:obj options:0 error:nil];
    fwrite(data.bytes,1,data.length,stdout); fputc('\n',stdout); fflush(stdout);
}
static io_service_t FindInterface(void) {
    CFMutableDictionaryRef m=[IOUSBHostInterface createMatchingDictionaryWithVendorID:@0x18d1 productID:@0x4ee1 bcdDevice:nil interfaceNumber:@0 configurationValue:@1 interfaceClass:@0x06 interfaceSubclass:@0x01 interfaceProtocol:@0x01 speed:nil productIDArray:nil];
    return m ? IOServiceGetMatchingService(kIOMainPortDefault,m) : IO_OBJECT_NULL;
}
static BOOL ReceiveSized(NSUInteger capacity, NSData **result, NSError **error) {
    NSMutableData *buffer=[NSMutableData dataWithLength:capacity]; NSUInteger n=0; NSError *e=nil;
    if (![gIn sendIORequestWithData:buffer bytesTransferred:&n completionTimeout:kTimeout error:&e]) {
        if(error)*error=[NSError errorWithDomain:@"MTP.Transport" code:e.code userInfo:@{NSLocalizedDescriptionKey:[NSString stringWithFormat:@"bulk-in endpoint=0x81 requested=%lu actual=%lu timeout=%.1fs underlying=%@(%ld) %@",(unsigned long)capacity,(unsigned long)n,kTimeout,e.domain,(long)e.code,e.localizedDescription]}];
        return NO;
    }
    [buffer setLength:n]; *result=buffer; return YES;
}
static BOOL Receive(NSData **result, NSError **error) { return ReceiveSized(kMax,result,error); }
static BOOL ReceiveStreamBuffer(NSMutableData *buffer, NSUInteger *actual, NSError **error) {
    NSUInteger n=0;NSError *e=nil;
    if(![gIn sendIORequestWithData:buffer bytesTransferred:&n completionTimeout:kTimeout error:&e]){
        if(error)*error=[NSError errorWithDomain:@"MTP.Transport" code:e.code userInfo:@{NSLocalizedDescriptionKey:[NSString stringWithFormat:@"bulk-in endpoint=0x81 requested=%lu actual=%lu timeout=%.1fs buffer=%p underlying=%@(%ld) %@",(unsigned long)buffer.length,(unsigned long)n,kTimeout,buffer.bytes,e.domain,(long)e.code,e.localizedDescription]}];
        return NO;
    }
    if(actual)*actual=n;return YES;
}
static PBAsyncReadState *EnqueueStreamBuffer(NSMutableData *buffer, NSError **error) {
    PBAsyncReadState *state=[PBAsyncReadState new];state->buffer=buffer;state->requested=buffer.length;
    NSError *e=nil;
    BOOL queued=[gIn enqueueIORequestWithData:buffer completionTimeout:kTimeout error:&e completionHandler:^(IOReturn completionStatus, NSUInteger bytesTransferred){state->status=completionStatus;state->actual=bytesTransferred;dispatch_semaphore_signal(state->done);}];
    if(!queued){if(error)*error=StageError(@"enqueue async bulk-in",e);return nil;}
    return state;
}
static BOOL WaitForStreamBuffer(PBAsyncReadState *state, NSError **error) {
    dispatch_semaphore_wait(state->done,DISPATCH_TIME_FOREVER);
    if(state->status==kIOReturnSuccess)return YES;
    if(error)*error=[NSError errorWithDomain:@"MTP.Transport" code:state->status userInfo:@{NSLocalizedDescriptionKey:[NSString stringWithFormat:@"async bulk-in endpoint=0x81 requested=%lu actual=%lu timeout=%.1fs buffer=%p IOReturn=0x%08x",(unsigned long)state->requested,(unsigned long)state->actual,kTimeout,state->buffer.bytes,state->status]}];
    return NO;
}
static void AbortPendingStreamRead(PBAsyncReadState *state) {
    if(!state)return;NSError *abortError=nil;[gIn abortWithError:&abortError];dispatch_semaphore_wait(state->done,DISPATCH_TIME_FOREVER);
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
    if (![gOut sendIORequestWithData:out bytesTransferred:&sent completionTimeout:kTimeout error:&e]) { if(error)*error=CommandStageError(op,tx,@"send",e); return NO; }
    NSData *raw; NSError *receiveError=nil;if(!Receive(&raw,&receiveError)){if(error)*error=CommandStageError(op,tx,@"first receive",receiveError);return NO;} uint16_t ctype,code; uint32_t rtx; NSData *payload;
    if(!Parse(raw,&ctype,&code,&rtx,&payload,error) || rtx!=tx) return NO;
    if(ctype==2) {
        if (code!=op) { if(error)*error=[NSError errorWithDomain:@"MTP" code:3 userInfo:@{NSLocalizedDescriptionKey:@"unexpected data code"}]; return NO; }
        PBStoreOptionalPayload(dataPayload,payload); if(!Receive(&raw,&receiveError)){if(error)*error=CommandStageError(op,tx,@"response receive",receiveError);return NO;} if(!Parse(raw,&ctype,&code,&rtx,&payload,error)) return NO;
    } else PBStoreOptionalPayload(dataPayload,nil);
    if(ctype!=3 || code!=0x2001 || rtx!=tx) {
        NSString *response=code==0x2009 ? @"InvalidObjectHandle (0x2009)" : [NSString stringWithFormat:@"MTP response 0x%04x",code];
        if(error)*error=[NSError errorWithDomain:@"MTP" code:4 userInfo:@{NSLocalizedDescriptionKey:response}];
        return NO;
    }
    return YES;
}
static BOOL Open(NSError **error) {
    io_service_t service=FindInterface();
    if(!service){if(error)*error=[NSError errorWithDomain:@"MTP" code:5 userInfo:@{NSLocalizedDescriptionKey:@"Pixel MTP interface not found"}];return NO;}
    NSError *e=nil;
    gInterface=[[IOUSBHostInterface alloc] initWithIOService:service options:IOUSBHostObjectInitOptionsNone queue:nil error:&e interestHandler:nil];
    IOObjectRelease(service);
    if(!gInterface){if(error)*error=e;return NO;}
    gIn=[gInterface copyPipeWithAddress:0x81 error:&e];
    gOut=[gInterface copyPipeWithAddress:0x01 error:&e];
    if(!gIn||!gOut){if(error)*error=e;return NO;}
    NSMutableData *session=[NSMutableData data]; P32(session,1);
    NSMutableData *cmd=[NSMutableData data]; P32(cmd,16); uint8_t t[2]={1,0};[cmd appendBytes:t length:2];uint8_t c[2]={2,0x10};[cmd appendBytes:c length:2];P32(cmd,0);[cmd appendData:session];
    NSUInteger sent=0; if(![gOut sendIORequestWithData:cmd bytesTransferred:&sent completionTimeout:kTimeout error:&e]){if(error)*error=e;return NO;}
    NSData *raw; if(!Receive(&raw,&e)){if(error)*error=e;return NO;}
    uint16_t ty,co;uint32_t rt;NSData *pl;
    if(!Parse(raw,&ty,&co,&rt,&pl,&e)){if(error)*error=e;return NO;}
    if(ty!=3||co!=0x2001){if(error)*error=[NSError errorWithDomain:@"MTP" code:6 userInfo:@{NSLocalizedDescriptionKey:[NSString stringWithFormat:@"OpenSession response 0x%04x",co]}];return NO;}
    gTx=1;gOpen=YES;return YES;
}
static void Close(void) {
    NSError *e=nil; if(gOpen)Command(0x1003,gTx++,@[],NULL,&e); if(gInterface)[gInterface destroy]; gInterface=nil;gIn=nil;gOut=nil;gOpen=NO;
}
static NSDictionary *DeviceInfo(void) {
    NSError *e=nil; NSData *d=nil; if(!Command(0x1001,gTx++,@[],&d,&e))return Error(e.localizedDescription);
    NSUInteger o=0;const uint8_t*p;if(!Bytes(d,&o,8,&p))return Error(@"DeviceInfo truncated"); NSString *ext=MTPString(d,&o);if(!ext||!Bytes(d,&o,2,&p))return Error(@"DeviceInfo header truncated");
    gSupportsPartialObject=NO;gSupportsPartialObject64=NO;
    for(int i=0;i<5;i++){
        if(!Bytes(d,&o,4,&p))return Error(@"DeviceInfo array truncated");uint32_t n=U32(p);
        if(n>4096||!Bytes(d,&o,n*2,&p))return Error(@"DeviceInfo array invalid");
        if(i==0){for(uint32_t j=0;j<n;j++){uint16_t operation=U16(p+j*2);if(operation==0x101b)gSupportsPartialObject=YES;if(operation==0x95c1)gSupportsPartialObject64=YES;}}
    }
    NSString *manufacturer=MTPString(d,&o),*model=MTPString(d,&o),*version=MTPString(d,&o),*serial=MTPString(d,&o);if(!manufacturer||!model||!version||!serial)return Error(@"DeviceInfo strings truncated");
    unsigned char digest[CC_SHA256_DIGEST_LENGTH];CC_SHA256(serial.UTF8String,(CC_LONG)strlen(serial.UTF8String),digest);NSMutableString *fp=[NSMutableString string];for(int i=0;i<12;i++)[fp appendFormat:@"%02x",digest[i]];
    return @{@"ok":@YES,@"device":@{@"manufacturer":manufacturer,@"model":model,@"friendly_name":model,@"vid":@0x18d1,@"pid":@0x4ee1,@"serial_fingerprint":fp,@"supports_get_partial_object":@(gSupportsPartialObject),@"supports_get_partial_object_64":@(gSupportsPartialObject64)}};
}
static NSDictionary *Storages(void) {
    NSError *e=nil;NSData*d=nil;if(!Command(0x1004,gTx++,@[],&d,&e))return Error(e.localizedDescription);if(d.length<4)return Error(@"StorageIDs truncated");const uint8_t*p=d.bytes;uint32_t n=U32(p);if(n>1024||d.length<4+n*4)return Error(@"StorageIDs invalid");NSMutableArray*a=[NSMutableArray array];for(uint32_t i=0;i<n;i++){uint32_t sid=U32((const uint8_t*)d.bytes+4+i*4);NSData*si=nil;if(!Command(0x1005,gTx++,@[@(sid)],&si,&e))return Error(e.localizedDescription);if(si.length<26)return Error(@"StorageInfo truncated");const uint8_t*q=si.bytes;[a addObject:@{@"storage_id":@(sid),@"name":@"Internal storage",@"capacity_bytes":@(U64(q+6)),@"free_bytes":@(U64(q+14))}];}return @{@"ok":@YES,@"storages":a};
}
static NSDictionary *ObjectInfo(uint32_t handle) {
    NSError*e=nil;NSData*d=nil;if(!Command(0x1008,gTx++,@[@(handle)],&d,&e))return Error(e.localizedDescription);if(d.length<52)return Error(@"ObjectInfo truncated");const uint8_t*p=d.bytes;uint32_t parent=U32(p+38);uint16_t format=U16(p+4);uint32_t size=U32(p+8);NSUInteger o=52;NSString*n=MTPString(d,&o),*created=MTPString(d,&o),*modified=MTPString(d,&o),*keywords=MTPString(d,&o);if(!n||!created||!modified||!keywords)return Error(@"ObjectInfo strings truncated");return @{@"ok":@YES,@"item":@{@"object_id":@(handle),@"parent_id":@(parent),@"name":n,@"format":@(format),@"size_bytes":@(size),@"created_at":created,@"modified_at":modified}};
}
static NSArray<NSNumber *> *ObjectHandles(NSNumber *parent, NSError **error) {
    uint32_t query=parent ? parent.unsignedIntValue : kRootQuery;
    NSData *data=nil;uint32_t tx=gTx++;
    if(!Command(0x1007,tx,@[@65537,@0,@(query)],&data,error)) {
        if(error&&*error)*error=[NSError errorWithDomain:@"MTP" code:20 userInfo:@{NSLocalizedDescriptionKey:[NSString stringWithFormat:@"GetObjectHandles parent=%u tx=%u failed: %@",query,tx,(*error).localizedDescription]}];
        return nil;
    }
    if(data.length<4){if(error)*error=[NSError errorWithDomain:@"MTP" code:21 userInfo:@{NSLocalizedDescriptionKey:@"ObjectHandles truncated"}];return nil;}
    const uint8_t*p=data.bytes;uint32_t count=U32(p);
    if(count>10000||data.length<4+(NSUInteger)count*4){if(error)*error=[NSError errorWithDomain:@"MTP" code:22 userInfo:@{NSLocalizedDescriptionKey:@"ObjectHandles invalid"}];return nil;}
    NSMutableArray *handles=[NSMutableArray arrayWithCapacity:count];
    for(uint32_t i=0;i<count;i++)[handles addObject:@(U32((const uint8_t*)data.bytes+4+i*4))];
    return handles;
}
static NSDictionary *FindChild(NSNumber *parent, NSString *name) {
    NSError *error=nil;NSArray<NSNumber*>*handles=ObjectHandles(parent,&error);
    if(!handles)return Error(error.localizedDescription);
    for(NSUInteger index=0;index<handles.count;index++){
        NSDictionary *info=ObjectInfo(handles[index].unsignedIntValue);
        if(![info[@"ok"] boolValue])return Error([NSString stringWithFormat:@"GetObjectInfo index=%lu/%lu failed: %@",(unsigned long)index+1,(unsigned long)handles.count,info[@"error"]]);
        NSDictionary *item=info[@"item"];
        if([item[@"format"] unsignedIntValue]==0x3001&&[item[@"name"] caseInsensitiveCompare:name]==NSOrderedSame)return @{@"ok":@YES,@"item":item};
    }
    return @{@"ok":@YES,@"item":[NSNull null]};
}
static NSDictionary *Children(NSNumber *parent, NSUInteger offset, NSUInteger limit) {
    NSError *error=nil;NSArray<NSNumber*>*handles=ObjectHandles(parent,&error);
    if(!handles)return Error(error.localizedDescription);
    NSUInteger start=MIN(offset,handles.count);NSUInteger end=MIN(start+MAX((NSUInteger)1,limit),handles.count);
    NSMutableArray *items=[NSMutableArray arrayWithCapacity:end-start];
    for(NSUInteger index=start;index<end;index++){
        NSDictionary *info=ObjectInfo(handles[index].unsignedIntValue);
        if(![info[@"ok"] boolValue])return Error([NSString stringWithFormat:@"GetObjectInfo index=%lu/%lu handle=%@ failed: %@",(unsigned long)index+1,(unsigned long)handles.count,handles[index],info[@"error"]]);
        [items addObject:info[@"item"]];
    }
    id next=end<handles.count?@(end):[NSNull null];
    return @{@"ok":@YES,@"items":items,@"total":@(handles.count),@"next_offset":next};
}
static BOOL StreamObject(uint32_t handle, NSUInteger streamChunk, NSString *transport, uint64_t *bytesWritten, NSError **error) {
    NSMutableData *cmd=[NSMutableData data]; P32(cmd,16); uint8_t commandType[2]={1,0}; [cmd appendBytes:commandType length:2]; uint8_t c[2]={9,0x10}; [cmd appendBytes:c length:2]; uint32_t tx=gTx++; P32(cmd,tx); P32(cmd,handle);
    NSUInteger sent=0; NSError *e=nil;
    if (![gOut sendIORequestWithData:cmd bytesTransferred:&sent completionTimeout:kTimeout error:&e]) { if(error)*error=StageError(@"GetObject command send",e); return NO; }
    NSMutableData *streamBuffer=[gInterface ioDataWithCapacity:streamChunk error:&e];
    if(!streamBuffer){if(error)*error=StageError(@"allocate GetObject IO buffer",e);return NO;}
    NSUInteger firstLength=0;if(!ReceiveStreamBuffer(streamBuffer,&firstLength,&e)){if(error)*error=StageError(@"GetObject first response",e);return NO;}
    NSData *first=[NSData dataWithBytes:streamBuffer.bytes length:firstLength];
    if(first.length<12){if(error)*error=[NSError errorWithDomain:@"MTP" code:30 userInfo:@{NSLocalizedDescriptionKey:@"GetObject response header truncated"}];return NO;}
    const uint8_t *p=first.bytes; uint32_t total=U32(p); uint16_t type=U16(p+4), code=U16(p+6); uint32_t responseTx=U32(p+8);
    if(total<12 || type!=2 || code!=0x1009 || responseTx!=tx){if(error)*error=[NSError errorWithDomain:@"MTP" code:31 userInfo:@{NSLocalizedDescriptionKey:@"invalid GetObject data header"}];return NO;}
    uint64_t objectLength=(uint64_t)total-12;uint64_t remaining=objectLength; NSUInteger firstPayload=first.length-12; NSUInteger emit=(NSUInteger)MIN((uint64_t)firstPayload,remaining);
    fprintf(stderr,"MTP_STREAM_TRACE\tbuffer=kernel-reused\tread_size=%lu\tfirst_read=%lu\tcontainer_length=%u\tinitial_payload=%lu\n",(unsigned long)streamChunk,(unsigned long)first.length,total,(unsigned long)emit);
    if(emit && fwrite((const uint8_t *)first.bytes+12,1,emit,stdout)!=emit){if(error)*error=[NSError errorWithDomain:@"MTP" code:32 userInfo:@{NSLocalizedDescriptionKey:@"stream output failed"}];return NO;} remaining-=emit;
    NSUInteger chunkIndex=0;uint64_t offset=emit;
    if([transport isEqualToString:@"async-pingpong"]&&remaining){
        NSMutableData *bufferB=[gInterface ioDataWithCapacity:streamChunk error:&e];
        if(!bufferB){if(error)*error=StageError(@"allocate second GetObject IO buffer",e);return NO;}
        NSUInteger requested=(NSUInteger)MIN((uint64_t)streamChunk,remaining);
        NSMutableData *firstContinuation=requested==streamChunk?streamBuffer:[gInterface ioDataWithCapacity:requested error:&e];
        if(!firstContinuation){if(error)*error=StageError(@"allocate final GetObject IO buffer",e);return NO;}
        PBAsyncReadState *current=EnqueueStreamBuffer(firstContinuation,&e);
        if(!current){if(error)*error=e;return NO;}
        while(current){
            chunkIndex++;
            if(!WaitForStreamBuffer(current,&e)){if(error)*error=StageError([NSString stringWithFormat:@"GetObject async receive chunk=%lu offset=%llu remaining=%llu",(unsigned long)chunkIndex,offset,remaining],e);return NO;}
            if(current->actual==0){if(error)*error=[NSError errorWithDomain:@"MTP" code:33 userInfo:@{NSLocalizedDescriptionKey:[NSString stringWithFormat:@"empty async GetObject chunk=%lu offset=%llu remaining=%llu",(unsigned long)chunkIndex,offset,remaining]}];return NO;}
            NSUInteger n=(NSUInteger)MIN((uint64_t)current->actual,remaining);uint64_t nextRemaining=remaining-n;
            PBAsyncReadState *next=nil;
            if(nextRemaining){NSUInteger nextRequested=(NSUInteger)MIN((uint64_t)streamChunk,nextRemaining);NSMutableData *candidate=current->buffer==streamBuffer?bufferB:streamBuffer;if(nextRequested!=streamChunk)candidate=[gInterface ioDataWithCapacity:nextRequested error:&e];if(!candidate){if(error)*error=StageError(@"allocate final async GetObject IO buffer",e);return NO;}next=EnqueueStreamBuffer(candidate,&e);if(!next){if(error)*error=e;return NO;}}
            if(fwrite(current->buffer.bytes,1,n,stdout)!=n){AbortPendingStreamRead(next);if(error)*error=[NSError errorWithDomain:@"MTP" code:32 userInfo:@{NSLocalizedDescriptionKey:@"stream output failed"}];return NO;}
            remaining=nextRemaining;offset+=n;
            if(chunkIndex%64==0||!remaining)fprintf(stderr,"MTP_STREAM_ASYNC\tchunk=%lu\toffset=%llu\tremaining=%llu\tmax_pending=1\n",(unsigned long)chunkIndex,offset,remaining);
            current=next;
        }
    }else{
        while(remaining){NSUInteger requested=(NSUInteger)MIN((uint64_t)streamChunk,remaining);NSMutableData *activeBuffer=requested==streamChunk?streamBuffer:[gInterface ioDataWithCapacity:requested error:&e];if(!activeBuffer){if(error)*error=StageError(@"allocate final GetObject IO buffer",e);return NO;}NSUInteger actual=0;chunkIndex++;if(!ReceiveStreamBuffer(activeBuffer,&actual,&e)){if(error)*error=StageError([NSString stringWithFormat:@"GetObject data receive chunk=%lu offset=%llu remaining=%llu",(unsigned long)chunkIndex,offset,remaining],e);return NO;}if(actual==0){if(error)*error=[NSError errorWithDomain:@"MTP" code:33 userInfo:@{NSLocalizedDescriptionKey:[NSString stringWithFormat:@"empty GetObject data chunk=%lu offset=%llu remaining=%llu",(unsigned long)chunkIndex,offset,remaining]}];return NO;}NSUInteger n=(NSUInteger)MIN((uint64_t)actual,remaining);if(fwrite(activeBuffer.bytes,1,n,stdout)!=n){if(error)*error=[NSError errorWithDomain:@"MTP" code:32 userInfo:@{NSLocalizedDescriptionKey:@"stream output failed"}];return NO;}remaining-=n;offset+=n;}
    }
    fflush(stdout);NSUInteger statusLength=0;if(!ReceiveStreamBuffer(streamBuffer,&statusLength,&e)){if(error)*error=StageError(@"GetObject status receive",e);return NO;}if(statusLength==0&&!ReceiveStreamBuffer(streamBuffer,&statusLength,&e)){if(error)*error=StageError(@"GetObject status receive after ZLP",e);return NO;}NSData *status=[NSData dataWithBytes:streamBuffer.bytes length:statusLength];uint16_t stype,scode;uint32_t stx;NSData *sp;if(!Parse(status,&stype,&scode,&stx,&sp,&e)||stype!=3||scode!=0x2001||stx!=tx){if(error)*error=StageError(@"GetObject status parse",e);return NO;}if(bytesWritten)*bytesWritten=objectLength;return YES;
}
static BOOL StreamPartialObject(uint32_t handle, uint64_t objectSize, NSUInteger partialSize, uint64_t *bytesWritten, NSError **error) {
    if(!gSupportsPartialObject){if(error)*error=[NSError errorWithDomain:@"MTP" code:60 userInfo:@{NSLocalizedDescriptionKey:@"Pixel does not advertise GetPartialObject (0x101b)"}];return NO;}
    if(partialSize==0||partialSize+12>kMax){if(error)*error=[NSError errorWithDomain:@"MTP" code:61 userInfo:@{NSLocalizedDescriptionKey:@"invalid partial object size"}];return NO;}
    uint64_t offset=0;NSUInteger part=0;
    while(offset<objectSize){
        NSUInteger requested=(NSUInteger)MIN((uint64_t)partialSize,objectSize-offset);NSData *payload=nil;NSError *e=nil;uint32_t tx=gTx++;
        if(!Command(0x101b,tx,@[@(handle),@((uint32_t)offset),@(requested)],&payload,&e)){if(error)*error=StageError([NSString stringWithFormat:@"GetPartialObject part=%lu offset=%llu requested=%lu tx=%u",(unsigned long)part,offset,(unsigned long)requested,tx],e);return NO;}
        if(payload.length==0||payload.length>requested){if(error)*error=[NSError errorWithDomain:@"MTP" code:62 userInfo:@{NSLocalizedDescriptionKey:[NSString stringWithFormat:@"invalid GetPartialObject payload part=%lu offset=%llu requested=%lu actual=%lu",(unsigned long)part,offset,(unsigned long)requested,(unsigned long)payload.length]}];return NO;}
        if(fwrite(payload.bytes,1,payload.length,stdout)!=payload.length){if(error)*error=[NSError errorWithDomain:@"MTP" code:32 userInfo:@{NSLocalizedDescriptionKey:@"partial stream output failed"}];return NO;}
        offset+=payload.length;part++;
        if(part%16==0||offset==objectSize)fprintf(stderr,"MTP_PARTIAL\tpart=%lu\toffset=%llu\trequested=%lu\tactual=%lu\tresponse=0x2001\n",(unsigned long)(part-1),offset-payload.length,(unsigned long)requested,(unsigned long)payload.length);
    }
    fflush(stdout);if(bytesWritten)*bytesWritten=offset;return offset==objectSize;
}
static BOOL PrepareForObjectRead(NSError **error) {
    NSDictionary *storages=Storages();
    if (![storages[@"ok"] boolValue]) {
        if (error) *error=[NSError errorWithDomain:@"MTP" code:41 userInfo:@{NSLocalizedDescriptionKey:storages[@"error"] ?: @"Storage setup failed"}];
        return NO;
    }
    return YES;
}
static NSDictionary *OpenControlSession(void) {
    NSError *error=nil;if(gOpen)Close();
    if(!Open(&error))return Error(error.localizedDescription);
    NSDictionary *device=DeviceInfo();
    if(![device[@"ok"] boolValue]){Close();return device;}
    NSDictionary *storages=Storages();
    if(![storages[@"ok"] boolValue]){Close();return storages;}
    gStorageCache=storages[@"storages"];
    NSDictionary *reply=@{@"ok":@YES,@"device":device[@"device"],@"storages":storages[@"storages"]};
    Close();
    if(!Open(&error))return Error([NSString stringWithFormat:@"fresh traversal session failed: %@",error.localizedDescription]);
    return reply;
}
static NSDictionary *FirstMediaInFolder(NSString *logicalPath) {
    NSNumber *parent=nil;
    for(NSString *component in [logicalPath componentsSeparatedByString:@"/"]){
        if(component.length==0)continue;
        NSDictionary *found=FindChild(parent,component);
        if(![found[@"ok"] boolValue])return found;
        id item=found[@"item"];
        if(item==[NSNull null])return Error([NSString stringWithFormat:@"folder not found: %@",component]);
        parent=item[@"object_id"];
    }
    NSError *error=nil;NSArray<NSNumber*>*handles=ObjectHandles(parent,&error);
    if(!handles)return Error(error.localizedDescription);
    for(NSNumber *handle in handles){
        NSDictionary *info=ObjectInfo(handle.unsignedIntValue);
        if(![info[@"ok"] boolValue])return info;
        NSDictionary *item=info[@"item"];
        if([item[@"format"] unsignedIntValue]==0x3801)return info;
    }
    return Error(@"no JPEG object found in folder");
}
static NSUInteger EndpointMaxPacketSize(void) {
    const IOUSBHostIOSourceDescriptors *descriptors=gIn.descriptors;
    return descriptors ? (CFSwapInt16LittleToHost(descriptors->descriptor.wMaxPacketSize)&0x7ff) : 0;
}
static int StreamTest(NSString *logicalPath, NSString *readSize, NSString *transport, NSString *mtpMode, NSUInteger partialSize) {
    NSDictionary *opened=OpenControlSession();
    if(![opened[@"ok"] boolValue]){fprintf(stderr,"android-mtp stream-test failed: open_control_session: %s\n",[opened[@"error"] UTF8String]);Close();return 3;}
    NSDictionary *selected=FirstMediaInFolder(logicalPath);
    if(![selected[@"ok"] boolValue]){fprintf(stderr,"android-mtp stream-test failed: resolve_media: %s\n",[selected[@"error"] UTF8String]);Close();return 3;}
    NSDictionary *item=selected[@"item"];
    NSUInteger endpointPacket=EndpointMaxPacketSize();
    NSUInteger streamChunk=[readSize isEqualToString:@"max-packet"]?endpointPacket:kDefaultStreamChunk;
    if(streamChunk==0){fprintf(stderr,"android-mtp stream-test failed: invalid endpoint max packet size\n");Close();return 3;}
    if([transport isEqualToString:@"async-pingpong"])streamChunk=kDefaultStreamChunk;
    fprintf(stderr,"MTP_STREAM_CONFIG\tmtp_mode=%s\tpartial_supported=%s\tpartial64_supported=%s\tpartial_size=%lu\ttransport=%s\tread_size_mode=%s\tread_size=%lu\tendpoint_max_packet=%lu\n",mtpMode.UTF8String,gSupportsPartialObject?"yes":"no",gSupportsPartialObject64?"yes":"no",(unsigned long)partialSize,transport.UTF8String,readSize.UTF8String,(unsigned long)streamChunk,(unsigned long)endpointPacket);
    uint64_t transferred=0;NSError *error=nil;
    BOOL ok=[mtpMode isEqualToString:@"partial"]?StreamPartialObject([item[@"object_id"] unsignedIntValue],[item[@"size_bytes"] unsignedLongLongValue],partialSize,&transferred,&error):StreamObject([item[@"object_id"] unsignedIntValue],streamChunk,transport,&transferred,&error);
    if(!ok)fprintf(stderr,"android-mtp stream-test failed: %s\n",StageError(@"stream_object",error).localizedDescription.UTF8String);
    else fprintf(stderr,"PHOTOVAULT_STREAM_RESULT\t%llu\t%u\n",transferred,[item[@"size_bytes"] unsignedIntValue]);
    Close();return ok?0:3;
}
int main(int argc,const char **argv){
    @autoreleasepool {
        if((argc==3||argc==11)&&strcmp(argv[1],"--stream-test")==0){NSString *mtpMode=argc==11?[NSString stringWithUTF8String:argv[4]]:@"full";NSUInteger partialSize=argc==11?(NSUInteger)strtoul(argv[6],NULL,10):65536;NSString *transport=argc==11?[NSString stringWithUTF8String:argv[8]]:@"synchronous";NSString *readSize=argc==11?[NSString stringWithUTF8String:argv[10]]:@"16k";return StreamTest([NSString stringWithUTF8String:argv[2]],readSize,transport,mtpMode,partialSize);}
        if(argc==3&&strcmp(argv[1],"--stream")==0){
            NSError *error=nil;BOOL ok=Open(&error);
            if(!ok)error=StageError(@"open_session",error);
            else if(!PrepareForObjectRead(&error)){error=StageError(@"prepare_object_read",error);ok=NO;}
            else if(!StreamObject((uint32_t)strtoul(argv[2],NULL,10),kDefaultStreamChunk,@"synchronous",NULL,&error)){error=StageError(@"stream_object",error);ok=NO;}
            if(!ok)fprintf(stderr,"android-mtp stream failed: %s\n",error.localizedDescription.UTF8String);
            Close();return ok?0:3;
        }
        char line[65536];
        while(fgets(line,sizeof(line),stdin)){
            NSData *data=[[NSString stringWithUTF8String:line] dataUsingEncoding:NSUTF8StringEncoding];
            NSDictionary *request=[NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
            NSString *operation=request[@"operation"];
            if([operation isEqual:@"open_device"])Reply(OpenControlSession());
            else if([operation isEqual:@"list_storages"])Reply(@{@"ok":@YES,@"storages":gStorageCache ?: @[]});
            else if([operation isEqual:@"find_child"]){id value=request[@"parent_id"];Reply(FindChild(value==[NSNull null]?nil:value,request[@"name"]));}
            else if([operation isEqual:@"list_children"]){id value=request[@"parent_id"];Reply(Children(value==[NSNull null]?nil:value,[request[@"offset"] unsignedIntegerValue],[request[@"limit"] unsignedIntegerValue]));}
            else if([operation isEqual:@"object_info"])Reply(ObjectInfo([request[@"object_id"] unsignedIntValue]));
            else if([operation isEqual:@"close_device"]){Close();Reply(@{@"ok":@YES});}
            else Reply(Error(@"unknown operation"));
        }
        Close();
    }
    return 0;
}
