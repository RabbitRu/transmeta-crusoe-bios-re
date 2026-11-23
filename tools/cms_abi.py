#!/usr/bin/env python3
"""Recover the calling convention (ABI) of CMS from the image, statistically.

    python3 tools/cms_abi.py IMAGE

For every function entered by `call` it looks at:
  * prologue: stack adjustment, registers stored to the frame, mfsr %link
  * epilogue: mtsr %link + indirect return, registers reloaded
  * live-in registers (read before written on the straight-line entry path)
  * registers written just before return (return-value candidates)
  * registers read right after a call returns (what callers expect back)
  * registers callers rely on across calls (live across the call)
Register reads/writes are derived from the atom fields; molecules are treated
as parallel (all reads of a molecule happen before its writes).
"""
import sys, os, collections
sys.path.insert(0, os.path.dirname(__file__))
from crusoe_dis import *

SP, LINK = 47, 58

def atom_rw(slot, x):
    """(reads, writes) as sets of GPR numbers for one ALU/LSU atom; None if unknown."""
    t = (x >> 29) & 3 if slot == 'ALU1' else 0
    op = (x >> 20) & 0x1ff
    if not t and x & 0x1fffffff in (0x14b00000, 0x03b00600):
        return set(), set()
    rd, rs1, lo = (x >> 14) & 63, (x >> 8) & 63, x & 0xff
    rs2 = lo >> 2
    form = opform(op)
    if (t, op) in BANK_OPS:
        return ({rs2} if op & 8 else set()), (set() if op & 8 else {rd})
    if slot == 'LSU' and op == 0x050:
        return {rs2}, {rd}
    if slot == 'LSU' and op == 0x044:
        return {rs1, rs2}, set()
    if slot == 'LSU' and op == 0x053:
        return {rs1}, {rd}
    r = {rs1}
    if form == 'reg':
        r.add(rs2)
    return r, {rd}

def clean(s):
    return {r for r in s if r not in (62, 63)}

def mol_rw(kind, ws):
    reads, writes = set(), set()
    for k, (slot, x) in enumerate(zip(SLOTS[kind], ws)):
        if slot in ('ALU0', 'ALU1', 'LSU'):
            r, w = atom_rw(slot, x)
            reads |= r
            writes |= w
    return clean(reads), clean(writes)

def bru(kind, ws):
    if kind in (K_Q_BRU, K_AB):
        x = ws[0]
        if x >> 29 in BR_KIND:
            return x
    return None

def is_call(x):
    return x is not None and x >> 29 == 4 and (x >> 25) & 1 and not (x >> 23) & 1

def is_ret(x):
    return x is not None and x >> 29 == 4 and not (x >> 25) & 1 and (x >> 23) & 1

def stores(kind, ws):
    """[(value_reg, base_reg)] of st atoms in the molecule."""
    out = []
    for slot, x in zip(SLOTS[kind], ws):
        if slot == 'LSU' and (x >> 20) & 0x1ff == 0x044:
            out.append(((x >> 8) & 63, (x & 0xff) >> 2))
    return out

def loads(kind, ws):
    out = []
    for slot, x in zip(SLOTS[kind], ws):
        if slot == 'LSU' and (x >> 20) & 0x1ff == 0x050:
            out.append(((x >> 14) & 63, (x & 0xff) >> 2))
    return out

def sp_adjust(kind, ws):
    for slot, x in zip(SLOTS[kind], ws):
        if slot in ('ALU0', 'ALU1') and not ((x >> 29) & 3 and slot == 'ALU1'):
            if (x >> 20) & 0x1ff == 0x103 and (x >> 14) & 63 == SP and (x >> 8) & 63 == SP:
                return sx8(x & 0xff)
    return 0

def mfsr_link(kind, ws):
    for slot, x in zip(SLOTS[kind], ws):
        if slot == 'ALU1' and x >> 29 & 3 == 2 and (x >> 20) & 0x1ff == 0x060 and (x >> 8) & 63 == LINK:
            return (x >> 14) & 63
    return None

