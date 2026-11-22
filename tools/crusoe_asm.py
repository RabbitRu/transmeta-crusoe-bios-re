#!/usr/bin/env python3
"""Assembler for Transmeta Crusoe TM5x00 native VLIW code.

    crusoe_asm.py SOURCE.s -o OUT.bin [--org ADDR]
    crusoe_asm.py SOURCE.s --patch IMAGE -o PATCHED.image   # write into a CMS image
    crusoe_asm.py --selftest IMAGE                           # round-trip the whole CMS

Input is exactly the syntax printed by crusoe_dis.py, so a listing can be
edited and reassembled. One molecule per line:

    [ADDR:] [KIND] SLOT atom | SLOT atom ...      ; comment
    label:
    .org 0xa6798
    .word 0x00000000                    raw 32-bit word (padding / literals)

KIND (Q.imm, Q.bru, LA, AA, AI, AB) may be omitted; it is inferred from the
slots used. SLOT is IMM, BRU, ALU0, ALU1 or LSU. Atoms:

    imm 0x80000000                       IMM word
    br L / call L / brc.<cc> L / brc2.<cc> L / br.ind #0x7a / bru.raw 0x...
    addi %r47, %r47, -32                 imm8 form
    oril %r34, %zero, <imm>              imm32 form, value from the IMM slot
    add %r60, %r0, %r34                  register form ([1:0] = 3 unless .sN)
    ld %r27, [%r35], m=4 / st [%r47], %r25, m=12
    nop / nop.lsu
    suffixes: .cm (bit31 flag), .tN (LSU bits [30:29]), .sN (bits [1:0])

Branch targets are absolute CMS addresses (multiple of 8) or labels.
"""
import sys, os, re, struct
sys.path.insert(0, os.path.dirname(__file__))
from crusoe_isa import *

class AsmError(Exception):
    pass

def reg(s):
    s = s.strip()
    if s in GPR_NUM:
        return GPR_NUM[s]
    m = re.fullmatch(r'%r(\d+)', s)
    if m and int(m.group(1)) < 64:
        return int(m.group(1))
    raise AsmError('bad register %r' % s)

def spr(s):
    s = s.strip()
    if s in SPR_NUM:
        return SPR_NUM[s] - 64
    m = re.fullmatch(r'%s(\d+)', s)
    if m:
        return int(m.group(1))
    raise AsmError('bad special register %r' % s)

def num(s):
    return int(s.strip().lstrip('#'), 0)

def split_mnemonic(tok):
    """'ld.cm.s1' -> ('ld', cm=1, t=0, s=None)"""
    parts = tok.split('.')
    cm, t, sz = 0, 0, None
    while len(parts) > 1:
        p = parts[-1]
        if p == 'cm':
            cm = 1
        elif re.fullmatch(r't\d', p) and len(parts) > 1 and not (len(parts) == 2 and parts[0] == ''):
            t = int(p[1])
        elif re.fullmatch(r's\d', p):
            sz = int(p[1])
        else:
            break
        parts.pop()
    return '.'.join(parts), cm, t, sz

