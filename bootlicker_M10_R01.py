#!/usr/bin/env python3
"""Force-unlock patch for the Pritom M10_R01 U-Boot (rk_avb_read_lock_state).

Offline only: reads a stock uboot_a/b image, patches rk_avb_read_lock_state to report
"unlocked" + TEE_SUCCESS, fixes both FIT copies' SHA-256, writes <name>_patched.bin.
It never opens a device and never flashes.

Usage: bootlicker_M10_R01.py STOCK_UBOOT.bin [OUT.bin]
Then flash the result to uboot_a/uboot_b and keep the stock image for recovery.
"""
import hashlib, sys

BANNER = "Wicked Labs - October 2026 - https://www.cyberspace7.org"
USAGE = "usage: bootlicker_M10_R01.py STOCK_UBOOT.bin [OUT.bin]"

PAYLOAD_OFF = 0x1000          # uboot payload inside each FIT copy
PAYLOAD_SZ  = 0x10db38
HASH_OFF    = 0x18c           # uboot image hash (32 bytes, BE) in FIT metadata
COPY_STRIDE = 0x200000        # second identical FIT copy
FUNC_OFF    = 0x95570         # rk_avb_read_lock_state, relative to payload start

STOCK = bytes([0xe2,0x03,0x00,0xaa, 0x23,0x00,0x80,0x52, 0x61,0x01,0x80,0x52,
               0x60,0x02,0x00,0xd0, 0x00,0x6c,0x26,0x91, 0x27,0xfe,0xff,0x17])
PATCH = bytes([0x21,0x00,0x80,0x52, 0x01,0x00,0x00,0x39, 0x00,0x00,0x80,0x52,
               0xc0,0x03,0x5f,0xd6, 0x1f,0x20,0x03,0xd5, 0x1f,0x20,0x03,0xd5])
STOCK_UBOOT_SHA = "9511060b92a74e3e5d319e1ee56c5a5ad1f3078c1fd51f90253c1ac113c9f746"


def block(text):
    print()
    print(text)
    print()


def main():
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else src.rsplit(".", 1)[0] + "_patched.bin"
    d = bytearray(open(src, "rb").read())
    if len(d) < COPY_STRIDE + PAYLOAD_OFF + PAYLOAD_SZ:
        sys.exit("image too small / unexpected layout")

    copies = [0x0, COPY_STRIDE]
    for c in copies:
        if d[c:c+4] != b"\xd0\x0d\xfe\xed":
            sys.exit(f"no FIT magic at copy 0x{c:x}")
        site = c + PAYLOAD_OFF + FUNC_OFF
        cur = bytes(d[site:site+24])
        if cur == PATCH:
            print(f"copy 0x{c:x}: already patched")
        elif cur == STOCK:
            d[site:site+24] = PATCH
            print(f"copy 0x{c:x}: patched rk_avb_read_lock_state at file 0x{site:x}")
        else:
            sys.exit(f"copy 0x{c:x}: unexpected bytes at patch site {cur.hex()} — refusing")

    # fix each copy's uboot-image hash
    for c in copies:
        payload = bytes(d[c+PAYLOAD_OFF:c+PAYLOAD_OFF+PAYLOAD_SZ])
        newh = hashlib.sha256(payload).digest()
        hoff = c + HASH_OFF
        old = bytes(d[hoff:hoff+32]).hex()
        if old not in (STOCK_UBOOT_SHA, hashlib.sha256(payload).hexdigest()):
            sys.exit(f"copy 0x{c:x}: hash slot has unexpected value {old} — refusing")
        d[hoff:hoff+32] = newh
        print(f"copy 0x{c:x}: uboot hash -> {newh.hex()}")

    open(out, "wb").write(d)
    # self-check
    v = open(out, "rb").read()
    for c in copies:
        p = v[c+PAYLOAD_OFF:c+PAYLOAD_OFF+PAYLOAD_SZ]
        assert v[c+HASH_OFF:c+HASH_OFF+32] == hashlib.sha256(p).digest(), "hash mismatch"
        assert v[c+PAYLOAD_OFF+FUNC_OFF:c+PAYLOAD_OFF+FUNC_OFF+24] == PATCH
    print(f"wrote {out} ({len(v)} bytes); both FIT copies patched and hashed. Nothing flashed.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        block(BANNER)
        block(USAGE)
        sys.exit(0)
    block(BANNER)
    main()
