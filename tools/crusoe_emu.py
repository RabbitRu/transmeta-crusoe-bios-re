#!/usr/bin/env python3
"""Tiny interpreter for Transmeta Crusoe native code: validate the ISA semantics.

    crusoe_emu.py IMAGE START [--arg40 V ...] [--trace] [--max N]

Executes molecules starting at CMS address START, with the CMS image mapped at
0x8e000 and the rest of a 32 MB space zero-filled. Stops when the code returns
through %link to the sentinel address, or after --max molecules.

Only the opcodes whose meaning is established (docs/crusoe-isa.md) are
implemented; an unknown opcode with a real destination aborts with its address,
which is exactly what we want for validation. Molecules are executed in
parallel: all source reads use the pre-molecule register file.

This is for *checking* our understanding on self-contained routines (e.g. the
CPUID handler), not a full CMS: it has no gated store buffer, no rollback, no
TLB, and memory is a flat little-endian array.
"""
import sys, os, struct
sys.path.insert(0, os.path.dirname(__file__))
from crusoe_isa import *
from crusoe_dis import u32s, classify, BASE, CODE_END

MEM = 32 << 20
SENTINEL = 0x7ffffff8

class Abort(Exception):
    pass

class Machine:
    def __init__(self, img):
        self.m = bytearray(MEM)
        self.m[BASE:BASE + len(img)] = img
        self.g = [0] * 64
        self.spr = {}
        self.g[63] = 0
        self.cc = {}        # condition flags from the last compare/sub
        self.cc2 = {}

    def ld(self, addr, n=4):
        addr &= MEM - 1
        return int.from_bytes(self.m[addr:addr + n], 'little')

    def st(self, addr, val, n=4):
        addr &= MEM - 1
        self.m[addr:addr + n] = (val & ((1 << (8 * n)) - 1)).to_bytes(n, 'little')

def sx(v, bits):
    v &= (1 << bits) - 1
    return v - (1 << bits) if v & (1 << (bits - 1)) else v

def setflags(cc, a, b, res):
    cc['e'] = (res & 0xffffffff) == 0
    cc['ne'] = not cc['e']
    cc['b'] = (a & 0xffffffff) < (b & 0xffffffff)      # unsigned below (CF of a-b)
    cc['nb'] = not cc['b']
    cc['be'] = cc['b'] or cc['e']
    cc['nbe'] = not cc['be']
    sa, sb = sx(a, 32), sx(b, 32)
    cc['l'] = sa < sb
    cc['nl'] = not cc['l']
    cc['le'] = sa <= sb
    cc['nle'] = not cc['le']
    cc['s'] = (res >> 31) & 1
    cc['ns'] = not cc['s']

