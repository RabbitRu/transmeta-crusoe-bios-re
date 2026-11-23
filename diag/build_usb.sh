#!/bin/bash
# Build crudiag.img: a USB stick image that boots a Crusoe laptop, runs the
# read-only probes, saves the results to its own FAT32 partition and powers off.
#
#   sudo diag/build_usb.sh WORKDIR        # -> WORKDIR/crudiag.img
#
# Needs (Ubuntu host): debootstrap syslinux syslinux-common mtools dosfstools
# fdisk e2fsprogs gcc-multilib bc flex bison libelf-dev libssl-dev, and the
# linux-source-6.8.0 package. No loop devices or mounts are used.
#
# Why this mix: Crusoe has no PAE and no SSE. Ubuntu i386 kernels need PAE, so
# the kernel is built here from source (MCRUSOE, no PAE, uniprocessor, no PTI,
# no cpufreq so LongRun is read untouched). Userland is Ubuntu 18.04 i386
# (i686 baseline, no SSE), the last Ubuntu with a full i386 archive.
set -euo pipefail
W=$(realpath "${1:?usage: build_usb.sh WORKDIR}")
HERE=$(cd "$(dirname "$0")" && pwd); REPO=$(dirname "$HERE")
R=$W/rootfs; K=$W/linux-source-6.8.0
mkdir -p "$W"

# ---- kernel
if [ ! -f "$K/arch/x86/boot/bzImage" ]; then
    if [ ! -d "$K" ]; then
        (cd "$W" && apt-get download linux-source-6.8.0 && dpkg-deb -x linux-source-6.8.0_*.deb src \
            && tar xjf src/usr/src/linux-source-6.8.0/linux-source-6.8.0.tar.bz2)
    fi
    cd "$K"
    make -s ARCH=i386 i386_defconfig
    scripts/config -d M686 -e MCRUSOE -d SMP -d X86_PAE -e HIGHMEM4G -d HIGHMEM64G \
        -d MITIGATION_PAGE_TABLE_ISOLATION -d PAGE_TABLE_ISOLATION -d CPU_FREQ \
        -d DRM -d SOUND -d WLAN -d WIRELESS \
        -e X86_MSR -e X86_CPUID -e DEVTMPFS -e DEVTMPFS_MOUNT -e ACPI -e APM -e PCI \
        -e USB -e USB_PCI -e USB_UHCI_HCD -e USB_OHCI_HCD -e USB_OHCI_HCD_PCI \
        -e USB_EHCI_HCD -e USB_EHCI_PCI -e USB_STORAGE -e BLK_DEV_SD -e SCSI \
        -e EXT4_FS -e VFAT_FS -e FAT_FS -e MSDOS_PARTITION \
        -e NLS_CODEPAGE_437 -e NLS_ISO8859_1 -e NLS_UTF8 \
        -d WERROR -e PRINTK_TIME -e MAGIC_SYSRQ -e IKCONFIG -e IKCONFIG_PROC \
        -e ATA -e ATA_SFF -e ATA_PIIX -e PATA_ALI
    make -s ARCH=i386 olddefconfig
    make ARCH=i386 -j"$(nproc)" bzImage
    cd "$W"
fi

# ---- root filesystem
if [ ! -x "$R/usr/bin/python3" ]; then
    debootstrap --arch=i386 --variant=minbase --include=python3,pciutils,dmidecode,kmod,util-linux \
        bionic "$R" http://archive.ubuntu.com/ubuntu /usr/share/debootstrap/scripts/gutsy
fi
for d in usr/share/doc usr/share/man usr/share/info var/lib/apt/lists var/cache/apt; do
    find "${R:?}/$d" -mindepth 1 -delete 2>/dev/null || true
done
find "${R:?}/usr/share/locale" -mindepth 1 -maxdepth 1 ! -name locale.alias -exec rm -r {} + 2>/dev/null || true
mkdir -p "$R/crudiag/tools"
cp "$REPO"/tools/crusoe_probe.py "$REPO"/tools/lrti_dump.py "$REPO"/tools/cms_flash_read.py \
   "$HERE"/bench.py "$R/crudiag/tools/"
install -m 755 "$HERE/init" "$R/crudiag/init"

# ---- partitions: p1 FAT32 CRUDIAG (boot + results), p2 ext4 CRUROOT (system)
FAT_MB=64; ROOT_MB=320
SIG=0x43525553                               # MBR disk id -> PARTUUID 43525553-02
IMG=$W/crudiag.img; FAT=$W/p1.fat; EXT=$W/p2.ext4
rm -f "$IMG" "$FAT" "$EXT"
mkfs.vfat -F 32 -n CRUDIAG -C "$FAT" $((FAT_MB * 1024)) >/dev/null
cat > "$W/syslinux.cfg" <<EOF
DEFAULT crudiag
PROMPT 0
TIMEOUT 0
LABEL crudiag
  KERNEL /bzImage
  APPEND root=PARTUUID=43525553-02 rootfstype=ext4 rootwait ro init=/crudiag/init panic=0 loglevel=4
EOF
cp "$HERE/README.txt" "$W/README.txt"
mcopy -i "$FAT" "$K/arch/x86/boot/bzImage" "$W/syslinux.cfg" "$W/README.txt" ::/
mmd -i "$FAT" ::/results
syslinux --install "$FAT"
mke2fs -q -t ext4 -L CRUROOT -O ^metadata_csum,^64bit -d "$R" "$EXT" ${ROOT_MB}M

truncate -s $((1 + FAT_MB + ROOT_MB + 1))M "$IMG"
sfdisk -q "$IMG" <<EOF
label: dos
label-id: $SIG
1MiB,${FAT_MB}MiB,c,*
,${ROOT_MB}MiB,83
EOF
dd if=/usr/lib/syslinux/mbr/mbr.bin of="$IMG" bs=440 count=1 conv=notrunc status=none
dd if="$FAT" of="$IMG" bs=1M seek=1 conv=notrunc status=none
dd if="$EXT" of="$IMG" bs=1M seek=$((1 + FAT_MB)) conv=notrunc status=none
rm -f "$FAT" "$EXT"
echo "built $IMG"
