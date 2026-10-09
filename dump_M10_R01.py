#!/usr/bin/env python3
"""Dump every eMMC partition to its own image via rkdeveloptool (usbplug loaded).

Usage: sudo-capable user, device in usbplug:  dump_M10_R01.py OUT_DIR [--skip NAME ...]

Reads the live primary GPT, then writes one file per region:
  gpt_primary.bin   LBA 0-33 (protective MBR + header + entries)
  idblock.bin       LBA 0x40 .. first partition - 1 (SPL/TPL)
  <name>.bin        each GPT partition
  gpt_backup.bin    last 33 sectors (backup entries + header)
  gap_*.bin         any sectors between the above, so the set covers every LBA
plus MANIFEST.txt (sha256, LBA range, flash command) and parameter.txt.
"""
import argparse, hashlib, os, struct, subprocess, sys, uuid

SECTOR = 512
BANNER = "Wicked Labs - October 2026 - https://www.cyberspace7.org"
USAGE = "usage: dump_M10_R01.py OUT_DIR [--skip NAME ...]"


def block(text):
    print()
    print(text)
    print()


if len(sys.argv) == 1:
    block(BANNER)
    block(USAGE)
    sys.exit(0)
block(BANNER)


def rl(lba, count, path):
    subprocess.run(["sudo", "rkdeveloptool", "rl", str(lba), str(count), path],
                   check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["sudo", "chown", f"{os.getuid()}:{os.getgid()}", path], check=True)
    if os.path.getsize(path) != count * SECTOR:
        raise SystemExit(f"short read: {path}")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(16 << 20):
            h.update(b)
    return h.hexdigest()


ap = argparse.ArgumentParser()
ap.add_argument("out")
ap.add_argument("--skip", nargs="*", default=[])
a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)

gpt = os.path.join(a.out, "gpt_primary.bin")
rl(0, 34, gpt)
with open(gpt, "rb") as f:
    d = f.read()
assert d[SECTOR:SECTOR + 8] == b"EFI PART", "no GPT header at LBA 1"
alt_lba = struct.unpack_from("<Q", d, SECTOR + 32)[0]
ent_lba, n_ent, ent_sz = struct.unpack_from("<QII", d, SECTOR + 72)
parts = []
for i in range(n_ent):
    e = d[ent_lba * SECTOR + i * ent_sz:][:ent_sz]
    if e[:16] == b"\0" * 16:
        continue
    first, last = struct.unpack_from("<QQ", e, 32)
    name = e[56:128].decode("utf-16-le").rstrip("\0")
    parts.append((name, first, last, str(uuid.UUID(bytes_le=e[16:32]))))

regions = [("gpt_primary.bin", 0, 33, "")]
regions.append(("idblock.bin", 0x40, min(p[1] for p in parts) - 1, ""))
regions += [(n + ".bin", f, l, g) for n, f, l, g in sorted(parts, key=lambda p: p[1])]
regions.append(("gpt_backup.bin", alt_lba - 32, alt_lba, ""))
# Any sectors no region claims get their own gap_*.bin, so the set covers the whole disk.
full, cur = [], 0
for r in regions:
    if r[1] > cur:
        full.append((f"gap_0x{cur:x}-0x{r[1] - 1:x}.bin", cur, r[1] - 1, ""))
    full.append(r)
    cur = r[2] + 1
regions = full
assert regions[0][1] == 0 and regions[-1][2] == alt_lba
assert all(b[1] == a[2] + 1 for a, b in zip(regions, regions[1:])), "regions not contiguous"

lines = []
for fname, first, last, guid in regions:
    path = os.path.join(a.out, fname)
    if fname[:-4] in a.skip:
        print(f"skip {fname}")
    elif fname != "gpt_primary.bin":
        print(f"{fname}  lba 0x{first:x}-0x{last:x}", flush=True)
        rl(first, last - first + 1, path)
    digest = sha256(path) if os.path.exists(path) else "-" * 64
    lines.append(f"{digest}  {fname:<22} lba 0x{first:07x}-0x{last:07x}  "
                 f"{(last - first + 1) * SECTOR >> 10:>9} KiB  "
                 f"rkdeveloptool wl 0x{first:x} {fname}  {guid}".rstrip())

with open(os.path.join(a.out, "MANIFEST.txt"), "w") as m:
    m.write("\n".join(lines) + "\n")

# Rockchip parameter.txt (for `rkdeveloptool gpt parameter.txt`); last partition grows.
mtd = []
for n, f, l, _ in parts:
    size = "-" if (n, f, l) == parts[-1][:3] else f"0x{l - f + 1:08x}"
    mtd.append(f"{size}@0x{f:08x}({n}{':grow' if size == '-' else ''})")
with open(os.path.join(a.out, "parameter.txt"), "w") as p:
    p.write("FIRMWARE_VER:13.0\nMACHINE_MODEL:RK3562\nMACHINE_ID:007\nMANUFACTURER:RK3562\n"
            "MAGIC: 0x5041524B\nATAG: 0x00200800\nMACHINE: 0xffffffff\nCHECK_MASK: 0x80\n"
            "PWR_HLD: 0,0,A,0,1\nTYPE: GPT\n"
            f"CMDLINE:mtdparts=rk29xxnand:{','.join(mtd)}\n")
print("done")
