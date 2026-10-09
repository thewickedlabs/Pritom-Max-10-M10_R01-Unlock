# Pritom Max 10 (M10_R01) — Unlock & Root

The M10_R01 runs Android 13 with a locked bootloader (AVB enforcing), and I couldn't find stock
firmware for this build published anywhere — so imaging it yourself is the only backup. This is the
path I used: reset the vendor loader to maskrom over USB (`rd 3`, no button combo and no opening the
case), build a loader from the tablet's **own** DDR init, image every partition, then unlock by
patching its U-Boot so AVB reports the device unlocked. KernelSU Next roots it from there.

No vendor binaries are shipped — you build the loader from your own device. Two scripts and a runbook.

## Device

- Brand (marketing): PRITOM
- Model (internal): M10_R01
- Marketed as: TAB10 Pro (from the build display ID TAB10 Pro_13.0_US_20240529)
- ODM/manufacturer: incar (INCARTECH — matches the board silkscreen RB631-RK3562)
- Platform/board: RK3562 / rk30sdk
- Release: 13, SDK 33
- Build ID: TQ1A.230105.002.A1
- Build date: 2024-05-29 (incremental 20240529)
- Security patch: 2024-04-05
- Fingerprint: PRITOM/M10_R01/M10_R01:13/TQ1A.230105.002.A1/20240529:user/release-keys
- SoC: Rockchip RK3562
- CPU: quad-core (4× ARM Cortex-A53, nproc=4, implementer 0x41 = ARM), max ~2.016 GHz
- PMIC: Rockchip RK817
- RAM type: LPDDR4 ("LP4" in the board name)
- GPU (per SoC spec): ARM Mali-G52

Product page: https://www.pritom-tech.com/tables/m10

## Tools

Download both scripts as a zip from the [latest release](https://github.com/thewickedlabs/Pritom-Max-10-M10_R01-Unlock/releases/latest/download/Pritom-Max-10-M10_R01-Unlock-tools.zip), or grab them straight from this repo:
[`dump_M10_R01.py`](dump_M10_R01.py) · [`bootlicker_M10_R01.py`](bootlicker_M10_R01.py).

- **`dump_M10_R01.py OUT_DIR [--skip NAME ...]`** — with the device in usbplug, reads the live GPT and
  writes every partition (plus idblock, GPT copies and inter-partition gaps) to its own `.bin`, with a
  `MANIFEST.txt` (sha256 + flash command per region) and a `parameter.txt`.
- **`bootlicker_M10_R01.py STOCK_UBOOT.bin [OUT.bin]`** — offline; patches `rk_avb_read_lock_state` in a
  stock `uboot_a` image so it reports **unlocked**, re-hashes both FIT copies, and writes
  `*_patched.bin`. It never touches a device. Flash the result with `rkdeveloptool wl 0x4000 <out>`
  (and `wl 0x6000` for the B slot); the stock image restores it.

---

# PREP — building the maskrom loader and taking a full firmware dump (Linux)

Runbook for the Pritom M10_R01 (RK3562, board RB631). As run on my system; adjust for yours. YMMV.

## 0. Host prerequisites

    sudo pacman -S --needed dtc aarch64-linux-gnu-binutils zstd git
    paru -S --needed rkdeveloptool-git

- `rkdeveloptool` drives maskrom/usbplug over USB.
- `dtc` + `aarch64-linux-gnu-binutils` are only for inspecting DTBs / U-Boot (not the dump itself).
- `zstd` for compressing userdata.
- USBGuard blocks each new USB identity: when maskrom (`2207:350d`, empty serial) and usbplug
  (`USB-MSC`) first appear, approve them in the popup. Nothing here disables USBGuard.

## 1. Build the working maskrom loader

The generic rkbin RK3562 DDR blob hangs this board's DRAM init. The fix is to pack a loader that uses
the tablet's **own** DDR init (the TPL from its idblock) with rkbin's generic usbplug + SPL. This needs
your device's `idblock.bin` (it sits in the readable bootloader region, so you can pull it with the
vendor loader before building this, or take it from a dump).

    # a) get rkbin's packer + generic RK3562 blobs (sparse, no full history)
    git clone --depth 1 --filter=blob:none --sparse https://github.com/rockchip-linux/rkbin.git
    cd rkbin
    git sparse-checkout set --no-cone /tools/boot_merger /bin/rk35/rk3562_* /RKBOOT/RK3562MINIALL.ini

    # b) carve the tablet's own DDR TPL out of its idblock (RKNS image #1)
    dd if=/path/to/idblock.bin of=bin/rk35/rk3562_ddr_vendor_v1.04.bin bs=512 skip=4 count=$((0x6c)) status=none
    sha256sum bin/rk35/rk3562_ddr_vendor_v1.04.bin   # matches the idblock header's img-1 hash @0x90

    # c) point the 471 (DDR) stage at that vendor TPL; keep usbplug v1.04 + spl v1.08
    sed -e 's#rk3562_ddr_1332MHz_v1.10.bin#rk3562_ddr_vendor_v1.04.bin#g' \
        -e 's#^PATH=.*#PATH=rk3562_loader_vendorddr.bin#' \
        RKBOOT/RK3562MINIALL.ini > RKBOOT/RK3562VENDOR.ini

    # d) pack
    ./tools/boot_merger RKBOOT/RK3562VENDOR.ini
    cp rk3562_loader_vendorddr.bin ..
    cd ..

