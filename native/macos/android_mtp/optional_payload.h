#import <Foundation/Foundation.h>

static inline void PBStoreOptionalPayload(NSData **destination, NSData *payload) {
    if (destination != NULL) {
        *destination = payload;
    }
}
