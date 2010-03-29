/*
*******************************************************************************
*   Copyright (C) 2010, International Business Machines
*   Corporation and others.  All Rights Reserved.
*******************************************************************************
*   file name:  genuts46.cpp
*   encoding:   US-ASCII
*   tab size:   8 (not used)
*   indentation:4
*
*   created on: 2010mar02
*   created by: Markus W. Scherer
*
* quick & dirty tool to recreate the UTS #46 data table according to the spec
*/

#include <stdio.h>
#include <string>
#include "unicode/utypes.h"
#include "unicode/errorcode.h"
#include "unicode/normalizer2.h"
#include "unicode/uniset.h"
#include "unicode/unistr.h"
#include "unicode/usetiter.h"
#include "unicode/usprep.h"
#include "sprpimpl.h"  // HACK

/**
 * icu::ErrorCode subclass for easy UErrorCode handling.
 * The destructor calls handleFailure() which calls exit(errorCode) when isFailure().
 */
class ExitingErrorCode : public icu::ErrorCode {
public:
    /**
     * @param loc A short string describing where the ExitingErrorCode is used.
     */
    ExitingErrorCode(const char *loc) : location(loc) {}
    virtual ~ExitingErrorCode();
protected:
    virtual void handleFailure() const;
private:
    const char *location;
};

ExitingErrorCode::~ExitingErrorCode() {
    // Safe because our handleFailure() does not throw exceptions.
    if(isFailure()) { handleFailure(); }
}

void ExitingErrorCode::handleFailure() const {
    fprintf(stderr, "error at %s: %s\n", location, errorName());
    exit(errorCode);
}

static int
toIDNA2003(const UStringPrepProfile *prep, UChar32 c, icu::UnicodeString &destString) {
    UChar src[2];
    int32_t srcLength=0;
    U16_APPEND_UNSAFE(src, srcLength, c);
    UChar *dest;
    int32_t destLength;
    dest=destString.getBuffer(32);
    if(dest==NULL) {
        return FALSE;
    }
    UErrorCode errorCode=U_ZERO_ERROR;
    destLength=usprep_prepare(prep, src, srcLength,
                              dest, destString.getCapacity(),
                              USPREP_DEFAULT, NULL, &errorCode);
    destString.releaseBuffer(destLength);
    if(errorCode==U_STRINGPREP_PROHIBITED_ERROR) {
        return -1;
    } else {
        return U_SUCCESS(errorCode);
    }
}

enum Status { DISALLOWED, IGNORED, MAPPED, DEVIATION, VALID };
static const char *const statusNames[]={
    "disallowed", "ignored", "mapped", "deviation", "valid"
};

static void
printLine(UChar32 start, UChar32 end, Status status, const icu::UnicodeString &mapping) {
    if(start==end) {
        printf("%04lX          ", (long)start);
    } else {
        printf("%04lX..%04lX    ", (long)start, (long)end);
    }
    printf("; %s", statusNames[status]);
    if(status==MAPPED || status==DEVIATION || !mapping.isEmpty()) {
        printf(" ;");
        const UChar *buffer=mapping.getBuffer();
        int32_t length=mapping.length();
        int32_t i=0;
        UChar32 c;
        while(i<length) {
            U16_NEXT(buffer, i, length, c);
            printf(" %04lX", (long)c);
        }
    }
    puts("");
}

