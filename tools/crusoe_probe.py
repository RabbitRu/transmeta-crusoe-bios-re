#!/usr/bin/env python
"""Read-only probe of everything a BIOS can see/set about CMS, from a running Linux.

    modprobe msr cpuid; python crusoe_probe.py > probe-<machine>.txt

Works with Python 2 or 3, needs root. Nothing is written except the two
documented "select" MSRs (LongRun table index 0x80868018), which are restored.
Sections:
  1. CPUID standard/Transmeta leaves, CMS version string
  2. Transmeta MSRs: CPUID_TFMS / VND / MASK, LONGRUN, LONGRUN_FLAGS
  3. LongRun table (per level: perf %, MHz, mV, memory/PCI divisors, gate delay,
     SDR/DDR timing words 0x8086803x)
  4. CMS flash region sizes (rdmsr 0x80868001..5 -> EDX = size in dwords)
  5. Northbridge config (PCI 00:00.0 and 00:00.1): TOM, PM_CR2_OPT, LR_ATM,
     PERF_CTRL, PCI arbiter, SPD/timing registers the BIOS programs for CMS
Send the whole output back; values are printed raw.
"""
import os, struct, sys

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

def try_rdmsr(n):
    try:
        return '%08x:%08x' % (lambda v: (v[1], v[0]))(rdmsr(n))
    except (OSError, IOError) as e:
        return 'GP/err (%s)' % e.__class__.__name__

def cpuid(leaf):
    fd = os.open('/dev/cpu/0/cpuid', os.O_RDONLY)
    try:
        os.lseek(fd, leaf, 0)
        return struct.unpack('<IIII', os.read(fd, 16))
    finally:
        os.close(fd)

def section(t):
    print('\n== ' + t)

section('1. CPUID')
for leaf in (0, 1, 0x80000000, 0x80000001, 0x80000005, 0x80000006):
    print('cpuid %08x: eax=%08x ebx=%08x ecx=%08x edx=%08x' % ((leaf,) + cpuid(leaf)))
for leaf in range(0x80860000, 0x80860008):
    print('cpuid %08x: eax=%08x ebx=%08x ecx=%08x edx=%08x' % ((leaf,) + cpuid(leaf)))
s = b''.join(struct.pack('<IIII', *cpuid(l)) for l in range(0x80860003, 0x80860007))
print('CMS info string: %r' % s.split(b'\0')[0])

section('2. Transmeta MSRs (edx:eax)')
for n, name in ((0x80860000, 'CPUID_TFMS'), (0x80860001, 'CPUID_VND1'), (0x80860002, 'CPUID_VND2'),
                (0x80860003, 'CPUID_VND3'), (0x80860004, 'CPUID_MASK'), (0x80868010, 'LONGRUN'),
                (0x80868011, 'LONGRUN_FLAGS'), (0x80868018, 'LRTI_READOUT'), (0x119, 'PSN_CTL(0x119)')):
    print('%08x %-14s %s' % (n, name, try_rdmsr(n)))

section('3. LongRun table')
try:
    cur = rdmsr(0x80868018)
    levels = cur[1] + 1
    print('%d levels (level 0 = fastest)' % levels)
    for i in range(levels):
        wrmsr(0x80868018, i, 0)
        row = ' '.join('%x=%s' % (m & 0xff, try_rdmsr(m)) for m in
                       (0x80868019, 0x8086801a, 0x8086801b, 0x8086801c, 0x8086801d))
        mem = ' '.join('%x=%s' % (m & 0xff, try_rdmsr(m)) for m in range(0x80868030, 0x80868038))
        print('level %2d  %s\n          %s' % (i, row, mem))
    wrmsr(0x80868018, cur[0], 0)
except (OSError, IOError) as e:
    print('LRTI not available: %s' % e)

section('4. CMS flash regions (rdmsr 0x8086800N, EDX = size in dwords; N=3 is the OEM config table)')
for n in range(0x80868000, 0x80868006):
    print('%08x %s' % (n, try_rdmsr(n)))

section('5. Northbridge PCI config')
def pcicfg(fn):
    p = '/sys/bus/pci/devices/0000:00:00.%d/config' % fn
    try:
        return open(p, 'rb').read()
    except (OSError, IOError):
        return None
NB0 = {0x08: ('RID0 (2=CMS4.2 3=CMS4.3+)', 1), 0x4a: ('TOM (CMS memory start >>16)', 2),
       0x74: ('SD_MISC', 4), 0x7a: ('PM_CR', 1), 0x7b: ('PM_CR2_OPT (bit0 PSM_EN: +1 clk mem latency)', 1),
       0x80: ('SD_TIF0', 4), 0x84: ('SD_TIF1', 4), 0x90: ('SD_MRS0', 2), 0x92: ('SD_MRS1', 2),
       0xa4: ('OEMOPT', 4), 0xa8: ('LR_ATM (bit4 ATM_EN, 3:1 level)', 1),
       0xa9: ('PERF_CTRL (bit0 = WinXP-boot tuning)', 1), 0xac: ('PCI_ARB_CTRL', 4),
       0xfc: ('MASTER_CLK', 2), 0xfe: ('MEM_DIV', 1), 0xff: ('PCI_DIV', 1)}
NB1 = {0x40: 'SD_CTRL', 0x60: 'B0_GEOMETRY1', 0x64: 'B0_GEOMETRY2', 0x68: 'B0_CYCLE', 0x6c: 'B0_REFRESH',
       0x70: 'B0_MISC', 0x74: 'B0_TIMING_CL1', 0x78: 'B0_TIMING_CL2', 0x7c: 'B0_TIMING_RAS',
       0x80: 'B0_ADDRESS_AND_DATA', 0x9c: 'B0_SPD_REV', 0xa0: 'B0_AUX1', 0xa4: 'B0_AUX2', 0xa8: 'B0_ERROR',
       0xb0: 'B1_GEOMETRY1', 0xb8: 'B1_CYCLE', 0xbc: 'B1_REFRESH', 0xc0: 'B1_MISC', 0xc4: 'B1_TIMING_CL1',
       0xc8: 'B1_TIMING_CL2', 0xcc: 'B1_TIMING_RAS', 0xf8: 'B1_ERROR'}
c0 = pcicfg(0)
if c0 is None or len(c0) < 256:
    print('00:00.0 config not readable in full (need root; /sys/bus/pci)')
else:
    print('00:00.0 vendor/device %04x:%04x' % struct.unpack_from('<HH', c0, 0))
    for off in sorted(NB0):
        name, sz = NB0[off]
        v = {1: c0[off:off + 1], 2: c0[off:off + 2], 4: c0[off:off + 4]}[sz]
        print('  %02xh %-46s %s' % (off, name, ''.join('%02x' % b for b in bytearray(v[::-1]))))
c1 = pcicfg(1)
if c1 is not None and len(c1) >= 256:
    print('00:00.1 vendor/device %04x:%04x' % struct.unpack_from('<HH', c1, 0))
    for off in sorted(NB1):
        print('  %02xh %-20s %08x' % (off, NB1[off], struct.unpack_from('<I', c1, off)[0]))
for fn in (0, 1, 2):
    c = pcicfg(fn)
    if c is not None:
        print('raw 00:00.%d:' % fn)
        for o in range(0, len(c), 16):
            print('  %02x: %s' % (o, ' '.join('%02x' % b for b in bytearray(c[o:o + 16]))))