def main(path):
    img = open(path, 'rb').read()
    w = u32s(img)
    sync = sync_points(w, BASE, CODE_END)
    mols = [(a, k, ws) for a, k, ws in molecules(w, BASE, BASE, CODE_END, sync) if k != 'DATA']
    idx = {a: i for i, (a, k, ws) in enumerate(mols)}
    labels, calls = collect_labels(w, BASE, BASE, CODE_END)
    funcs = sorted(t for t in calls if t in idx)

    frame = collections.Counter(); saved = collections.Counter(); linkreg = collections.Counter()
    livein = collections.Counter(); leaf = 0; nonleaf = 0; nfunc = 0
    retw = collections.Counter(); reloaded = collections.Counter(); ret_hint = collections.Counter()
    for f in funcs:
        nfunc += 1
        i = idx[f]
        # straight-line entry path: until first branch (incl. its molecule)
        written, li, adj, sv, lk = set(), set(), 0, set(), None
        for j in range(i, min(i + 24, len(mols))):
            a, k, ws = mols[j]
            r, wr = mol_rw(k, ws)
            li |= (r - written - {SP})
            adj += sp_adjust(k, ws)
            m = mfsr_link(k, ws)
            if m is not None:
                lk = m
            for v, b in stores(k, ws):
                sv.add(v)
            written |= wr
            if bru(k, ws) is not None:
                break
        for r in li:
            livein[r] += 1
        frame[adj] += 1
        if lk is not None:
            linkreg[lk] += 1
            nonleaf += 1
        else:
            leaf += 1
        for r in sv:
            saved[r] += 1
    # epilogues: molecules ending in a return, look back 6 molecules
    for i, (a, k, ws) in enumerate(mols):
        x = bru(k, ws)
        if not is_ret(x):
            continue
        ret_hint[x & 0x7fffff] += 1
        lastw = {}
        for j in range(max(0, i - 6), i + 1):
            aa, kk, wws = mols[j]
            for v, b in loads(kk, wws):
                if b == SP or b in range(34, 40):
                    reloaded[v] += 1
            r, wr = mol_rw(kk, wws)
            for reg in wr:
                lastw[reg] = j
        for reg, j in lastw.items():
            retw[reg] += 1
    # call sites: registers read after the call before being written
    after = collections.Counter(); across = collections.Counter(); ncalls = 0
    for i, (a, k, ws) in enumerate(mols):
        if not is_call(bru(k, ws)):
            continue
        ncalls += 1
        written = set()
        for j in range(i + 1, min(i + 8, len(mols))):
            r, wr = mol_rw(mols[j][1], mols[j][2])
            for reg in r - written:
                after[reg] += 1
            written |= wr
            if bru(mols[j][1], mols[j][2]) is not None:
                break
        # args set up in the 3 molecules before and in the call molecule itself
        for j in range(max(0, i - 3), i + 1):
            r, wr = mol_rw(mols[j][1], mols[j][2])
            for reg in wr:
                across[reg] += 1

    def top(c, n=16):
        return ' '.join('%s:%d' % (GPR[r] if isinstance(r, int) and 0 <= r < 64 else r, v)
                        for r, v in c.most_common(n))
    print('functions entered by call: %d   call sites: %d' % (nfunc, ncalls))
    print('with mfsr %%link (non-leaf): %d   without (leaf or tail): %d' % (nonleaf, leaf))
    print('register receiving %%link in prologue: %s' % top(linkreg))
    print('stack adjust on entry (bytes): %s' % ' '.join('%d:%d' % kv for kv in sorted(frame.items())))
    print('registers stored in prologue: %s' % top(saved, 20))
    print('live-in (read before write) on entry: %s' % top(livein, 20))
    print('registers written by the call molecule and the 3 before it: %s' % top(across, 20))
    print('registers read after return before written: %s' % top(after, 20))
    print('registers reloaded from the frame before return: %s' % top(reloaded, 20))
    print('registers written in the 6 molecules before return: %s' % top(retw, 20))
    print('return hint field: %s' % ' '.join('0x%x:%d' % kv for kv in ret_hint.most_common(12)))

if __name__ == '__main__':
    main(sys.argv[1])
