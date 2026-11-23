#!/usr/bin/env python3
"""High-level, data-only patches to a decompressed CMS image (no opcode guessing).

    cms_patch.py IN.image OUT.image [patches...]

Patches (all operate on the CPUID data tables located in docs/cms-architecture.md):
    --tfms FAMILY MODEL STEPPING   set CPUID.1:EAX type/family/model/stepping
    --family6                      shortcut: report family 6 (keeps model/stepping)
    --vendor "GenuineIntel"        set the 12-byte vendor string (CPUID.0)
    --dump                         print current CPUID tables and exit

These edit the CPUID data that f_a6798 returns (verified by tools/crusoe_emu.py).
They do NOT add instructions or change behaviour beyond what the processor
reports, so they are safe to reason about. The result still needs repacking
(tools/cru_pack.py) and can only reach a chip via SROM programming or a RAM
patch; the normal signed-update path will reject it.

Table addresses (CMS space): standard leaf 0 = 0x18aaa0 (eax=maxleaf, then the
vendor string in ebx,edx,ecx order), leaf 1 = 0x18aab0 (eax=TFMS).
"""
import sys, struct

BASE = 0x8e000
LEAF0 = 0x18aaa0 - BASE
LEAF1 = 0x18aab0 - BASE

def dump(d):
    e = struct.unpack_from('<4I', d, LEAF0)
    vs = struct.pack('<III', e[1], e[3], e[2])          # ebx, edx, ecx
    print('CPUID.0  maxleaf=%d  vendor=%r' % (e[0], vs))
    t = struct.unpack_from('<I', d, LEAF1)[0]
    print('CPUID.1  EAX=%08x  type=%d family=%d model=%d stepping=%d' %
          (t, (t >> 12) & 3, (t >> 8) & 0xf, (t >> 4) & 0xf, t & 0xf))

def main(a):
    d = bytearray(open(a[1], 'rb').read())
    if '--dump' in a:
        dump(d); return
    out = a[2]
    i = 3
    while i < len(a):
        o = a[i]
        if o == '--tfms':
            fam, mod, st = int(a[i+1]), int(a[i+2]), int(a[i+3]); i += 4
            t = struct.unpack_from('<I', d, LEAF1)[0]
            t = (t & ~0x3fff) | (fam << 8) | (mod << 4) | st
            struct.pack_into('<I', d, LEAF1, t)
            print('set TFMS -> %08x' % t)
        elif o == '--family6':
            t = struct.unpack_from('<I', d, LEAF1)[0]
            t = (t & ~0xf00) | (6 << 8)
            struct.pack_into('<I', d, LEAF1, t)
            print('set family 6 -> %08x' % t); i += 1
        elif o == '--vendor':
            v = a[i+1].encode(); i += 2
            v = (v + b'\0' * 12)[:12]
            ebx, edx, ecx = struct.unpack('<III', v)
            struct.pack_into('<I', d, LEAF0 + 4, ebx)
            struct.pack_into('<I', d, LEAF0 + 8, ecx)
            struct.pack_into('<I', d, LEAF0 + 12, edx)
            print('set vendor %r' % v)
        else:
            i += 1
    open(out, 'wb').write(d)
    print('wrote %s' % out)
    dump(d)

if __name__ == '__main__':
    main(sys.argv)
