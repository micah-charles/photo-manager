#import <Foundation/Foundation.h>
#import "../../native/macos/android_mtp/optional_payload.h"

int main(void) {
    @autoreleasepool {
        NSData *stored = nil;
        NSData *value = [NSData dataWithBytes:"x" length:1];
        PBStoreOptionalPayload(NULL, value);
        PBStoreOptionalPayload(&stored, value);
        return [stored isEqualToData:value] ? 0 : 1;
    }
}