extern int
main(int argc, const char *argv[]) {
    ExitingErrorCode errorCode("genuts46");

    // predefined base sets
    icu::UnicodeSet labelSeparators(
        UNICODE_STRING_SIMPLE("[\\u002E\\u3002\\uFF0E\\uFF61]"), errorCode);

    icu::UnicodeSet mappedSet(
        UNICODE_STRING_SIMPLE("[:Changes_When_NFKC_Casefolded:]"), errorCode);
    mappedSet.removeAll(labelSeparators);  // simplifies checking of mapped characters

    icu::UnicodeSet baseValidSet(icu::UnicodeString(
        "[[[:^Changes_When_NFKC_Casefolded:]"
        "-[:C:]-[:Z:]"
        "-[:Block=Ideographic_Description_Characters:]"
        "-[:ascii:]]"
        "[\\u002Da-zA-Z0-9]]", -1, US_INV), errorCode);

#if 0
    icu::UnicodeSet baseExclusionSet(icu::UnicodeString(
        "[\\u04C0\\u10A0-\\u10C5\\u2132\\u2183"
        "\\U0002F868\\U0002F874\\U0002F91F\\U0002F95F\\U0002F9BF"
        "\\u3164\\uFFA0\\u115F\\u1160\\u17B4\\u17B5\\u1806\\uFFFC\\uFFFD"
        "\\u200E\\u200F\\u202A-\\u202E"
        "\\u2061-\\u2063"
        "\\U0001D173-\\U0001D17A"
        "\\u200B\\u2060\\uFEFF"
        "\\u206A-\\u206F"
        "\\U000E0001\\U000E0020-\\U000E007F"
        "[:Cn:]]", -1, US_INV), errorCode);
#endif

    icu::UnicodeSet deviationSet(
        UNICODE_STRING_SIMPLE("[\\u00DF\\u03C2\\u200C\\u200D]"), errorCode);
    errorCode.assertSuccess();

    // derived sets
    icu::LocalUStringPrepProfilePointer namePrep(usprep_openByType(USPREP_RFC3491_NAMEPREP, errorCode));
    const icu::Normalizer2 *nfkc_cf=
        icu::Normalizer2::getInstance(NULL, "nfkc_cf", UNORM2_COMPOSE, errorCode);
    errorCode.assertSuccess();

    // HACK: The StringPrep API performs a BiDi check according to the data.
    // We need to override that for this data generation, by resetting an internal flag.
    namePrep->checkBiDi=FALSE;

    icu::UnicodeSet baseExclusionSet;
    icu::UnicodeString cString, mapping, namePrepResult;
    for(UChar32 c=0; c<=0x10ffff; ++c) {
        if(c==0xd800) {
            c=0xe000;
        }
        int namePrepStatus=toIDNA2003(namePrep.getAlias(), c, namePrepResult);
        if(namePrepStatus!=0) {
            // get the UTS #46 base mapping value
            switch(c) {
            case 0xff0e:
            case 0x3002:
            case 0xff61:
                mapping.setTo(0x2e);
                break;
            default:
                cString.setTo(c);
                nfkc_cf->normalize(cString, mapping, errorCode);
                break;
            }
            if(
                namePrepStatus>0 ?
                    // c is valid or mapped in IDNA2003
                    namePrepResult!=mapping :
                    // namePrepStatus<0: c is prohibited in IDNA2003
                    baseValidSet.contains(c) || (cString!=mapping && baseValidSet.containsAll(mapping))
            ) {
                baseExclusionSet.add(c);
            }
        }
    }

    icu::UnicodeSet disallowedSet(0, 0x10ffff);
    disallowedSet.
        removeAll(labelSeparators).
        removeAll(deviationSet).
        removeAll(mappedSet).
        removeAll(baseValidSet).
        addAll(baseExclusionSet);

    const icu::Normalizer2 *nfd=
        icu::Normalizer2::getInstance(NULL, "nfc", UNORM2_DECOMPOSE, errorCode);
    errorCode.assertSuccess();

    icu::UnicodeSet ignoredSet;  // will be a subset of mappedSet
    icu::UnicodeSet removeSet;
    icu::UnicodeString nfdString;
    {
        icu::UnicodeSetIterator iter(mappedSet);
        while(iter.next()) {
            UChar32 c=iter.getCodepoint();
            cString.setTo(c);
            nfkc_cf->normalize(cString, mapping, errorCode);
            if(!baseValidSet.containsAll(mapping)) {
                fprintf(stderr, "U+%04lX mapped -> disallowed: mapping not wholly in base valid set\n", (long)c);
                disallowedSet.add(c);
                removeSet.add(c);
            } else if(mapping.isEmpty()) {
                ignoredSet.add(c);
            }
        }
        mappedSet.removeAll(removeSet);
    }
    errorCode.assertSuccess();

    icu::UnicodeSet validSet(baseValidSet);
    validSet.
        removeAll(labelSeparators).  // non-ASCII label separators will be mapped in the end
        removeAll(deviationSet).
        removeAll(disallowedSet).
        removeAll(mappedSet).
        add(0x2e);  // not mapped, simply valid
    UBool madeChange;
    do {
        madeChange=FALSE;
        {
            removeSet.clear();
            icu::UnicodeSetIterator iter(validSet);
            while(iter.next()) {
                UChar32 c=iter.getCodepoint();
                cString.setTo(c);
                nfd->normalize(cString, nfdString, errorCode);
                if(!validSet.containsAll(nfdString)) {
                    fprintf(stderr, "U+%04lX valid -> disallowed: NFD not wholly valid\n", (long)c);
                    disallowedSet.add(c);
                    removeSet.add(c);
                    madeChange=TRUE;
                }
            }
            validSet.removeAll(removeSet);
        }
        {
            removeSet.clear();
            icu::UnicodeSetIterator iter(mappedSet);
            while(iter.next()) {
                UChar32 c=iter.getCodepoint();
                cString.setTo(c);
                nfkc_cf->normalize(cString, mapping, errorCode);
                nfd->normalize(mapping, nfdString, errorCode);
                if(!validSet.containsAll(nfdString)) {
                    fprintf(stderr, "U+%04lX mapped -> disallowed: NFD of mapping not wholly valid\n", (long)c);
                    disallowedSet.add(c);
                    removeSet.add(c);
                    madeChange=TRUE;
                }
            }
            mappedSet.removeAll(removeSet);
        }
    } while(madeChange);
    errorCode.assertSuccess();

    // finish up
    labelSeparators.remove(0x2e).freeze();  // U+002E is simply valid
    deviationSet.freeze();
    ignoredSet.freeze();
    validSet.freeze();
    mappedSet.freeze();

    // output
    UChar32 prevStart=0, c=0;
    Status prevStatus=DISALLOWED, status;
    icu::UnicodeString prevMapping;

    icu::UnicodeSetIterator iter(disallowedSet);
    while(iter.nextRange()) {
        UChar32 start=iter.getCodepoint();
        while(c<start) {
            mapping.remove();
            if(labelSeparators.contains(c)) {
                status=MAPPED;
                mapping.setTo(0x2e);
            } else if(deviationSet.contains(c)) {
                status=DEVIATION;
                cString.setTo(c);
                nfkc_cf->normalize(cString, mapping, errorCode);
            } else if(ignoredSet.contains(c)) {
                status=IGNORED;
            } else if(validSet.contains(c)) {
                status=VALID;
            } else if(mappedSet.contains(c)) {
                status=MAPPED;
                cString.setTo(c);
                nfkc_cf->normalize(cString, mapping, errorCode);
            } else {
                fprintf(stderr, "*** undetermined status of U+%04lX\n", (long)c);
            }
            if(prevStart<c && status!=prevStatus || mapping!=prevMapping) {
                printLine(prevStart, c-1, prevStatus, prevMapping);
                prevStart=c;
                prevStatus=status;
                prevMapping=mapping;
            }
            ++c;
        }
        // c==start is disallowed
        if(prevStart<c) {
            printLine(prevStart, c-1, prevStatus, prevMapping);
        }
        prevStart=c;
        prevStatus=DISALLOWED;
        prevMapping.remove();
        c=iter.getCodepointEnd()+1;
    }
    if(prevStart<c) {
        printLine(prevStart, c-1, prevStatus, prevMapping);
    }
    return 0;
}
