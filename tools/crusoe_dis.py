#!/usr/bin/env python3
"""Disassembler / pseudo-C decompiler for Transmeta Crusoe TM5x00 native code.

    crusoe_dis.py IMAGE [START [END]] [-c] [-b BASE] [--raw] [--stats]

IMAGE  decompressed CMS image (tools/cru.py FILE out/ writes it as *.image)
START  CMS address to start at (default: BASE, i.e. start of image)
END    CMS address to stop at (default: end of the code region, 0x1823f0)
-c     print pseudo-C next to each atom instead of assembly
-b     load address of the image in CMS space (default 0x8e000)
--raw  also print the raw words of each molecule
--stats  print the molecule census instead of a listing (--linear: no resync,
          reproduces the census published in Crusoe Exposed)

Addresses are CMS physical-space addresses (image offset + 0x8e000), the same
numbering used by "Crusoe Exposed". The output of the default mode is accepted
unchanged by crusoe_asm.py, which reassembles it bit-for-bit.
"""
import sys, struct, collections
sys.path.insert(0, __import__('os').path.dirname(__file__))
from crusoe_isa import *

BASE = 0x8e000
CODE_END = 0x1823f0

def u32s(img):
    return struct.unpack('<%dI' % (len(img) // 4), img[:len(img) // 4 * 4])

def molecules(w, base, start, end, sync=None):
    """Yield (addr, kind, words) for consecutive molecules in [start, end).

    sync: set of addresses known to start a molecule (branch targets). A
    molecule that would straddle one of them is emitted as kind 'DATA'
    (one 32-bit word at a time) until the stream re-aligns: this skips the
    zero padding and literal words the compiler leaves between functions.
    """
    i = (start - base) // 4
    stop = (end - base) // 4
    sync = sync or ()
    while i + 1 < len(w) and i < stop:
        kind, n = classify(w[i], w[i + 1])
        a = base + i * 4
        if sync and any(a + 4 * j in sync for j in range(1, n)):
            yield a, 'DATA', w[i:i + 1]
            i += 1
            continue
        yield a, kind, w[i:i + n]
        i += n

_SYNC = {}
def sync_points(w, base, end):
    """Branch targets, iterated to a fixed point (cached per image)."""
    key = (id(w), base, end)
    if key in _SYNC:
        return _SYNC[key]
    sync = set()
    for _ in range(4):
        new = set()
        for a, kind, ws in molecules(w, base, base, end, sync):
            if kind in (K_Q_BRU, K_AB):
                x = ws[0]
                if x >> 29 in BR_KIND and not (x >> 23) & 1:
                    t = (x & 0x7fffff) << 3
                    if base <= t < end:
                        new.add(t)
        if new == sync:
            break
        sync = new
    _SYNC[key] = sync
    return sync

def sx8(v):
    return v - 256 if v & 0x80 else v

def free_top(kind, k, slot):
    """(mask of free bits in [31:29], implied value) for word k of a molecule."""
    if k == 1:
        # second word: format bits fixed; bit31 fixed for 128-bit kinds
        return (0 if kind in (K_Q_IMM, K_Q_BRU) else 4), FORMAT_BITS[kind]
    return 7, 0

# ------------------------------------------------------------- atom formatting
# Grammar:  mnemonic[.c][.tN][.sN] operands
#   .cm  bit31 of the atom when it is not part of the format (commit flag?)
#   .tN  bits [30:29] for LSU atoms (ALU1 carries them in the mnemonic: tN.opXXX)
#   .sN  bits [1:0] of register-form atoms when not 3 (CMS prints .00 .. .11)
def fmt_alu(x, slot, kind, k):
    mask, implied = free_top(kind, k, slot)
    top = x >> 29
    c = (top >> 2) & 1 if mask & 4 else 0
    t = top & 3 if mask & 3 else 0
    op = (x >> 20) & 0x1ff
    rd, rs1, lo = (x >> 14) & 63, (x >> 8) & 63, x & 0xff
    ot = t if slot == 'ALU1' else 0
    name = opname(op, ot)
    sfx = ('.cm' if c else '') + ('.t%d' % t if t and slot != 'ALU1' else '')
    if not ot and x & 0x1fffffff == 0x14b00000:
        return 'nop' + sfx
    if not ot and x & 0x1fffffff == 0x03b00600:
        return 'nop.lsu' + sfx
    form = opform(op)
    if form == 'imm8':
        return '%s%s %s, %s, %d' % (name, sfx, GPR[rd], GPR[rs1], sx8(lo))
    if form == 'imm32':
        s = '%s%s %s, %s, <imm>' % (name, sfx, GPR[rd], GPR[rs1])
        return s + (', #%d' % lo if lo else '')
    if lo & 3 != 3:
        sfx += '.s%d' % (lo & 3)
    if op == 0x050 and not ot:
        return 'ld%s %s, [%s], m=%d' % (sfx, GPR[rd], GPR[lo >> 2], rs1)
    if op == 0x044 and not ot:
        return 'st%s [%s], %s, m=%d' % (sfx, GPR[lo >> 2], GPR[rs1], rd)
    r1 = SPR[rs1] if (ot, op) in SPR_OPS else GPR[rs1]
    return '%s%s %s, %s, %s' % (name, sfx, GPR[rd], r1, GPR[lo >> 2])

def br_target(x, base):
    return (x & 0x7fffff) << 3

def fmt_bru(x, labels):
    kind, cc, xb, ind = x >> 29, (x >> 25) & 15, (x >> 24) & 1, (x >> 23) & 1
    if kind not in BR_KIND:
        return 'bru.raw 0x%08x' % x
    if kind == 4:
        m = 'call' if cc & 1 else 'br'
        if cc & ~1:
            m += '.k%d' % (cc & ~1)
    else:
        m = ('brc.' if kind == 5 else 'brc2.') + CC[cc]
    if xb:
        m += '.x'
    if ind:
        return '%s.ind #0x%x' % (m, x & 0x7fffff)
    t = (x & 0x7fffff) << 3
    return '%s %s' % (m, labels.get(t, '0x%x' % t))

# ------------------------------------------------------------- pseudo-C
def cname(r):
    n = GPR[r][1:]
    return n + ('/*%s*/' % X86_ALIAS[r] if r in X86_ALIAS else '')

C_BIN = {'add': '+', 'or': '|', 'and': '&', 'sll': '<<'}

def c_alu(x, imm, slot, kind, k):
    op = (x >> 20) & 0x1ff
    rd, rs1, lo = (x >> 14) & 63, (x >> 8) & 63, x & 0xff
    ot = (x >> 29) & 3 if slot == 'ALU1' else 0
    if not ot and x & 0x1fffffff in (0x14b00000, 0x03b00600):
        return None
    name = opname(op, ot).rstrip('?')
    if (ot, op) == (2, 0x060):
        return '%s = %s;' % (cname(rd), SPR[rs1][1:])
    if (ot, op) == (2, 0x068):
        return '%s = %s;  /* br.prep */' % (SPR[rs1][1:], cname(lo >> 2))
    form = opform(op)
    if op == 0x050:
        return '%s = load.m%d(%s);' % (cname(rd), rs1, cname(lo >> 2))
    if op == 0x044:
        return 'store.m%d(%s, %s);' % (rd, cname(lo >> 2), cname(rs1))
    b = '%s' % cname(lo >> 2) if form == 'reg' else (
        '%d' % sx8(lo) if form == 'imm8' else ('0x%x' % imm if imm is not None else '<imm>'))
    base = name.rstrip('il').rstrip('i') if form != 'reg' else name
    if name.startswith('cmp'):
        return 'cc = %s(%s, %s);' % (name, cname(rs1), b)
    if base in C_BIN:
        if rs1 == 63 and base in ('add', 'or'):
            rhs = b
        else:
            rhs = '%s %s %s' % (cname(rs1), C_BIN[base], b)
    elif name == 'slli':
        rhs = '%s << %s' % (cname(rs1), b)
    else:
        rhs = '%s(%s, %s)' % (name, cname(rs1), b)
    if rd == 62:
        return '(void)(%s);' % rhs
    return '%s = %s;' % (cname(rd), rhs)

def c_bru(x, labels):
    kind, cc, ind = x >> 29, (x >> 25) & 15, (x >> 23) & 1
    if kind not in BR_KIND:
        return '/* bru 0x%08x */' % x
    if ind:
        # the target is the branch register set by br.prep (almost always %link)
        if kind == 4 and not cc & 1:
            return 'goto *link;  /* return, hint 0x%x */' % (x & 0x7fffff)
        tgt = '*link'
    else:
        t = (x & 0x7fffff) << 3
        tgt = labels.get(t, 'L_%x' % t)
    if kind == 4:
        return ('%s();' if cc & 1 else 'goto %s;') % tgt
    return 'if (%scc.%s) goto %s;' % ('' if kind == 5 else 'cc2.', CC[cc], tgt)

# ------------------------------------------------------------- listing
def collect_labels(w, base, start, end):
    calls, jumps = collections.Counter(), collections.Counter()
    sync = sync_points(w, base, end)
    for a, kind, ws in molecules(w, base, start, end, sync):
        if kind in (K_Q_BRU, K_AB):
            x = ws[0]
            if x >> 29 in BR_KIND and not (x >> 23) & 1:
                t = (x & 0x7fffff) << 3
                (calls if x >> 29 == 4 and (x >> 25) & 1 else jumps)[t] += 1
    starts = {a for a, kind, ws in molecules(w, base, start, end, sync) if kind != 'DATA'}
    bad = [t for t in list(jumps) + list(calls) if t not in starts]
    for t in bad:                       # target not on a molecule boundary: keep numeric
        jumps.pop(t, None); calls.pop(t, None)
    labels = {}
    for t in jumps:
        labels[t] = 'L_%x' % t
    for t in calls:
        labels[t] = 'f_%x' % t
    return labels, calls

def disasm(img, start=None, end=None, base=BASE, pseudo=False, raw=False, out=sys.stdout):
    w = u32s(img)
    start = base if start is None else start
    end = min(end or CODE_END, base + len(img))
    cend = min(CODE_END, base + len(img))
    labels, calls = collect_labels(w, base, base, cend)
    sync = sync_points(w, base, cend)
    for a, kind, ws in molecules(w, base, start, end, sync):
        if a in labels:
            out.write('%s:%s\n' % (labels[a], '    ; %d callers' % calls[a] if a in calls else ''))
        if kind == 'DATA':
            out.write('  %06x: .word 0x%08x\n' % (a, ws[0]))
            continue
        slots = SLOTS[kind]
        imm = ws[0] if 'IMM' in slots else None
        parts = []
        for k, (slot, x) in enumerate(zip(slots, ws)):
            if slot == 'IMM':
                parts.append(('IMM', 'imm 0x%08x' % x, None))
            elif slot == 'BRU':
                parts.append(('BRU', fmt_bru(x, labels), c_bru(x, labels)))
            else:
                parts.append((slot, fmt_alu(x, slot, kind, k), c_alu(x, imm, slot, kind, k)))
        if pseudo:
            cs = [c for s, t, c in parts if s != 'IMM' and c]
            out.write('  %06x:  %s\n' % (a, '  '.join(cs) if cs else ';'))
        else:
            body = ' | '.join('%s %s' % (s, t) for s, t, c in parts)
            line = '  %06x: %-5s %s' % (a, kind, body)
            if raw:
                line += '    ; ' + ' '.join('%08x' % x for x in ws)
            out.write(line + '\n')

def stats(img, base=BASE, linear=False):
    w = u32s(img)
    end = min(CODE_END, base + len(img))
    c = collections.Counter(k for a, k, ws in molecules(w, base, base, end, None if linear else sync_points(w, base, end)))
    n64 = sum(v for k, v in c.items() if not k.startswith('Q'))
    n128 = c[K_Q_IMM] + c[K_Q_BRU]
    print('molecules: %d (64-bit %d, 128-bit %d)' % (n64 + n128, n64, n128))
    for k in KINDS + ('DATA',):
        print('  %-6s %d' % (k, c[k]))
    print('(the published census, 78460/23297, counts a purely linear parse: use --linear)')

def main(argv):
    args = [a for a in argv[1:] if not a.startswith('-')]
    base = BASE
    if '-b' in argv:
        base = int(argv[argv.index('-b') + 1], 0)
        args.remove(argv[argv.index('-b') + 1])
    img = open(args[0], 'rb').read()
    if '--stats' in argv:
        return stats(img, base, '--linear' in argv)
    start = int(args[1], 0) if len(args) > 1 else None
    end = int(args[2], 0) if len(args) > 2 else None
    disasm(img, start, end, base, pseudo='-c' in argv, raw='--raw' in argv)

if __name__ == '__main__':
    main(sys.argv)
