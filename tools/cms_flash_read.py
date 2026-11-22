#!/usr/bin/env python3
"""Back up CMS flash regions (incl. the OEM Configuration Table) from a running Linux.

    modprobe msr
    python3 cms_flash_read.py --sizes              # safe: only rdmsr
    python3 cms_flash_read.py --read 3 oct.bin --i-understand
    python3 cms_flash_read.py --read 1 cms1.bin --i-understand

Protocol (recovered from F1542_CMSDrv.sys in HP SoftPaq SP23689, functions
CheckROMExist / IoctlCMSReadCMS / IoctlCMSGetCMSSize):

    rdmsr 0x8086800N            EDX = size of region N in dwords (N = 1..5)
    wrmsr 0x80868000            EAX = buffer address, EDX = 0x8086800N
                                -> CMS copies region N into the buffer
    rdmsr 0x80868000            EAX = status, 0 = success

Region 3 is the OEM Configuration Table: the driver checks that it starts with
"OEM Conf Header" and holds "Transmeta(tm) Crusoe(tm) Processor" at +0x1be.
The meaning of regions 1, 2, 4, 5 is not confirmed (primary/recovery CMS are
the likely candidates) - look at the sizes first.

The Windows driver passes a *virtual* address from the kernel pool, and the
BIOS a flat address, so CMS treats EAX as a linear address translated by the
current page tables. On a uniprocessor Linux the msr driver executes WRMSR
in the context of the calling process, so an mlock()ed buffer of this process
is used. This has NOT been tested on real hardware yet: on a multi-CPU or
PTI kernel it would be wrong. The write commands (IoctlCMSWriteCMS) are
deliberately not implemented.
"""
import ctypes, mmap, os, struct, sys

def rdmsr(n):
    fd = os.open('/dev/cpu/0/msr', os.O_RDONLY)
    try:
        os.lseek(fd, n, 0)
        return struct.unpack('<II', os.read(fd, 8))
    finally:
        os.close(fd)

def wrmsr(n, lo, hi):
    fd = os.open('/dev/cpu/0/msr', os.O_WRONLY)
    try:
        os.lseek(fd, n, 0)
        os.write(fd, struct.pack('<II', lo, hi))
    finally:
        os.close(fd)

def sizes():
    out = {}
    for n in range(1, 6):
        try:
            eax, edx = rdmsr(0x80868000 + n)
            out[n] = edx
            print('region %d: eax=%08x edx=%08x -> %d bytes' % (n, eax, edx, edx * 4))
        except OSError as e:
            print('region %d: rdmsr failed (%s)' % (n, e))
    return out

def read_region(n, path):
    if os.sysconf('SC_NPROCESSORS_ONLN') != 1:
        sys.exit('refusing: more than one CPU online (WRMSR could run in another context)')
    words = rdmsr(0x80868000 + n)[1]
    if not 0 < words < (4 << 20):
        sys.exit('region %d size %d dwords looks wrong' % (n, words))
    size = (words * 4 + 0x10000 + 4095) & ~4095          # 64 KB guard
    buf = mmap.mmap(-1, size, mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS)
    addr = ctypes.addressof(ctypes.c_char.from_buffer(buf))
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.mlock(ctypes.c_void_p(addr), ctypes.c_size_t(size)) != 0:
        sys.exit('mlock failed: errno %d' % ctypes.get_errno())
    buf[:] = b'\xa5' * size                               # fault every page in
    if addr >> 32:
        sys.exit('buffer above 4 GB, cannot pass in EAX')
    wrmsr(0x80868000, addr, 0x80868000 + n)
    status = rdmsr(0x80868000)[0]
    data = buf[:words * 4]
    open(path, 'wb').write(data)
    print('region %d: status %08x, %d bytes -> %s; guard intact: %s' % (
        n, status, len(data), path, buf[words * 4:] == b'\xa5' * (size - words * 4)))
    if n == 3:
        print('OEM header ok: %s' % data.startswith(b'OEM Conf Header'))

def main(a):
    if '--sizes' in a or len(a) == 1:
        sizes()
    if '--read' in a:
        if '--i-understand' not in a:
            sys.exit('add --i-understand: this asks CMS to write into this process memory')
        i = a.index('--read')
        read_region(int(a[i + 1]), a[i + 2])

if __name__ == '__main__':
    main(sys.argv)