def enc_alu(text, slot, kind, k):
    text = text.strip()
    tok, _, rest = text.partition(' ')
    base, cm, tsfx, sz = split_mnemonic(tok)
    ops = [o.strip() for o in rest.split(',')] if rest.strip() else []
    if k == 1:
        top = FORMAT_BITS[kind]
        if cm:
            if kind in (K_Q_IMM, K_Q_BRU):
                raise AsmError('.cm not encodable in word 1 of a 128-bit molecule')
            top |= 4
    else:
        top = (cm << 2) | tsfx
    if base == 'nop':
        return (top << 29) | 0x14b00000
    if base == 'nop.lsu':
        return (top << 29) | 0x03b00600
    t, op = parse_opname(base)
    if t:
        if slot != 'ALU1':
            raise AsmError('typed opcode %s only valid in ALU1' % base)
        top |= t
    form = opform(op)
    if form == 'imm8':
        rd, rs1, lo = reg(ops[0]), reg(ops[1]), num(ops[2]) & 0xff
    elif form == 'imm32':
        if ops[2] != '<imm>':
            raise AsmError('imm32 form needs <imm> operand: %r' % text)
        rd, rs1 = reg(ops[0]), reg(ops[1])
        lo = num(ops[3]) if len(ops) > 3 else 0
    else:
        s2 = 3 if sz is None else sz
        if op == 0x050 and not t:
            rd = reg(ops[0]); b = reg(ops[1].strip('[]')); rs1 = num(ops[2].split('=')[1])
            lo = (b << 2) | s2
        elif op == 0x044 and not t:
            b = reg(ops[0].strip('[]')); rs1 = reg(ops[1]); rd = num(ops[2].split('=')[1])
            lo = (b << 2) | s2
        else:
            rd = reg(ops[0])
            rs1 = spr(ops[1]) if (t, op) in SPR_OPS else reg(ops[1])
            lo = (reg(ops[2]) << 2) | s2
    return (top << 29) | (op << 20) | (rd << 14) | (rs1 << 8) | lo

def enc_bru(text, labels):
    tok, _, rest = text.strip().partition(' ')
    rest = rest.strip()
    if tok == 'bru.raw':
        return num(rest)
    parts = tok.split('.')
    xb = 0
    if parts[-1] == 'x':
        xb = 1; parts.pop()
    ind = 0
    if parts[-1] == 'ind':
        ind = 1; parts.pop()
    if parts[0] in ('br', 'call'):
        kind, cc = 4, 1 if parts[0] == 'call' else 0
        if len(parts) > 1 and parts[1].startswith('k'):
            cc |= int(parts[1][1:])
    elif parts[0] in ('brc', 'brc2'):
        kind = 5 if parts[0] == 'brc' else 7
        cc = CC.index(parts[1])
    else:
        raise AsmError('bad branch %r' % text)
    if ind:
        field = num(rest)
    else:
        t = labels[rest] if rest in labels else num(rest)
        if t & 7:
            raise AsmError('branch target 0x%x not 8-byte aligned' % t)
        field = t >> 3
        if field >> 23:
            raise AsmError('branch target 0x%x beyond 64 MB' % t)
    return (kind << 29) | (cc << 25) | (xb << 24) | (ind << 23) | (field & 0x7fffff)

LINE_RE = re.compile(r'^\s*(?:([0-9a-fA-F]+):)?\s*(Q\.imm|Q\.bru|LA|AA|AI|AB)?\s*(.*)$')

def parse(src):
    """-> list of ('org', addr) | ('label', name) | ('mol', kind, [(slot, text)], lineno)"""
    items = []
    for n, line in enumerate(src.splitlines(), 1):
        line = line.split(';')[0].rstrip()
        if not line.strip():
            continue
        s = line.strip()
        if s.startswith('.org'):
            items.append(('org', int(s.split()[1], 0)))
            continue
        m = re.fullmatch(r'(?:([0-9a-fA-F]+):\s*)?\.word\s+(\S+)', s)
        if m:
            if m.group(1):
                items.append(('at', int(m.group(1), 16), n))
            items.append(('word', int(m.group(2), 0)))
            continue
        m = re.fullmatch(r'([A-Za-z_][\w.]*):', s)
        if m:
            items.append(('label', m.group(1)))
            continue
        m = LINE_RE.match(line)
        addr, kind, body = m.groups()
        if addr:
            items.append(('at', int(addr, 16), n))
        slots = []
        for part in body.split('|'):
            sl, _, atom = part.strip().partition(' ')
            if sl not in ('IMM', 'BRU', 'ALU0', 'ALU1', 'LSU'):
                raise AsmError('line %d: bad slot %r' % (n, sl))
            slots.append((sl, atom.strip()))
        if not kind:
            kind = infer_kind([s for s, a in slots], slots)
        items.append(('mol', kind, slots, n))
    return items

