#!/usr/bin/env python
"""Dump the LongRun frequency/voltage table of a Transmeta Crusoe from a running Linux.

Run as root on the laptop itself after `modprobe msr cpuid`. Works with Python 2 or 3.
It repeats exactly what the Sony R0248E0 BIOS does when it builds its ACPI tables:
read the level count from MSR 0x80868018, select each level by writing its index there,
read MSR 0x80868019/0x8086801A/0x8086801B, and restore MSR 0x80868010 afterwards.
Raw values are printed undecoded on purpose - send the output back for analysis.
"""
import os, struct

def rdmsr(n):
    fd = os.open('/dev/cpu/0/msr', os.O_RDONLY)
    try:
        os.lseek(fd, n, 0); return struct.unpack('<II', os.read(fd, 8))
    finally: os.close(fd)

def wrmsr(n, lo, hi):
    fd = os.open('/dev/cpu/0/msr', os.O_WRONLY)
    try:
        os.lseek(fd, n, 0); os.write(fd, struct.pack('<II', lo, hi))
    finally: os.close(fd)

def cpuid(leaf):
    fd = os.open('/dev/cpu/0/cpuid', os.O_RDONLY)
    try:
        os.lseek(fd, leaf, 0); return struct.unpack('<IIII', os.read(fd, 16))
    finally: os.close(fd)

for leaf in range(0x80860000, 0x80860008):
    print('cpuid %08x: %08x %08x %08x %08x' % ((leaf,) + cpuid(leaf)))
print('CMS info string: %r' % b''.join(struct.pack('<IIII', *cpuid(l)) for l in range(0x80860003, 0x80860007)))

saved = rdmsr(0x80868010)
print('LONGRUN  80868010: lo=%08x hi=%08x' % saved)
print('FLAGS    80868011: lo=%08x hi=%08x' % rdmsr(0x80868011))
lo, hi = rdmsr(0x80868018)
print('READOUT  80868018: lo=%08x hi=%08x  -> %d levels' % (lo, hi, hi + 1))
try:
    for i in range(hi + 1):
        wrmsr(0x80868018, i, 0)
        row = ['%08x:%08x' % rdmsr(m) for m in (0x80868019, 0x8086801a, 0x8086801b)]
        print('level %2d  19=%s  1a=%s  1b=%s' % (i, row[0], row[1], row[2]))
finally:
    wrmsr(0x80868010, saved[0], saved[1])