Result: `rk3562_loader_vendorddr.bin` — DDR v1.04 (device-specific) + usbplug v1.04 + spl v1.08
(SoC-generic). It only has to bring up DRAM and expose rockusb for RAM-level reads/writes.

## 2. Enter maskrom → usbplug

    adb -s <SERIAL> reboot loader                 # into the vendor U-Boot rockusb loader
    sudo rkdeveloptool ld                         # -> "...Loader"
    sudo rkdeveloptool rd 3                        # reset to BootROM download (writes BOOT_BROM_DOWNLOAD)
    sudo rkdeveloptool ld                         # -> "...Maskrom"
    sudo rkdeveloptool db rk3562_loader_vendorddr.bin   # DDR+usbplug into RAM
    sudo rkdeveloptool rfi                         # sanity: Flash Size 59640 MB / 122142720 sectors

Everything in usbplug is RAM-resident and the eMMC is untouched until an explicit `wl`.

## 3. Full dump (userdata first, then every other region)

userdata is largest (~57 GB raw) and highly compressible, so dump it first, compress, verify, then
delete the raw before dumping the rest. One command per line:

    mkdir -p firmware
    sudo rkdeveloptool rl $((0xa1bc00)) $((0x747bfbf - 0xa1bc00 + 1)) firmware/userdata.img
    sudo chown "$USER": firmware/userdata.img
    mv firmware/userdata.img firmware/userdata.bin
    sha256sum firmware/userdata.bin | tee firmware/userdata.bin.sha256
    zstd -9 -T0 firmware/userdata.bin -o firmware/userdata.bin.zst
    zstd -dc firmware/userdata.bin.zst | sha256sum          # must match the hash from the line above
    rm firmware/userdata.bin                                # only after the two hashes match
    python3 dump_M10_R01.py firmware --skip userdata        # every other region

The `rl` range (`0xa1bc00 .. 0x747bfbf`) is userdata's LBA span from this build's GPT.

`dump_M10_R01.py` reads the **live primary GPT** and writes, contiguously covering LBA 0 to the backup
GPT: `gpt_primary.bin`, `idblock.bin`, each of the 25 partitions, any inter-partition `gap_*.bin`, and
`gpt_backup.bin`. It also emits:
- `MANIFEST.txt` — sha256, LBA range and a `rkdeveloptool wl <lba> <file>` line per region.
- `parameter.txt` — the Rockchip GPT table (`rkdeveloptool gpt parameter.txt`).

Files use the `.bin` extension (raw byte-for-byte images; no tool cares about the extension).

## 4. Checksumming / verification

- `firmware/MANIFEST.txt` carries the sha256 of every non-userdata region as written.
- `firmware/userdata.bin.sha256` carries the raw userdata hash; the zstd stream was verified against it
  before the raw was deleted, so `zstd -dc userdata.bin.zst | sha256sum` reproduces it.
- To re-verify a region later, read it back and compare:

      sudo rkdeveloptool rl <lba> <count> /tmp/x.bin
      sha256sum /tmp/x.bin                                 # compare against MANIFEST.txt

## 5. Finish

    sudo rkdeveloptool rd        # reboot back into Android

> Reboot quirk: with the battery disconnected, a soft reset from usbplug/fastboot sometimes leaves the
> board powered off instead of restarting — do a physical power cycle (USB out, battery out briefly,
> back in). `rd 3` from the vendor U-Boot loader always comes back on its own.

---

These tools and notes are provided as-is, for use on hardware you own. Flashing a bootloader can brick
a device. You run them entirely at your own risk; the authors accept no liability for any damage, data
loss, or bricked hardware. No warranty of any kind.

Wicked Labs · https://www.cyberspace7.org