def run(img, start, args=None, trace=False, maxins=200000):
    M = Machine(img)
    w = u32s(img)
    M.spr[58] = SENTINEL                      # %link
    M.g[47] = MEM - 0x10000                    # %sp in scratch
    for i, v in (args or {}).items():
        M.g[i] = v & 0xffffffff
    ip = start
    for _ in range(maxins):
        if ip == SENTINEL:
            return M
        off = ip - BASE
        kind, n = classify(w[off // 4], w[off // 4 + 1])
        ws = w[off // 4:off // 4 + n]
        reads = dict((i, M.g[i]) for i in range(64))   # snapshot GPRs
        link_now = M.spr.get(58, 0)
        nextip = ip + 4 * n
        branch = None
        imm = ws[0] if 'IMM' in SLOTS[kind] else 0
        if trace:
            print('%06x %s' % (ip, kind))
        for slot, x in zip(SLOTS[kind], ws):
            if slot == 'IMM':
                continue
            if slot == 'BRU':
                branch = exec_bru(M, x, reads, link_now, nextip)
                continue
            exec_alu(M, slot, kind, x, reads, imm, ip)
        M.g[62] = 0
        M.g[63] = 0
        if branch is not None:
            ip = branch
        else:
            ip = nextip
    raise Abort('exceeded %d molecules at %06x' % (maxins, ip))

def exec_bru(M, x, reads, link_now, nextip):
    kind = x >> 29
    if kind not in BR_KIND:
        return None
    cc = (x >> 25) & 15
    ind = (x >> 23) & 1
    if kind == 4:                              # unconditional / call
        if ind:
            tgt = link_now                     # indirect = through %link (prepared by mtsr)
        else:
            tgt = (x & 0x7fffff) << 3
        if cc & 1:                             # call: hardware writes return addr to %link
            M.spr[58] = nextip
        return tgt
    cond = CC[cc]
    table = M.cc if kind == 5 else M.cc2
    if table.get(cond):
        if ind:
            return link_now
        return (x & 0x7fffff) << 3
    return None

def exec_alu(M, slot, kind, x, reads, imm, ip):
    t = (x >> 29) & 3 if slot == 'ALU1' else 0
    op = (x >> 20) & 0x1ff
    rd, rs1, lo = (x >> 14) & 63, (x >> 8) & 63, x & 0xff
    rs2 = lo >> 2
    if not t and x & 0x1fffffff in (0x14b00000, 0x03b00600):
        return
    a = reads[rs1]
    form = opform(op)
    if form == 'imm8':
        b = sx(lo, 8) & 0xffffffff
    elif form == 'imm32':
        b = imm
    else:
        b = reads[rs2]
    # register-bank moves
    if (t, op) in BANK_OPS:
        if op & 8:                              # mt: bank[rs1] = rs2
            if BANK_OPS[(t, op)] == 0:
                M.spr[rs1] = reads[rs2]
        else:                                   # mf: rd = bank[rs1]
            if BANK_OPS[(t, op)] == 0 and rd != 62:
                M.g[rd] = M.spr.get(rs1, 0) & 0xffffffff
        return
    name = opname(op, t)
    def wr(v):
        if rd != 62:
            M.g[rd] = v & 0xffffffff
    if slot == 'LSU':
        if op == 0x050:                         # ld rd,[rs2]
            wr(M.ld(reads[rs2]))
        elif op == 0x044:                       # st [rs2],rs1
            M.st(reads[rs2], reads[rs1])
        elif op == 0x053:                       # ldi rd, rs1, imm8  (word-indexed)
            wr(M.ld((a + sx(lo, 8) * 4) & 0xffffffff))
        elif op == 0x03b:
            pass
        else:
            raise Abort('unknown LSU op %03x at %06x' % (op, ip))
        return
    base = name.rstrip('?')
    if base in ('add', 'addi', 'addil'):
        wr(a + b)
    elif base in ('or', 'ori', 'oril', 'move', 'moveil'):
        wr(a | b)
    elif base in ('and', 'andi', 'andil'):
        wr(a & b)
    elif base in ('xor', 'xori', 'xoril'):
        wr(a ^ b)
    elif base in ('slli',):
        wr(a << (b & 31))
    elif base in ('srli', 'srl'):
        wr((a & 0xffffffff) >> (b & 31))
    elif base.startswith('sub') or base.startswith('cmp'):
        res = (a - b) & 0xffffffff
        setflags(M.cc, a, b, res)
        if rd != 62:
            M.g[rd] = res
    elif base == 'cmp.and':
        # combine: AND this comparison's result into cc2 (approx: edx==0 style)
        M.cc2['cc'] = (a == 0)
    elif base == 'nop':
        pass
    else:
        if rd != 62:
            raise Abort('unknown ALU op %s (%03x t%d) writing %s at %06x' %
                        (name, op, t, GPR[rd], ip))

EXPECT = {   # CPUID handler f_a6798: eax-in -> (eax,ebx,ecx,edx) out, from the image tables
    0x0:         (0x00000003, 0x756e6547, 0x3638784d, 0x54656e69),  # "GenuineTMx86"
    0x1:         (0x00000543, 0, 0, 0),                             # family 5 model 4 step 3
    0x80000000:  (0x80000006, 0x6e617254, 0x55504361, 0x74656d73),  # "TransmetaCPU"
}

def selftest(img):
    ok = True
    for eax, exp in sorted(EXPECT.items()):
        M = run(img, 0xa6798, {0: eax})
        got = (M.g[0], M.g[3], M.g[1], M.g[2])
        good = got == exp
        ok &= good
        print('cpuid eax=%08x -> eax=%08x ebx=%08x ecx=%08x edx=%08x  %s' %
              (eax, M.g[0], M.g[3], M.g[1], M.g[2], 'OK' if good else 'FAIL %r' % (exp,)))
    return ok

def main(argv):
    if '--selftest' in argv:
        img = [a for a in argv[1:] if a != '--selftest'][0]   # IMAGE --selftest or --selftest IMAGE
        sys.exit(0 if selftest(open(img, 'rb').read()) else 1)
    img = open(argv[1], 'rb').read()
    start = int(argv[2], 0)
    args = {}
    i = 3
    while i < len(argv):
        if argv[i] == '--arg40':
            args[40] = int(argv[i + 1], 0); i += 2
        elif argv[i] == '--eax':
            args[0] = int(argv[i + 1], 0); i += 2
        else:
            i += 1
    try:
        M = run(img, start, args, trace='--trace' in argv)
        print('returned. eax=%08x ebx=%08x ecx=%08x edx=%08x' % (M.g[0], M.g[3], M.g[1], M.g[2]))
    except Abort as e:
        print('stopped: %s' % e)
        return None
    return M

if __name__ == '__main__':
    main(sys.argv)