def infer_kind(names, slots):
    s = set(names)
    if 'LSU' in s and 'ALU0' in s:
        return K_Q_BRU if 'BRU' in s else K_Q_IMM
    if 'LSU' in s:
        return K_LA
    if 'BRU' in s:
        return K_AB
    if 'IMM' in s:
        return K_AI
    return K_AA

DEFAULT = {'IMM': 'imm 0x14b00000', 'ALU0': 'nop', 'ALU1': 'nop', 'LSU': 'nop.lsu'}

def assemble(src, org=0x8e000):
    items = parse(src)
    labels, pc = {}, org
    for it in items:                      # pass 1: addresses
        if it[0] == 'org':
            pc = it[1]
        elif it[0] == 'at':
            if it[1] != pc:
                raise AsmError('line %d: address %x but pc is %x' % (it[2], it[1], pc))
        elif it[0] == 'label':
            labels[it[1]] = pc
        elif it[0] == 'word':
            pc += 4
        else:
            pc += 4 * len(SLOTS[it[1]])
    out, pc, start = {}, org, org
    for it in items:                      # pass 2: encode
        if it[0] == 'org':
            pc = it[1]
            continue
        if it[0] == 'word':
            out[pc] = it[1]; pc += 4
            continue
        if it[0] != 'mol':
            continue
        kind, slots, n = it[1], dict(it[2]), it[3]
        extra = set(slots) - set(SLOTS[kind])
        if extra:
            raise AsmError('line %d: slot(s) %s not in a %s molecule' % (n, extra, kind))
        try:
            words = []
            for k, sl in enumerate(SLOTS[kind]):
                text = slots.get(sl, DEFAULT[sl] if sl != 'BRU' else None)
                if sl == 'IMM':
                    words.append(num(text.split()[1]))
                elif sl == 'BRU':
                    words.append(enc_bru(text, labels))
                else:
                    words.append(enc_alu(text, sl, kind, k))
        except (AsmError, ValueError, IndexError, KeyError) as e:
            raise AsmError('line %d: %s' % (n, e))
        got, _ = classify(words[0], words[1])
        if got != kind:
            raise AsmError('line %d: encodes as %s, not %s (imm32 ALU0 op needs AI)' % (n, got, kind))
        for i, x in enumerate(words):
            out[pc + 4 * i] = x
        pc += 4 * len(words)
    return out, labels

def to_bytes(words):
    lo, hi = min(words), max(words) + 4
    buf = bytearray(b'\0' * (hi - lo))
    for a, x in words.items():
        struct.pack_into('<I', buf, a - lo, x)
    return lo, bytes(buf)

def selftest(image):
    import io, crusoe_dis
    img = open(image, 'rb').read()
    f = io.StringIO()
    crusoe_dis.disasm(img, out=f)
    words, _ = assemble(f.getvalue())
    lo, blob = to_bytes(words)
    ref = img[lo - 0x8e000: lo - 0x8e000 + len(blob)]
    bad = sum(1 for i in range(0, len(blob), 4) if blob[i:i + 4] != ref[i:i + 4])
    print('round-trip %d bytes (%d molecules lines): %d mismatching words' %
          (len(blob), f.getvalue().count('\n'), bad))
    return bad == 0

def main(argv):
    if '--selftest' in argv:
        sys.exit(0 if selftest(argv[argv.index('--selftest') + 1]) else 1)
    src = open(argv[1]).read()
    org = int(argv[argv.index('--org') + 1], 0) if '--org' in argv else 0x8e000
    outp = argv[argv.index('-o') + 1]
    words, labels = assemble(src, org)
    lo, blob = to_bytes(words)
    if '--patch' in argv:
        img = bytearray(open(argv[argv.index('--patch') + 1], 'rb').read())
        for a, x in words.items():
            struct.pack_into('<I', img, a - 0x8e000, x)
        open(outp, 'wb').write(img)
        print('patched %d words into %s' % (len(words), outp))
    else:
        open(outp, 'wb').write(blob)
        print('wrote %d bytes at 0x%x to %s' % (len(blob), lo, outp))

if __name__ == '__main__':
    try:
        main(sys.argv)
    except AsmError as e:
        sys.exit('error: %s' % e)
